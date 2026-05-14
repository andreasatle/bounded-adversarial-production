from __future__ import annotations

from baps.example_roles import make_prompt_blue_role, make_prompt_red_role, make_prompt_referee_role
from baps.game_types import GameTypePromptSections
from baps.models import ModelClient
from baps.prompt_assembly import PromptSection, PromptSpec, assemble_prompt
from baps.schemas import AgentProfile


def _validate_profile_role(profile: AgentProfile | None, expected_role: str, arg_name: str) -> None:
    if profile is None:
        return
    if profile.role != expected_role:
        raise ValueError(f"{arg_name}.role must be '{expected_role}'")


def _profile_section(profile: AgentProfile | None) -> list[PromptSection]:
    if profile is None:
        return []
    return [
        PromptSection(
            name="Agent Profile",
            content=(
                f"Profile name: {profile.name}\n"
                f"Role: {profile.role}\n"
                f"Critique level: {profile.critique_level}\n"
                f"Instructions: {profile.instructions}"
            ),
        )
    ]


def default_blue_profile() -> AgentProfile:
    return AgentProfile(
        id="builtin:blue",
        role="blue",
        name="Built-in Blue",
        critique_level="low",
        instructions=(
            "Produce one bounded candidate move for the current goal. "
            "Prefer minimal, scoped changes that fit the stated target."
        ),
    )


def default_red_profile() -> AgentProfile:
    return AgentProfile(
        id="builtin:red",
        role="red",
        name="Built-in Red",
        critique_level="high",
        instructions=(
            "Provide scoped adversarial critique of the current Blue move only. "
            "Prioritize material issues with concrete claims."
        ),
    )


def default_referee_profile() -> AgentProfile:
    return AgentProfile(
        id="builtin:referee",
        role="referee",
        name="Built-in Referee",
        critique_level="medium",
        instructions=(
            "Enforce the game contract and local decision authority. "
            "Provide concise rationale aligned with the fixed structured decision."
        ),
    )


def build_prompt_roles(
    *,
    model_client: ModelClient,
    prompt_sections: GameTypePromptSections,
    shared_context: str,
    red_material: bool,
    blue_profile: AgentProfile | None = None,
    red_profile: AgentProfile | None = None,
    referee_profile: AgentProfile | None = None,
):
    _validate_profile_role(blue_profile, "blue", "blue_profile")
    _validate_profile_role(red_profile, "red", "red_profile")
    _validate_profile_role(referee_profile, "referee", "referee_profile")

    blue_template = assemble_prompt(
        PromptSpec(
            sections=[
                PromptSection(
                    name="Role",
                    content=(
                        "Using shared context, provide one concise candidate answer for goal `{goal}`."
                    ),
                ),
                *_profile_section(blue_profile),
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
                *_profile_section(red_profile),
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
                *_profile_section(referee_profile),
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
