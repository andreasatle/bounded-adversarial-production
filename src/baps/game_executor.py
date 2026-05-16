from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field, field_validator

from baps.state_progressor import GameProposal


def _require_non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("must be a non-empty string")
    return value


class GameExecutionResult(BaseModel):
    id: str
    game_proposal_id: str
    status: str
    summary: str
    state_delta: str
    risks: list[str] = Field(default_factory=list)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_game_proposal_id = field_validator("game_proposal_id")(_require_non_empty)
    _validate_status = field_validator("status")(_require_non_empty)
    _validate_summary = field_validator("summary")(_require_non_empty)
    _validate_state_delta = field_validator("state_delta")(_require_non_empty)


class GameExecutor(Protocol):
    def execute(self, game: GameProposal) -> GameExecutionResult:
        ...


class FakeGameExecutor:
    def __init__(self, result: GameExecutionResult):
        self.result = result

    def execute(self, game: GameProposal) -> GameExecutionResult:
        return GameExecutionResult(
            id=self.result.id,
            game_proposal_id=game.id,
            status=self.result.status,
            summary=self.result.summary,
            state_delta=self.result.state_delta,
            risks=list(self.result.risks),
        )
