from __future__ import annotations

from baps.example_roles import make_prompt_blue_role, make_prompt_red_role, make_prompt_referee_role
from baps.game_types import GameTypePromptSections
from baps.models import ModelClient
from baps.prompt_assembly import PromptSection, PromptSpec, assemble_prompt


def build_prompt_roles(
    *,
    model_client: ModelClient,
    prompt_sections: GameTypePromptSections,
    shared_context: str,
    red_material: bool,
):
    blue_template = assemble_prompt(
        PromptSpec(
            sections=[
                PromptSection(
                    name="Role",
                    content=(
                        "Using shared context, provide one concise candidate answer for goal `{goal}`."
                    ),
                ),
                PromptSection(
                    name="Shared Context",
                    content="Shared context:\n{shared_context}",
                ),
                *prompt_sections.blue_sections,
            ]
        )
    )

    red_template = assemble_prompt(
        PromptSpec(
            sections=[
                PromptSection(
                    name="Scope",
                    content=(
                        "Critique only this Blue move/change from the current game: `{blue_summary}`. "
                        "Do not perform a general audit. Use shared context only as supporting evidence."
                    ),
                ),
                PromptSection(
                    name="Shared Context",
                    content="Shared context:\n{shared_context}",
                ),
                PromptSection(
                    name="Output Format",
                    content="MATERIAL: yes|no\nCLAIM: concise critique/assessment",
                ),
                *prompt_sections.red_sections,
            ]
        )
    )

    referee_template = assemble_prompt(
        PromptSpec(
            sections=[
                PromptSection(
                    name="Decision",
                    content=(
                        "Structured decision is already fixed to `{decision}`. "
                        "Provide one concise rationale supporting that fixed decision. "
                        "Do not contradict or reselect the decision."
                    ),
                ),
                PromptSection(
                    name="Inputs",
                    content="Blue move: `{blue_summary}`. Red finding: `{red_claim}`.",
                ),
                PromptSection(
                    name="Shared Context",
                    content="Shared context:\n{shared_context}",
                ),
                *prompt_sections.referee_sections,
            ]
        )
    )

    extra_context = {"shared_context": shared_context}
    blue_role = make_prompt_blue_role(
        model_client,
        template=blue_template,
        extra_context=extra_context,
    )
    red_role = make_prompt_red_role(
        model_client,
        template=red_template,
        extra_context=extra_context,
        default_material=red_material,
    )
    referee_role = make_prompt_referee_role(
        model_client,
        template=referee_template,
        extra_context=extra_context,
    )
    return blue_role, red_role, referee_role
