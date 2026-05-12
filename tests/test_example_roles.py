import pytest

from baps.example_roles import (
    blue_role,
    make_prompt_blue_role,
    make_prompt_red_role,
    make_prompt_referee_role,
    red_role,
    referee_role,
)
from baps.models import FakeModelClient
from baps.schemas import Finding, GameContract, Move, Target


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


def test_prompt_driven_red_role_renders_and_calls_model_client() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={"k": "v"})
    model = FakeModelClient(responses=["generated red claim"])
    role = make_prompt_red_role(model, template="Red sees {blue_summary} for {goal}")

    finding = role(contract, blue)

    assert finding.claim == "generated red claim"
    assert model.prompts == [f"Red sees {blue.summary} for {contract.goal}"]


def test_prompt_driven_red_generated_text_becomes_claim() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    model = FakeModelClient(responses=["specific critique text"])
    role = make_prompt_red_role(model)

    finding = role(contract, blue)

    assert finding.claim == "specific critique text"
    assert finding.severity == "medium"
    assert finding.confidence == "medium"
    assert finding.block_integration is False
    assert blue.summary in finding.evidence[0]


def test_prompt_driven_red_missing_template_variable_raises_key_error() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    model = FakeModelClient(responses=["unused"])
    role = make_prompt_red_role(model, template="Missing {unknown_key}")

    with pytest.raises(KeyError):
        role(contract, blue)


def test_prompt_driven_red_whitespace_rendered_prompt_raises_value_error() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    model = FakeModelClient(responses=["unused"])
    role = make_prompt_red_role(model, template="{blank}", extra_context={"blank": "   "})

    with pytest.raises(ValueError):
        role(contract, blue)


def test_prompt_driven_referee_renders_and_calls_model_client() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    red = Finding(
        game_id=contract.id,
        severity="high",
        confidence="high",
        claim="critical issue",
        evidence=["e1"],
        block_integration=True,
    )
    model = FakeModelClient(responses=["generated rationale"])
    role = make_prompt_referee_role(model, template="Ref checks {red_claim} for {blue_summary}")

    decision = role(contract, blue, red)

    assert decision.rationale == "generated rationale"
    assert model.prompts == [f"Ref checks {red.claim} for {blue.summary}"]


def test_prompt_driven_referee_generated_text_becomes_rationale() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    red = Finding(
        game_id=contract.id,
        severity="low",
        confidence="low",
        claim="minor issue",
        evidence=["e1"],
        block_integration=False,
    )
    model = FakeModelClient(responses=["rationale text"])
    role = make_prompt_referee_role(model)

    decision = role(contract, blue, red)
    assert decision.rationale == "rationale text"


def test_prompt_driven_referee_rejects_when_block_integration_true() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    red = Finding(
        game_id=contract.id,
        severity="high",
        confidence="high",
        claim="major issue",
        evidence=["e1"],
        block_integration=True,
    )
    model = FakeModelClient(responses=["rationale"])
    role = make_prompt_referee_role(model)

    decision = role(contract, blue, red)
    assert decision.decision == "reject"
    assert "decision is already fixed to `reject`" in model.prompts[0]
    assert "reject = blocking issue, revise = useful non-blocking criticism, accept = no material issue" in model.prompts[0]
    assert "Do not choose a different decision and do not contradict it." in model.prompts[0]


def test_prompt_driven_referee_revises_when_block_integration_false() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    red = Finding(
        game_id=contract.id,
        severity="low",
        confidence="high",
        claim="minor issue",
        evidence=["e1"],
        block_integration=False,
    )
    model = FakeModelClient(responses=["rationale"])
    role = make_prompt_referee_role(model)

    decision = role(contract, blue, red)
    assert decision.decision == "revise"
    assert "decision is already fixed to `revise`" in model.prompts[0]
    assert "reject = blocking issue, revise = useful non-blocking criticism, accept = no material issue" in model.prompts[0]
    assert "Do not choose a different decision and do not contradict it." in model.prompts[0]


def test_prompt_driven_referee_missing_template_variable_raises_key_error() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    red = Finding(
        game_id=contract.id,
        severity="low",
        confidence="low",
        claim="minor issue",
        evidence=["e1"],
        block_integration=False,
    )
    model = FakeModelClient(responses=["unused"])
    role = make_prompt_referee_role(model, template="Missing {unknown_key}")

    with pytest.raises(KeyError):
        role(contract, blue, red)


def test_prompt_driven_referee_whitespace_rendered_prompt_raises_value_error() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    red = Finding(
        game_id=contract.id,
        severity="low",
        confidence="low",
        claim="minor issue",
        evidence=["e1"],
        block_integration=False,
    )
    model = FakeModelClient(responses=["unused"])
    role = make_prompt_referee_role(model, template="{blank}", extra_context={"blank": "   "})

    with pytest.raises(ValueError):
        role(contract, blue, red)
