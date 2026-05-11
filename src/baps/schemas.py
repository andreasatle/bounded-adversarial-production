from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


def _require_non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("must be a non-empty string")
    return value


class Target(BaseModel):
    kind: str
    ref: str | None = None

    _validate_kind = field_validator("kind")(_require_non_empty)


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
    current_round: int = 1
    rounds: list[GameRound] = Field(default_factory=list)
    final_decision: Decision | None = None

    _validate_game_id = field_validator("game_id")(_require_non_empty)

    @field_validator("current_round")
    @classmethod
    def validate_current_round(cls, value: int) -> int:
        if value < 1:
            raise ValueError("current_round must be >= 1")
        return value


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


class Event(BaseModel):
    id: str
    type: str
    payload: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_type = field_validator("type")(_require_non_empty)
