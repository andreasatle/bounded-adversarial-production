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


class Artifact(BaseModel):
    id: str
    type: str
    current_version: str | None = None
    metadata: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_type = field_validator("type")(_require_non_empty)


class Event(BaseModel):
    id: str
    type: str
    payload: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_type = field_validator("type")(_require_non_empty)
