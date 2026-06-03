"""Defines PlayGameContext, feedback types, and resolves Blue/Red/Referee roles for a play_game run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from pydantic import BaseModel

from baps.core.run_config import RunConfig
from baps.core.roles import SpecRole
from baps.core.clients import (
    build_client_for_role,
    build_fallback_chain_for_role,
    build_role_client,
    make_fallback_chain_fn,
    resolve_backend_model,
)
from baps.models.models import ModelClient, Role
from baps.adapters.project_adapter import ProjectTypeAdapter, VerificationResult
from baps.northstar.northstar_projection import StateView
from baps.state.state import DeltaState, GameSpec, RedFinding, RefereeDecision, State
from baps.tools.tools import ToolExecutor


class PriorExportFeedback(BaseModel):
    """Feedback carrying the prior export verification result into the next Blue attempt."""

    prior_export_verification: VerificationResult


class AttemptRejection(BaseModel):
    """A single rejected attempt, capturing stage, reason, and validation error."""

    stage: SpecRole
    reason: str
    validation_error: str


class BlueValidationFeedback(BaseModel):
    """Feedback carrying a Blue output validation error back to the next Blue attempt."""

    attempt_rejection: AttemptRejection


class AttemptRejectionFeedback(BaseModel):
    """Feedback from a rejected attempt carrying Red/Referee findings for the next Blue attempt."""

    red_finding: RedFinding
    referee_decision: RefereeDecision
    candidate_verification: VerificationResult | None = None


PlayGameFeedback = (
    PriorExportFeedback | BlueValidationFeedback | AttemptRejectionFeedback
)


# Keep schemas colocated with role wiring to avoid duplicating literals.
RED_FINDING_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "disposition": {"type": "string", "enum": ["accept", "revise", "reject"]},
        "rationale": {"type": "string", "maxLength": 500},
        "success_condition_met": {"type": ["boolean", "null"]},
        "findings": {"type": "array", "items": {"type": "string", "maxLength": 300}},
    },
    "required": ["disposition", "rationale"],
    "additionalProperties": False,
}

_REFEREE_DECISION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "disposition": {"type": "string", "enum": ["accept", "revise", "reject"]},
        "rationale": {"type": "string", "maxLength": 500},
        "red_override": {"type": ["boolean", "null"]},
        "improvement_hints": {
            "type": "array",
            "items": {"type": "string", "maxLength": 300},
        },
    },
    "required": ["disposition", "rationale"],
    "additionalProperties": False,
}


class RoleContract(BaseModel):
    """Schema and constrained-decoding flag for a single role."""

    output_schema: type[BaseModel] | None
    constrained: bool


class VerifyCandidateFn(Protocol):
    """Protocol for candidate delta verification callables used within play_game."""

    def __call__(
        self,
        adapter: ProjectTypeAdapter,
        delta_state: DeltaState,
        state: State,
        artifact_id: str,
        *,
        sandbox_mode: str,
    ) -> VerificationResult | None:
        """Verify the candidate delta and return a VerificationResult, or None if not applicable."""
        ...


@dataclass  # internal only — no serialization boundary
class PlayGameContext:
    """Immutable per-game setup resolved once before the attempt loop."""

    resolved_adapter: ProjectTypeAdapter
    state: State
    game_spec: GameSpec
    state_view: StateView
    game_id: str
    workspace: Path | None
    sandbox_mode: str
    executor: ToolExecutor | None
    blue_role: Role
    red_role: Role
    referee_role: Role
    red_fallback_fn: Callable[[str], str] | None
    referee_fallback_fn: Callable[[str], str] | None
    depth: int
    max_attempts: int
    debug_event_fn: Callable[[str, dict[str, Any]], None]
    render_red_prompt_fn: Callable[
        [StateView, GameSpec, DeltaState, VerificationResult | None, str], str
    ]
    render_referee_prompt_fn: Callable[
        [StateView, GameSpec, DeltaState, RedFinding, VerificationResult | None, str],
        str,
    ]
    verify_candidate_fn: VerifyCandidateFn


def initial_play_game_feedback(
    verification_result: VerificationResult | None,
) -> PriorExportFeedback | None:
    """Return PriorExportFeedback from a verification result, or None if no result was provided."""
    if verification_result is None:
        return None
    return PriorExportFeedback(prior_export_verification=verification_result)


def resolve_play_game_roles(
    resolved_adapter: ProjectTypeAdapter,
    config: RunConfig | None,
    model_client: ModelClient | None,
    red_model_client: ModelClient | None,
    referee_model_client: ModelClient | None,
    build_client_for_role_fn: Any = build_client_for_role,
    build_role_client_fn: Any = build_role_client,
    blue_contract: RoleContract | None = None,
    red_contract: RoleContract | None = None,
    referee_contract: RoleContract | None = None,
) -> tuple[Role, Role, Role]:
    """Resolve and return (blue_role, red_role, referee_role) using explicit clients or config-derived ones."""
    if blue_contract is None:
        blue_contract = RoleContract(output_schema=None, constrained=False)
    if red_contract is None:
        red_contract = RoleContract(output_schema=RedFinding, constrained=True)
    if referee_contract is None:
        referee_contract = RoleContract(output_schema=RefereeDecision, constrained=True)

    def _schema_dict(schema: type[BaseModel] | None) -> dict | None:
        return schema.model_json_schema() if schema is not None else None

    def _get_client(explicit: ModelClient | None, role: str) -> ModelClient:
        if explicit is not None:
            return explicit
        if config is not None:
            return build_client_for_role_fn(role, config)
        return build_role_client_fn(role)

    blue_role = Role(
        SpecRole.BLUE,
        _get_client(model_client, SpecRole.BLUE),
        _schema_dict(blue_contract.output_schema),
        constrained=blue_contract.constrained,
    )
    red_role = Role(
        SpecRole.RED,
        _get_client(red_model_client, SpecRole.RED),
        _schema_dict(red_contract.output_schema),
        constrained=red_contract.constrained,
    )
    referee_role = Role(
        SpecRole.REFEREE,
        _get_client(referee_model_client, SpecRole.REFEREE),
        _schema_dict(referee_contract.output_schema),
        constrained=referee_contract.constrained,
    )
    return blue_role, red_role, referee_role


def build_play_game_fallbacks(
    config: RunConfig | None,
    red_model_client: ModelClient | None,
    referee_model_client: ModelClient | None,
    build_fallback_chain_for_role_fn: Any = build_fallback_chain_for_role,
) -> tuple[Path | None, Callable[[str], str] | None, Callable[[str], str] | None]:
    """Build and return (workspace, red_fallback_fn, referee_fallback_fn) from the config fallback chains."""
    workspace = config.workspace if config else None
    if config is None:
        return workspace, None, None
    try:
        red_primary = (
            resolve_backend_model(SpecRole.RED, config)[1]
            if red_model_client is None
            else "(provided)"
        )
    except ValueError:
        red_primary = "(unknown)"
    try:
        referee_primary = (
            resolve_backend_model(SpecRole.REFEREE, config)[1]
            if referee_model_client is None
            else "(provided)"
        )
    except ValueError:
        referee_primary = "(unknown)"
    red_fallback_fn = make_fallback_chain_fn(
        SpecRole.RED,
        red_primary,
        build_fallback_chain_for_role_fn(SpecRole.RED, config),
    )
    referee_fallback_fn = make_fallback_chain_fn(
        SpecRole.REFEREE,
        referee_primary,
        build_fallback_chain_for_role_fn(SpecRole.REFEREE, config),
    )
    return workspace, red_fallback_fn, referee_fallback_fn
