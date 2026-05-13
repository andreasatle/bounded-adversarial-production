from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic import field_validator

from baps.prompt_assembly import PromptSection


class GameTypePromptSections(BaseModel):
    blue_sections: list[PromptSection] = Field(default_factory=list)
    red_sections: list[PromptSection] = Field(default_factory=list)
    referee_sections: list[PromptSection] = Field(default_factory=list)


class GameDefinition(BaseModel):
    id: str
    name: str
    description: str
    prompt_sections: GameTypePromptSections

    @field_validator("id", "name", "description")
    @classmethod
    def _non_empty_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value


def make_documentation_refinement_game_definition() -> GameDefinition:
    return GameDefinition(
        id="documentation-refinement",
        name="Documentation Refinement",
        description=(
            "Refine documentation deltas for clarity and correctness with bounded adversarial critique."
        ),
        prompt_sections=GameTypePromptSections(
        blue_sections=[
            PromptSection(
                name="Game Type",
                content=(
                    "Game type is documentation refinement. Improve clarity, correctness, "
                    "minimality, and non-redundancy while preserving intent."
                ),
            ),
        ],
        red_sections=[
            PromptSection(
                name="Game Type Scope",
                content=(
                    "Red critiques only the current Blue-produced delta from this game. "
                    "External context is supporting evidence, not expanded audit scope."
                ),
            ),
            PromptSection(
                name="Materiality Rule",
                content=(
                    "Material findings are actionable issues requiring revision. "
                    "Non-material findings are minor notes, praise, or no required change."
                ),
            ),
        ],
        referee_sections=[
            PromptSection(
                name="Game Type Convergence",
                content=(
                    "Referee converges toward correctness and clarity. "
                    "Accept when Red reports no material issue. "
                    "Accept when Red provides praise, confirmation, minor wording preference, or optional polish. "
                    "Revise only when Red identifies a material discrepancy that another round is expected to reduce. "
                    "Reject only for blocking or invalid candidates. "
                    "Do not recommend another revision merely because the candidate could be marginally polished. "
                    "The rationale must support the already-fixed structured decision."
                ),
            ),
        ],
        ),
    )


def make_documentation_refinement_game_type() -> GameTypePromptSections:
    return make_documentation_refinement_game_definition().prompt_sections


def get_builtin_game_definition(game_type: str) -> GameDefinition:
    if game_type == "documentation-refinement":
        return make_documentation_refinement_game_definition()
    raise ValueError(
        f"unknown game type: {game_type}. supported game types: documentation-refinement"
    )
