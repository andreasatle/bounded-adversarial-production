import pytest

from baps.game_types import make_documentation_refinement_game_definition
from baps.models import FakeModelClient
from baps.prompt_roles import (
    build_prompt_roles,
    default_blue_profile,
    default_red_profile,
    default_referee_profile,
)
from baps.schemas import AgentProfile, GameContract, Target


def test_build_prompt_roles_constructs_blue_red_referee_roles() -> None:
    model = FakeModelClient(
        responses=[
            "candidate answer",
            "MATERIAL: no\nCLAIM: looks good",
            "rationale",
        ]
    )
    contract = GameContract(
        id="game-1",
        subject="README",
        goal="Improve docs",
        target=Target(kind="documentation", ref="README.md"),
        active_roles=["blue", "red", "referee"],
        max_rounds=1,
    )
    sections = make_documentation_refinement_game_definition().prompt_sections
    blue_role, red_role, referee_role = build_prompt_roles(
        model_client=model,
        prompt_sections=sections,
        shared_context="shared-context",
        red_material=True,
    )

    blue_move = blue_role(contract)
    red_finding = red_role(contract, blue_move)
    decision = referee_role(contract, blue_move, red_finding)

    assert blue_move.summary == "candidate answer"
    assert red_finding.claim == "looks good"
    assert decision.rationale == "rationale"
    assert len(model.prompts) == 3
    assert all("shared-context" in prompt for prompt in model.prompts)


def test_build_prompt_roles_includes_blue_profile_only_in_blue_prompt() -> None:
    model = FakeModelClient(
        responses=[
            "candidate answer",
            "MATERIAL: no\nCLAIM: looks good",
            "rationale",
        ]
    )
    contract = GameContract(
        id="game-1",
        subject="README",
        goal="Improve docs",
        target=Target(kind="documentation", ref="README.md"),
        active_roles=["blue", "red", "referee"],
        max_rounds=1,
    )
    sections = make_documentation_refinement_game_definition().prompt_sections
    blue_profile = AgentProfile(
        id="blue-1",
        role="blue",
        name="Blue Planner",
        critique_level="low",
        instructions="Prefer conservative, scoped changes.",
    )
    blue_role, red_role, referee_role = build_prompt_roles(
        model_client=model,
        prompt_sections=sections,
        shared_context="shared-context",
        red_material=True,
        blue_profile=blue_profile,
    )

    blue_move = blue_role(contract)
    red_finding = red_role(contract, blue_move)
    referee_role(contract, blue_move, red_finding)

    assert "Blue Planner" in model.prompts[0]
    assert "Prefer conservative, scoped changes." in model.prompts[0]
    assert "Blue Planner" not in model.prompts[1]
    assert "Blue Planner" not in model.prompts[2]


def test_build_prompt_roles_includes_red_profile_only_in_red_prompt() -> None:
    model = FakeModelClient(
        responses=[
            "candidate answer",
            "MATERIAL: no\nCLAIM: looks good",
            "rationale",
        ]
    )
    contract = GameContract(
        id="game-1",
        subject="README",
        goal="Improve docs",
        target=Target(kind="documentation", ref="README.md"),
        active_roles=["blue", "red", "referee"],
        max_rounds=1,
    )
    sections = make_documentation_refinement_game_definition().prompt_sections
    red_profile = AgentProfile(
        id="red-1",
        role="red",
        name="Red Critic",
        critique_level="high",
        instructions="Prioritize material defects and concrete evidence.",
    )
    blue_role, red_role, referee_role = build_prompt_roles(
        model_client=model,
        prompt_sections=sections,
        shared_context="shared-context",
        red_material=True,
        red_profile=red_profile,
    )

    blue_move = blue_role(contract)
    red_finding = red_role(contract, blue_move)
    referee_role(contract, blue_move, red_finding)

    assert "Red Critic" not in model.prompts[0]
    assert "Red Critic" in model.prompts[1]
    assert "Prioritize material defects and concrete evidence." in model.prompts[1]
    assert "Red Critic" not in model.prompts[2]


