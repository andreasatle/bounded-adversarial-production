from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field, field_validator

from baps.northstar_projection import NorthStarView


def _require_non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("must be a non-empty string")
    return value


class StateProgressorInput(BaseModel):
    id: str
    northstar_view: NorthStarView
    runtime_objective: str

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_runtime_objective = field_validator("runtime_objective")(_require_non_empty)


class GameProposal(BaseModel):
    id: str
    title: str
    description: str
    expected_state_delta: str
    risks: list[str] = Field(default_factory=list)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_title = field_validator("title")(_require_non_empty)
    _validate_description = field_validator("description")(_require_non_empty)
    _validate_expected_state_delta = field_validator("expected_state_delta")(_require_non_empty)


class StateProgressionProposal(BaseModel):
    id: str
    input_id: str
    game_proposal: GameProposal
    rationale: str

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_input_id = field_validator("input_id")(_require_non_empty)
    _validate_rationale = field_validator("rationale")(_require_non_empty)


class StateProgressor(Protocol):
    def progress(self, input: StateProgressorInput) -> StateProgressionProposal:
        ...


class FakeStateProgressor:
    def __init__(self, game_proposal: GameProposal, rationale: str):
        self.game_proposal = game_proposal
        self.rationale = _require_non_empty(rationale)

    def progress(self, input: StateProgressorInput) -> StateProgressionProposal:
        return StateProgressionProposal(
            id=f"state-progression:{input.id}:{self.game_proposal.id}",
            input_id=input.id,
            game_proposal=self.game_proposal.model_copy(deep=True),
            rationale=self.rationale,
        )


def render_state_progressor_prompt(input: StateProgressorInput) -> str:
    sections = (
        (
            "State Progressor Task",
            (
                "Propose one deterministic game candidate aligned to the runtime objective and "
                "the provided North Star view."
            ),
        ),
        ("Runtime Objective", input.runtime_objective),
        ("North Star View", input.northstar_view.content),
        (
            "Required Output",
            (
                "Provide:\n"
                "- game proposal title\n"
                "- game proposal description\n"
                "- expected state delta\n"
                "- risks\n"
                "- rationale"
            ),
        ),
    )
    return "\n\n".join(f"## {title}\n{content}" for title, content in sections)
