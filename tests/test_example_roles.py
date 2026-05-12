import pytest

from baps.example_roles import blue_role, red_role, referee_role
from baps.models import FakeModelClient
from baps.schemas import Finding, GameContract, Move, Target
from baps.example_roles import make_prompt_blue_role


def _contract() -> GameContract:
    return GameContract(
        id="game-1",
        subject="auth",
        goal="find flaws",
        target=Target(kind="repo"),
        active_roles=["blue", "red", "referee"],
    )


def test_blue_role_returns_valid_move() -> None:
    contract = _contract()
    move = blue_role(contract)

    assert isinstance(move, Move)
    assert move.game_id == contract.id
    assert move.role == "blue"
    assert move.payload["goal"] == contract.goal


def test_red_role_returns_valid_finding_and_references_blue_summary() -> None:
    contract = _contract()
    move = blue_role(contract)
    finding = red_role(contract, move)

    assert isinstance(finding, Finding)
    assert finding.game_id == contract.id
    assert move.summary in finding.claim
    assert len(finding.evidence) >= 1
    assert finding.block_integration is False


def test_referee_role_references_blue_summary_and_red_claim() -> None:
    contract = _contract()
    move = blue_role(contract)
    finding = red_role(contract, move)
    decision = referee_role(contract, move, finding)

    assert decision.game_id == contract.id
    assert move.summary in decision.rationale
    assert finding.claim in decision.rationale


def test_example_roles_are_deterministic_for_same_input() -> None:
    contract = _contract()
    move1 = blue_role(contract)
    move2 = blue_role(contract)
    assert move1.model_dump(mode="json") == move2.model_dump(mode="json")

    finding1 = red_role(contract, move1)
    finding2 = red_role(contract, move1)
    assert finding1.model_dump(mode="json") == finding2.model_dump(mode="json")

    decision1 = referee_role(contract, move1, finding1)
    decision2 = referee_role(contract, move1, finding1)
    assert decision1.model_dump(mode="json") == decision2.model_dump(mode="json")


def test_prompt_driven_blue_role_renders_and_calls_model_client() -> None:
    contract = _contract()
    model = FakeModelClient(responses=["generated summary"])
    role = make_prompt_blue_role(model, template="Game {game_id} goal {goal}")

    move = role(contract)

    assert move.summary == "generated summary"
    assert model.prompts == [f"Game {contract.id} goal {contract.goal}"]


def test_prompt_driven_blue_role_is_deterministic_with_fake_model() -> None:
    contract = _contract()
    model = FakeModelClient(responses=["same summary", "same summary"])
    role = make_prompt_blue_role(model, template="Static prompt for {game_id}")

    move1 = role(contract)
    move2 = role(contract)

    assert move1.model_dump(mode="json") == move2.model_dump(mode="json")


def test_prompt_driven_blue_role_missing_template_variable_fails_clearly() -> None:
    contract = _contract()
    model = FakeModelClient(responses=["unused"])
    role = make_prompt_blue_role(model, template="Missing {unknown_key}")

    with pytest.raises(KeyError):
        role(contract)


def test_prompt_driven_blue_role_rejects_whitespace_rendered_prompt() -> None:
    contract = _contract()
    model = FakeModelClient(responses=["unused"])
    role = make_prompt_blue_role(model, template="{blank}", extra_context={"blank": "   "})

    with pytest.raises(ValueError):
        role(contract)
