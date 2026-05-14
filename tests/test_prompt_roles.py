from baps.game_types import make_documentation_refinement_game_definition
from baps.models import FakeModelClient
from baps.prompt_roles import build_prompt_roles
from baps.schemas import GameContract, Target


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