def test_build_prompt_roles_includes_referee_profile_only_in_referee_prompt() -> None:
    model = FakeModelClient(
        responses=[
            "candidate answer",
            "MATERIAL: no\nCLAIM: looks good",
            "rationale",
        ]
    )
    contract = GameContract(
        id="game-1",
        subject="README",
        goal="Improve docs",
        target=Target(kind="documentation", ref="README.md"),
        active_roles=["blue", "red", "referee"],
        max_rounds=1,
    )
    sections = make_documentation_refinement_game_definition().prompt_sections
    referee_profile = AgentProfile(
        id="ref-1",
        role="referee",
        name="Referee Arbiter",
        critique_level="medium",
        instructions="Keep rationale concise and policy-consistent.",
    )
    blue_role, red_role, referee_role = build_prompt_roles(
        model_client=model,
        prompt_sections=sections,
        shared_context="shared-context",
        red_material=True,
        referee_profile=referee_profile,
    )

    blue_move = blue_role(contract)
    red_finding = red_role(contract, blue_move)
    referee_role(contract, blue_move, red_finding)

    assert "Referee Arbiter" not in model.prompts[0]
    assert "Referee Arbiter" not in model.prompts[1]
    assert "Referee Arbiter" in model.prompts[2]
    assert "Keep rationale concise and policy-consistent." in model.prompts[2]


def test_build_prompt_roles_rejects_mismatched_profile_roles() -> None:
    model = FakeModelClient(
        responses=[
            "candidate answer",
            "MATERIAL: no\nCLAIM: ok",
            "rationale",
        ]
    )
    sections = make_documentation_refinement_game_definition().prompt_sections

    with pytest.raises(ValueError, match="blue_profile.role must be 'blue'"):
        build_prompt_roles(
            model_client=model,
            prompt_sections=sections,
            shared_context="shared-context",
            red_material=True,
            blue_profile=AgentProfile(
                id="bad-blue",
                role="red",
                name="Bad Blue",
                critique_level="low",
                instructions="bad",
            ),
        )


def test_default_profiles_have_expected_roles_levels_and_ids() -> None:
    blue = default_blue_profile()
    red = default_red_profile()
    referee = default_referee_profile()

    assert blue.id == "builtin:blue"
    assert blue.role == "blue"
    assert blue.critique_level == "low"

    assert red.id == "builtin:red"
    assert red.role == "red"
    assert red.critique_level == "high"

    assert referee.id == "builtin:referee"
    assert referee.role == "referee"
    assert referee.critique_level == "medium"


def test_default_profiles_can_be_passed_to_build_prompt_roles() -> None:
    model = FakeModelClient(
        responses=[
            "candidate answer",
            "MATERIAL: no\nCLAIM: looks good",
            "rationale",
        ]
    )
    contract = GameContract(
        id="game-1",
        subject="README",
        goal="Improve docs",
        target=Target(kind="documentation", ref="README.md"),
        active_roles=["blue", "red", "referee"],
        max_rounds=1,
    )
    sections = make_documentation_refinement_game_definition().prompt_sections

    blue_role, red_role, referee_role = build_prompt_roles(
        model_client=model,
        prompt_sections=sections,
        shared_context="shared-context",
        red_material=True,
        blue_profile=default_blue_profile(),
        red_profile=default_red_profile(),
        referee_profile=default_referee_profile(),
    )

    blue_move = blue_role(contract)
    red_finding = red_role(contract, blue_move)
    decision = referee_role(contract, blue_move, red_finding)

    assert blue_move.summary == "candidate answer"
    assert red_finding.claim == "looks good"
    assert decision.rationale == "rationale"
    assert "Built-in Blue" in model.prompts[0]
    assert "Built-in Red" in model.prompts[1]
    assert "Built-in Referee" in model.prompts[2]

    with pytest.raises(ValueError, match="red_profile.role must be 'red'"):
        build_prompt_roles(
            model_client=model,
            prompt_sections=sections,
            shared_context="shared-context",
            red_material=True,
            red_profile=AgentProfile(
                id="bad-red",
                role="blue",
                name="Bad Red",
                critique_level="low",
                instructions="bad",
            ),
        )

    with pytest.raises(ValueError, match="referee_profile.role must be 'referee'"):
        build_prompt_roles(
            model_client=model,
            prompt_sections=sections,
            shared_context="shared-context",
            red_material=True,
            referee_profile=AgentProfile(
                id="bad-ref",
                role="red",
                name="Bad Ref",
                critique_level="low",
                instructions="bad",
            ),
        )
