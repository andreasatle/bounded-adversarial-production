"""Parses model output for create_game, Red, and Referee roles into typed domain objects."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from baps.adapters.project_adapter import ProjectTypeAdapter
from baps.core.roles import SpecRole
from baps.core.run_config import RunConfig
from baps.models.model_output import ParseRecoveryRecord, parse_model_output
from baps.state.state import (
    DecomposeSpec,
    GameSpec,
    RedFinding,
    RefereeDecision,
    State,
    SubGapSpec,
)

logger = logging.getLogger(__name__)


class NoNewGameError(ValueError):
    """Raised when the model explicitly indicates no new game is available."""


class NorthStarUpdateNeededError(ValueError):
    """Raised when CreateGame signals the trajectory has drifted from NorthStar intent."""

    def __init__(self, rationale: str, proposed_northstar: str) -> None:
        """Initialize the instance."""
        super().__init__(rationale)
        self.rationale = rationale
        self.proposed_northstar = proposed_northstar


_CREATE_GAME_ALL_KEYS = frozenset(
    {
        "kind",
        "objective",
        "target_artifact_id",
        "allowed_delta_type",
        "success_condition",
        "max_words",
        "context_chain",
        "target_entity",
        "rationale",
        "sub_gaps",
        "reason",
        "proposed_northstar",
    }
)

_DECOMPOSE_EMPTY_SUBGAPS_CORRECTION_PROMPT = (
    "Your previous decompose response contained sub_gaps with empty description fields. "
    "Every sub_gap must have a non-empty, meaningful description string. "
    "Return a corrected JSON object where each sub_gap.description is a non-empty string, "
    'and include "kind": "decompose".'
)

_UNRECOGNIZABLE_SHAPE_CORRECTION_PROMPT = (
    "Your previous response did not match any valid create_game response shape. "
    "Return exactly one of:\n"
    '- {"kind": "game_spec", "objective": "...", "target_artifact_id": "...", "allowed_delta_type": "...", "success_condition": "..."}\n'
    '- {"kind": "decompose", "rationale": "...", "sub_gaps": [{"description": "..."}, ...]}\n'
    "Return only a JSON object. No prose, no extra keys.\n"
    "Do not return no_new_game or northstar_update_needed — those require the full StateView context "
    "which is not available in this correction step."
)

_RED_REQUIRED_KEYS = frozenset({"disposition", "rationale"})
_RED_ALL_KEYS = frozenset({"disposition", "rationale", "success_condition_met", "findings"})
_REFEREE_REQUIRED_KEYS = frozenset({"disposition", "rationale"})
_REFEREE_ALL_KEYS = frozenset({"disposition", "rationale", "red_override", "improvement_hints"})

_GAME_SPEC_REQUIRED = frozenset({"objective", "target_artifact_id", "allowed_delta_type", "success_condition"})


def parse_create_game_output(
    text: str,
    max_sub_gaps: int = 5,
    workspace: Path | None = None,
    retry_fn: Any = None,
    fallback_fn: Any = None,
) -> GameSpec | DecomposeSpec:
    """Parse and return create game output."""
    parsed, _ = parse_model_output(
        text,
        _CREATE_GAME_ALL_KEYS,
        context=SpecRole.CREATE_GAME,
        workspace=workspace,
        retry_fn=retry_fn,
        fallback_fn=fallback_fn,
    )

    kind = parsed.get("kind")

    if kind == "no_new_game":
        reason = str(parsed.get("reason", "")).strip()
        if not reason:
            raise ValueError("create_game no-game response reason must be non-empty")
        raise NoNewGameError(reason)

    if kind == "northstar_update_needed":
        rationale = str(parsed.get("rationale", "")).strip()
        if not rationale:
            raise ValueError("create_game northstar_update_needed response rationale must be non-empty")
        proposed_northstar = str(parsed.get("proposed_northstar", "")).strip()
        if not proposed_northstar:
            raise ValueError("create_game northstar_update_needed response proposed_northstar must be non-empty")
        raise NorthStarUpdateNeededError(rationale=rationale, proposed_northstar=proposed_northstar)

    if kind == "decompose":
        rationale = str(parsed.get("rationale", "")).strip()
        if not rationale:
            raise ValueError("create_game decompose response rationale must be non-empty")
        sub_gaps_raw = parsed.get("sub_gaps")
        if not isinstance(sub_gaps_raw, list) or not sub_gaps_raw:
            raise ValueError("create_game decompose response sub_gaps must be a non-empty list")

        raw_descriptions = [str(sg.get("description", "")).strip() for sg in sub_gaps_raw if isinstance(sg, dict)]
        valid_descriptions = [d for d in raw_descriptions if d]
        if len(valid_descriptions) < len(raw_descriptions):
            logger.warning(
                "[create_game] stripped %d sub-gap(s) with empty description",
                len(raw_descriptions) - len(valid_descriptions),
            )

        if not valid_descriptions:
            if fallback_fn is not None:
                logger.warning("[create_game] all sub-gaps had empty descriptions; escalating to fallback model")
                raw = fallback_fn(_DECOMPOSE_EMPTY_SUBGAPS_CORRECTION_PROMPT)
                return parse_create_game_output(raw, max_sub_gaps=max_sub_gaps, workspace=workspace)
            raise ValueError("create_game decompose response sub_gaps contained no valid entries")

        sub_gaps = tuple(SubGapSpec(description=d) for d in valid_descriptions)
        if len(sub_gaps) > max_sub_gaps:
            logger.warning(
                "[create_game] DecomposeSpec contained %d sub-gaps; truncating to max_sub_gaps=%d",
                len(sub_gaps),
                max_sub_gaps,
            )
            sub_gaps = sub_gaps[:max_sub_gaps]
        return DecomposeSpec(rationale=rationale, sub_gaps=sub_gaps)

    if kind == "game_spec":
        missing = _GAME_SPEC_REQUIRED - parsed.keys()
        if missing:
            raise ValueError(f"create_game model output missing required keys: {', '.join(sorted(missing))}")
        try:
            return GameSpec.model_validate(parsed)
        except ValidationError as exc:
            raise ValueError("create_game model output failed GameSpec validation") from exc

    # Unknown or missing kind — shape failure; trigger correction retry/fallback.
    if retry_fn is not None:
        logger.warning(
            "[create_game] unrecognizable response shape (keys: %s); retrying with correction prompt",
            sorted(parsed.keys()),
        )
        try:
            raw = retry_fn(_UNRECOGNIZABLE_SHAPE_CORRECTION_PROMPT)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[create_game] retry_fn raised during shape correction: %s", exc)
        else:
            try:
                return parse_create_game_output(raw, max_sub_gaps=max_sub_gaps, workspace=workspace)
            except (NoNewGameError, NorthStarUpdateNeededError, ValueError):
                logger.warning("[create_game] correction retry returned invalid response; treating as shape failure")
    if fallback_fn is not None:
        logger.warning(
            "[create_game] unrecognizable response shape (keys: %s); escalating to fallback model",
            sorted(parsed.keys()),
        )
        raw = fallback_fn(_UNRECOGNIZABLE_SHAPE_CORRECTION_PROMPT)
        try:
            return parse_create_game_output(raw, max_sub_gaps=max_sub_gaps, workspace=workspace)
        except (NoNewGameError, NorthStarUpdateNeededError):
            logger.warning(
                "[create_game] fallback returned terminal signal without StateView context; treating as shape failure"
            )
    raise ValueError("create_game model output missing required keys: kind")


def normalize_game_spec_with_adapter(
    adapter: ProjectTypeAdapter,
    game_spec: GameSpec,
    state: State,
    config: RunConfig,
) -> GameSpec:
    """Normalize and return game spec with adapter."""
    normalizer = getattr(adapter, "normalize_game_spec", None)
    if normalizer is None:
        return game_spec
    return normalizer(game_spec, state, config.to_adapter_config())


def _parse_role_output(
    text: str,
    all_keys: frozenset[str],
    required_keys: frozenset[str],
    model_cls: type,
    context: str,
    workspace: Path | None = None,
    retry_fn: Any = None,
    fallback_fn: Any = None,
) -> tuple[Any, ParseRecoveryRecord]:
    """Parse and return role output."""
    parsed, recovery = parse_model_output(
        text,
        all_keys,
        context=context,
        workspace=workspace,
        retry_fn=retry_fn,
        fallback_fn=fallback_fn,
    )
    missing = required_keys - set(parsed.keys())
    if missing:
        raise ValueError(f"{context} model output missing required keys: {sorted(missing)}")
    try:
        return model_cls.model_validate(parsed), recovery
    except ValidationError as exc:
        raise ValueError(f"{context} model output failed {model_cls.__name__} validation") from exc


def parse_red_finding_json(
    text: str,
    workspace: Path | None = None,
    retry_fn: Any = None,
    fallback_fn: Any = None,
) -> tuple[RedFinding, ParseRecoveryRecord]:
    """Parse and return red finding json."""
    return _parse_role_output(
        text,
        _RED_ALL_KEYS,
        _RED_REQUIRED_KEYS,
        RedFinding,
        context=SpecRole.RED,
        workspace=workspace,
        retry_fn=retry_fn,
        fallback_fn=fallback_fn,
    )


def parse_referee_decision_json(
    text: str,
    workspace: Path | None = None,
    retry_fn: Any = None,
    fallback_fn: Any = None,
) -> tuple[RefereeDecision, ParseRecoveryRecord]:
    """Parse and return referee decision json."""
    return _parse_role_output(
        text,
        _REFEREE_ALL_KEYS,
        _REFEREE_REQUIRED_KEYS,
        RefereeDecision,
        context=SpecRole.REFEREE,
        workspace=workspace,
        retry_fn=retry_fn,
        fallback_fn=fallback_fn,
    )
