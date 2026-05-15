from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _require_non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("must be a non-empty string")
    return value


class Target(BaseModel):
    kind: str
    ref: str | None = None

    _validate_kind = field_validator("kind")(_require_non_empty)


PlannerGroundingStatus = Literal[
    "grounded",
    "weakly_grounded",
    "ungrounded",
    "underspecified",
]


class PlannerGroundingMetadata(BaseModel):
    grounding_status: PlannerGroundingStatus
    grounding_rationale: str
    metadata: dict = Field(default_factory=dict)

    _validate_grounding_rationale = field_validator("grounding_rationale")(_require_non_empty)


class GameRequest(BaseModel):
    game_type: str
    subject: str
    goal: str
    target_kind: str
    target_ref: str = ""
    state_source_ids: list[str] = Field(default_factory=list)
    planner_grounding: PlannerGroundingMetadata | None = None

    @field_validator("game_type", "subject", "goal", "target_kind")
    @classmethod
    def _non_empty_required_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("state_source_ids")
    @classmethod
    def _validate_state_source_ids(cls, value: list[str]) -> list[str]:
        for source_id in value:
            if not source_id.strip():
                raise ValueError("state_source_ids must contain non-empty strings")
        return value


class GameContract(BaseModel):
    id: str
    subject: str
    goal: str
    target: Target
    active_roles: list[str]
    max_rounds: int = 3
    scope_allowed: list[str] = Field(default_factory=list)
    scope_forbidden: list[str] = Field(default_factory=list)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_subject = field_validator("subject")(_require_non_empty)
    _validate_goal = field_validator("goal")(_require_non_empty)

    @field_validator("active_roles")
    @classmethod
    def validate_active_roles(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("active_roles must be non-empty")
        return value

    @field_validator("max_rounds")
    @classmethod
    def validate_max_rounds(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_rounds must be >= 1")
        return value


class Move(BaseModel):
    game_id: str
    role: str
    summary: str
    payload: dict = Field(default_factory=dict)

    _validate_game_id = field_validator("game_id")(_require_non_empty)
    _validate_role = field_validator("role")(_require_non_empty)
    _validate_summary = field_validator("summary")(_require_non_empty)


class Finding(BaseModel):
    game_id: str
    severity: str
    confidence: str
    claim: str
    evidence: list[str] = Field(default_factory=list)
    payload: dict = Field(default_factory=dict)
    block_integration: bool = False

    _validate_game_id = field_validator("game_id")(_require_non_empty)
    _validate_severity = field_validator("severity")(_require_non_empty)
    _validate_confidence = field_validator("confidence")(_require_non_empty)
    _validate_claim = field_validator("claim")(_require_non_empty)


class Decision(BaseModel):
    game_id: str
    decision: str
    rationale: str

    _validate_game_id = field_validator("game_id")(_require_non_empty)
    _validate_decision = field_validator("decision")(_require_non_empty)
    _validate_rationale = field_validator("rationale")(_require_non_empty)


class GameRecord(BaseModel):
    game_id: str
    contract: GameContract
    status: str
    created_at: str
    updated_at: str
    metadata: dict = Field(default_factory=dict)

    _validate_game_id = field_validator("game_id")(_require_non_empty)
    _validate_created_at = field_validator("created_at")(_require_non_empty)
    _validate_updated_at = field_validator("updated_at")(_require_non_empty)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        value = _require_non_empty(value)
        if value not in {"pending", "running", "completed", "failed"}:
            raise ValueError("status must be one of: pending, running, completed, failed")
        return value


class GameRound(BaseModel):
    round_number: int
    moves: list[Move] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    decision: Decision | None = None

    @field_validator("round_number")
    @classmethod
    def validate_round_number(cls, value: int) -> int:
        if value < 1:
            raise ValueError("round_number must be >= 1")
        return value


class GameState(BaseModel):
    game_id: str
    run_id: str
    current_round: int = 1
    rounds: list[GameRound] = Field(default_factory=list)
    final_decision: Decision | None = None

    _validate_game_id = field_validator("game_id")(_require_non_empty)
    _validate_run_id = field_validator("run_id")(_require_non_empty)

    @field_validator("current_round")
    @classmethod
    def validate_current_round(cls, value: int) -> int:
        if value < 1:
            raise ValueError("current_round must be >= 1")
        return value


TerminalOutcome = Literal[
    "accepted_locally",
    "rejected_locally",
    "revision_budget_exhausted",
]

IntegrationRecommendation = Literal[
    "integration_recommended",
    "do_not_integrate",
]

IntegrationOutcome = Literal["accepted", "rejected", "deferred"]
GoalAmendmentStatus = Literal["proposed", "approved", "rejected"]

IntegrationTargetKind = Literal[
    "accomplishment",
    "architecture",
    "capability",
    "discrepancy",
]

CritiqueLevel = Literal["low", "medium", "high"]

AgentRoleKind = Literal["blue", "red", "referee", "sponsor", "integrator", "worker"]

DiscrepancyKind = Literal[
    "missing_capability",
    "architecture_drift",
    "documentation_drift",
    "goal_mismatch",
    "unresolved_finding",
]

DiscrepancySeverity = Literal[
    "low",
    "medium",
    "high",
]

DiscrepancyStatus = Literal[
    "open",
    "resolved",
    "superseded",
]


class GameResponse(BaseModel):
    game_id: str
    run_id: str
    rounds_played: int
    max_rounds: int
    final_decision: Decision
    terminal_reason: str
    terminal_outcome: TerminalOutcome
    integration_recommendation: IntegrationRecommendation
    final_blue_summary: str
    final_red_claim: str
    trace_event_ids: list[str] = Field(default_factory=list)
    round_summaries: list["RoundSummary"] = Field(default_factory=list)

    _validate_game_id = field_validator("game_id")(_require_non_empty)
    _validate_run_id = field_validator("run_id")(_require_non_empty)
    _validate_terminal_reason = field_validator("terminal_reason")(_require_non_empty)
    _validate_terminal_outcome = field_validator("terminal_outcome")(_require_non_empty)
    _validate_integration_recommendation = field_validator("integration_recommendation")(
        _require_non_empty
    )
    _validate_final_blue_summary = field_validator("final_blue_summary")(_require_non_empty)
    _validate_final_red_claim = field_validator("final_red_claim")(_require_non_empty)

    @field_validator("rounds_played")
    @classmethod
    def validate_rounds_played(cls, value: int) -> int:
        if value < 1:
            raise ValueError("rounds_played must be >= 1")
        return value

    @field_validator("max_rounds")
    @classmethod
    def validate_max_rounds(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_rounds must be >= 1")
        return value


class RoundSummary(BaseModel):
    round_number: int
    blue_summary: str
    red_claim: str
    referee_decision: str
    referee_rationale: str

    _validate_blue_summary = field_validator("blue_summary")(_require_non_empty)
    _validate_red_claim = field_validator("red_claim")(_require_non_empty)
    _validate_referee_decision = field_validator("referee_decision")(_require_non_empty)
    _validate_referee_rationale = field_validator("referee_rationale")(_require_non_empty)

    @field_validator("round_number")
    @classmethod
    def validate_round_number(cls, value: int) -> int:
        if value < 1:
            raise ValueError("round_number must be >= 1")
        return value


class AcceptedAccomplishment(BaseModel):
    id: str
    summary: str
    source_run_id: str
    metadata: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_summary = field_validator("summary")(_require_non_empty)
    _validate_source_run_id = field_validator("source_run_id")(_require_non_empty)


class AcceptedArchitectureItem(BaseModel):
    id: str
    title: str
    source_event_id: str
    metadata: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_title = field_validator("title")(_require_non_empty)
    _validate_source_event_id = field_validator("source_event_id")(_require_non_empty)


class AcceptedCapability(BaseModel):
    id: str
    name: str
    source_run_id: str
    metadata: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_name = field_validator("name")(_require_non_empty)
    _validate_source_run_id = field_validator("source_run_id")(_require_non_empty)


class UnresolvedDiscrepancy(BaseModel):
    id: str
    summary: str
    kind: DiscrepancyKind
    severity: DiscrepancySeverity
    status: DiscrepancyStatus
    source_event_id: str
    related_artifact_id: str | None = None
    related_artifact_version: str | None = None
    metadata: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_summary = field_validator("summary")(_require_non_empty)
    _validate_source_event_id = field_validator("source_event_id")(_require_non_empty)

    @field_validator("related_artifact_id", "related_artifact_version")
    @classmethod
    def _validate_optional_non_empty_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)


class ActiveGameSummary(BaseModel):
    id: str
    title: str
    source_run_id: str
    metadata: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_title = field_validator("title")(_require_non_empty)
    _validate_source_run_id = field_validator("source_run_id")(_require_non_empty)


class ProjectedState(BaseModel):
    accepted_accomplishments: list[AcceptedAccomplishment] = Field(default_factory=list)
    accepted_architecture: list[AcceptedArchitectureItem] = Field(default_factory=list)
    accepted_capabilities: list[AcceptedCapability] = Field(default_factory=list)
    unresolved_discrepancies: list[UnresolvedDiscrepancy] = Field(default_factory=list)
    active_games: list[ActiveGameSummary] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class IntegrationDecision(BaseModel):
    id: str
    run_id: str
    outcome: IntegrationOutcome
    target_kind: IntegrationTargetKind
    summary: str
    rationale: str
    metadata: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_run_id = field_validator("run_id")(_require_non_empty)
    _validate_summary = field_validator("summary")(_require_non_empty)
    _validate_rationale = field_validator("rationale")(_require_non_empty)


class GoalAmendmentProposal(BaseModel):
    id: str
    summary: str
    rationale: str
    proposed_change: str
    source_run_id: str | None = None
    status: GoalAmendmentStatus = "proposed"
    metadata: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_summary = field_validator("summary")(_require_non_empty)
    _validate_rationale = field_validator("rationale")(_require_non_empty)
    _validate_proposed_change = field_validator("proposed_change")(_require_non_empty)

    @field_validator("source_run_id")
    @classmethod
    def _validate_optional_source_run_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)


class AgentProfile(BaseModel):
    id: str
    role: AgentRoleKind
    name: str
    critique_level: CritiqueLevel
    instructions: str
    metadata: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_name = field_validator("name")(_require_non_empty)
    _validate_instructions = field_validator("instructions")(_require_non_empty)


class DiscrepancyResolution(BaseModel):
    id: str
    discrepancy_id: str
    resolution_summary: str
    source_run_id: str
    metadata: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_discrepancy_id = field_validator("discrepancy_id")(_require_non_empty)
    _validate_resolution_summary = field_validator("resolution_summary")(_require_non_empty)
    _validate_source_run_id = field_validator("source_run_id")(_require_non_empty)


class DiscrepancySupersession(BaseModel):
    id: str
    superseded_discrepancy_id: str
    superseding_discrepancy_id: str
    rationale: str
    source_run_id: str
    metadata: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_superseded_discrepancy_id = field_validator("superseded_discrepancy_id")(
        _require_non_empty
    )
    _validate_superseding_discrepancy_id = field_validator("superseding_discrepancy_id")(
        _require_non_empty
    )
    _validate_rationale = field_validator("rationale")(_require_non_empty)
    _validate_source_run_id = field_validator("source_run_id")(_require_non_empty)


class AcceptedStateSupersession(BaseModel):
    id: str
    superseded_item_id: str
    superseding_item_id: str
    target_kind: IntegrationTargetKind
    rationale: str
    source_run_id: str
    metadata: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_superseded_item_id = field_validator("superseded_item_id")(_require_non_empty)
    _validate_superseding_item_id = field_validator("superseding_item_id")(_require_non_empty)
    _validate_rationale = field_validator("rationale")(_require_non_empty)
    _validate_source_run_id = field_validator("source_run_id")(_require_non_empty)


class AcceptedStateRevocation(BaseModel):
    id: str
    revoked_item_id: str
    target_kind: IntegrationTargetKind
    rationale: str
    source_run_id: str
    metadata: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_revoked_item_id = field_validator("revoked_item_id")(_require_non_empty)
    _validate_rationale = field_validator("rationale")(_require_non_empty)
    _validate_source_run_id = field_validator("source_run_id")(_require_non_empty)


class Artifact(BaseModel):
    id: str
    type: str
    current_version: str | None = None
    metadata: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_type = field_validator("type")(_require_non_empty)


class ArtifactVersion(BaseModel):
    artifact_id: str
    version_id: str
    path: str
    metadata: dict = Field(default_factory=dict)

    _validate_artifact_id = field_validator("artifact_id")(_require_non_empty)
    _validate_version_id = field_validator("version_id")(_require_non_empty)
    _validate_path = field_validator("path")(_require_non_empty)


class ArtifactChange(BaseModel):
    artifact_id: str
    change_id: str
    base_version: str
    description: str
    diff: str | None = None
    metadata: dict = Field(default_factory=dict)

    _validate_artifact_id = field_validator("artifact_id")(_require_non_empty)
    _validate_change_id = field_validator("change_id")(_require_non_empty)
    _validate_base_version = field_validator("base_version")(_require_non_empty)
    _validate_description = field_validator("description")(_require_non_empty)


class ArtifactAdapterResult(BaseModel):
    artifact_id: str
    version_id: str | None = None
    change_id: str | None = None
    message: str

    _validate_artifact_id = field_validator("artifact_id")(_require_non_empty)
    _validate_message = field_validator("message")(_require_non_empty)


class ArtifactProposalRecord(BaseModel):
    id: str
    artifact_id: str
    change_id: str
    source_run_id: str
    integration_decision_id: str | None = None
    status: Literal["proposed", "accepted", "rejected"] = "proposed"
    summary: str
    metadata: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_artifact_id = field_validator("artifact_id")(_require_non_empty)
    _validate_change_id = field_validator("change_id")(_require_non_empty)
    _validate_source_run_id = field_validator("source_run_id")(_require_non_empty)
    _validate_summary = field_validator("summary")(_require_non_empty)

    @field_validator("integration_decision_id")
    @classmethod
    def _validate_optional_integration_decision_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)


class Event(BaseModel):
    id: str
    type: str
    payload: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_type = field_validator("type")(_require_non_empty)
