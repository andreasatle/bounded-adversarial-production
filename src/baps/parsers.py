from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from baps.clients import SpecRole
from baps.model_output import parse_model_output
from baps.project_adapter import ProjectTypeAdapter
from baps.state import (
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
        super().__init__(rationale)
        self.rationale = rationale
        self.proposed_northstar = proposed_northstar


_CREATE_GAME_ALL_KEYS = frozenset({
    "no_new_game", "reason",
    "northstar_update_needed", "rationale", "proposed_northstar",
    "decompose", "sub_gaps",
    "objective", "target_artifact_id", "allowed_delta_type", "success_condition",
    "max_words", "context_chain",
})

_DECOMPOSE_EMPTY_SUBGAPS_CORRECTION_PROMPT = (
    "Your previous decompose response contained sub_gaps with empty description fields. "
    "Every sub_gap must have a non-empty, meaningful description string. "
    "Return a corrected JSON object where each sub_gap.description is a non-empty string."
)

_UNRECOGNIZABLE_SHAPE_CORRECTION_PROMPT = (
    "Your previous response did not match any valid create_game response shape. "
    "Return exactly one of:\n"
    '- GameSpec: {"objective": "...", "target_artifact_id": "...", "allowed_delta_type": "...", "success_condition": "..."}\n'
    '- Decompose: {"decompose": true, "rationale": "...", "sub_gaps": [{"description": "..."}, ...]}\n'
    '- No new game: {"no_new_game": true, "reason": "..."}\n'
    "Return only a JSON object. No prose, no extra keys."
)

_RED_REQUIRED_KEYS = frozenset({"disposition", "rationale"})
_RED_ALL_KEYS = frozenset({"disposition", "rationale", "success_condition_met", "findings"})
_REFEREE_REQUIRED_KEYS = frozenset({"disposition", "rationale"})
_REFEREE_ALL_KEYS = frozenset({"disposition", "rationale", "red_override", "improvement_hints"})


def _parse_create_game_output(
    text: str,
    max_sub_gaps: int = 5,
    workspace: Path | None = None,
    retry_fn: Any = None,
    fallback_fn: Any = None,
) -> GameSpec | DecomposeSpec:
    parsed = parse_model_output(
        text,
        _CREATE_GAME_ALL_KEYS,
        context=SpecRole.CREATE_GAME,
        workspace=workspace,
        retry_fn=retry_fn,
        fallback_fn=fallback_fn,
    )

    if parsed.get("no_new_game") is True:
        reason = str(parsed.get("reason", "")).strip()
        if not reason:
            raise ValueError("create_game no-game response reason must be non-empty")
        raise NoNewGameError(reason)

    if parsed.get("northstar_update_needed") is True:
        rationale = str(parsed.get("rationale", "")).strip()
        if not rationale:
            raise ValueError(
                "create_game northstar_update_needed response rationale must be non-empty"
            )
        proposed_northstar = str(parsed.get("proposed_northstar", "")).strip()
        if not proposed_northstar:
            raise ValueError(
                "create_game northstar_update_needed response proposed_northstar must be non-empty"
            )
        raise NorthStarUpdateNeededError(rationale=rationale, proposed_northstar=proposed_northstar)

    if parsed.get("decompose") is True:
        rationale = str(parsed.get("rationale", "")).strip()
        if not rationale:
            raise ValueError("create_game decompose response rationale must be non-empty")
        sub_gaps_raw = parsed.get("sub_gaps")
        if not isinstance(sub_gaps_raw, list) or not sub_gaps_raw:
            raise ValueError("create_game decompose response sub_gaps must be a non-empty list")

        # Build descriptions, filtering empty ones before Pydantic validation.
        raw_descriptions = [
            str(sg.get("description", "")).strip()
            for sg in sub_gaps_raw
            if isinstance(sg, dict)
        ]
        valid_descriptions = [d for d in raw_descriptions if d]
        if len(valid_descriptions) < len(raw_descriptions):
            logger.warning(
                "[create_game] stripped %d sub-gap(s) with empty description",
                len(raw_descriptions) - len(valid_descriptions),
            )

        if not valid_descriptions:
            if fallback_fn is not None:
                logger.warning(
                    "[create_game] all sub-gaps had empty descriptions; escalating to fallback model"
                )
                raw = fallback_fn(_DECOMPOSE_EMPTY_SUBGAPS_CORRECTION_PROMPT)
                return _parse_create_game_output(raw, max_sub_gaps=max_sub_gaps, workspace=workspace)
            raise ValueError("create_game decompose response sub_gaps contained no valid entries")

        sub_gaps = tuple(SubGapSpec(description=d) for d in valid_descriptions)
        if len(sub_gaps) > max_sub_gaps:
            logger.warning(
                "[create_game] DecomposeSpec contained %d sub-gaps; truncating to max_sub_gaps=%d",
                len(sub_gaps), max_sub_gaps,
            )
            sub_gaps = sub_gaps[:max_sub_gaps]
        return DecomposeSpec(rationale=rationale, sub_gaps=sub_gaps)

    # GameSpec branch
    _game_spec_required = {"objective", "target_artifact_id", "allowed_delta_type", "success_condition"}
    if not _game_spec_required.issubset(parsed.keys()):
        if fallback_fn is not None:
            logger.warning(
                "[create_game] unrecognizable response shape (keys: %s); escalating to fallback model",
                sorted(parsed.keys()),
            )
            raw = fallback_fn(_UNRECOGNIZABLE_SHAPE_CORRECTION_PROMPT)
            return _parse_create_game_output(raw, max_sub_gaps=max_sub_gaps, workspace=workspace)
        raise ValueError(
            "create_game model output must contain exactly keys: "
            "objective, target_artifact_id, allowed_delta_type, success_condition"
        )
    try:
        return GameSpec.model_validate(parsed)
    except ValidationError as exc:
        raise ValueError("create_game model output failed GameSpec validation") from exc


def _normalize_game_spec_with_adapter(
    adapter: ProjectTypeAdapter,
    game_spec: GameSpec,
    state: State,
    config: dict[str, Any],
) -> GameSpec:
    normalizer = getattr(adapter, "normalize_game_spec", None)
    if normalizer is None:
        return game_spec
    return normalizer(game_spec, state, config)


def _parse_role_output(
    text: str,
    all_keys: frozenset[str],
    required_keys: frozenset[str],
    model_cls: type,
    context: str,
    workspace: Path | None = None,
    retry_fn: Any = None,
    fallback_fn: Any = None,
) -> Any:
    parsed = parse_model_output(
        text, all_keys, context=context, workspace=workspace,
        retry_fn=retry_fn, fallback_fn=fallback_fn,
    )
    missing = required_keys - set(parsed.keys())
    if missing:
        raise ValueError(f"{context} model output missing required keys: {sorted(missing)}")
    try:
        return model_cls.model_validate(parsed)
    except ValidationError as exc:
        raise ValueError(
            f"{context} model output failed {model_cls.__name__} validation"
        ) from exc


def _parse_red_finding_json(
    text: str,
    workspace: Path | None = None,
    retry_fn: Any = None,
    fallback_fn: Any = None,
) -> RedFinding:
    return _parse_role_output(
        text, _RED_ALL_KEYS, _RED_REQUIRED_KEYS, RedFinding,
        context=SpecRole.RED, workspace=workspace, retry_fn=retry_fn, fallback_fn=fallback_fn,
    )


def _parse_referee_decision_json(
    text: str,
    workspace: Path | None = None,
    retry_fn: Any = None,
    fallback_fn: Any = None,
) -> RefereeDecision:
    return _parse_role_output(
        text, _REFEREE_ALL_KEYS, _REFEREE_REQUIRED_KEYS, RefereeDecision,
        context=SpecRole.REFEREE, workspace=workspace, retry_fn=retry_fn, fallback_fn=fallback_fn,
    )
