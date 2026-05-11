from baps.example_roles import blue_role, red_role, referee_role
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
