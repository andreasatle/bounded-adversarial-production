from __future__ import annotations

from pydantic import BaseModel, Field

from baps.prompt_assembly import PromptSection


class GameTypePromptSections(BaseModel):
    blue_sections: list[PromptSection] = Field(default_factory=list)
    red_sections: list[PromptSection] = Field(default_factory=list)
    referee_sections: list[PromptSection] = Field(default_factory=list)


def make_documentation_refinement_game_type() -> GameTypePromptSections:
    return GameTypePromptSections(
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
                    "Accept when no material discrepancy remains."
                ),
            ),
        ],
    )
