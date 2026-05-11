from pathlib import Path

import pytest

from baps.blackboard import Blackboard
from baps.roles import RoleInvocationError, RoleInvocationGuard
from baps.runtime import RuntimeEngine
from baps.schemas import GameContract, Target


def _contract() -> GameContract:
    return GameContract(
        id="game-1",
        subject="auth",
        goal="find flaws",
        target=Target(kind="repo"),
        active_roles=["blue", "red", "referee"],
    )


def test_run_game_returns_expected_game_state_and_events(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    engine = RuntimeEngine(board)
    contract = _contract()

    def blue_role(_contract: GameContract):
        return {"game_id": "game-1", "role": "blue", "summary": "proposed change"}

    def red_role(_contract: GameContract, _blue_move):
        return {"game_id": "game-1", "severity": "high", "confidence": "high", "claim": "risk found"}

    def referee_role(_contract: GameContract, _blue_move, _red_finding):
        return {"game_id": "game-1", "decision": "integrate", "rationale": "acceptable risk"}

    state = engine.run_game(contract, blue_role, red_role, referee_role)

    assert state.game_id == "game-1"
    assert state.current_round == 1
    assert len(state.rounds) == 1
    assert state.rounds[0].round_number == 1
    assert state.rounds[0].moves[0].role == "blue"
    assert state.final_decision is not None
    assert state.final_decision.decision == "integrate"

    events = board.read_all()
    assert [event.type for event in events] == [
        "game_started",
        "blue_move_recorded",
        "red_finding_recorded",
        "referee_decision_recorded",
        "game_completed",
    ]
    for event in events:
        assert event.payload["game_id"] == "game-1"


def test_invalid_blue_role_output_fails(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    engine = RuntimeEngine(board)
    contract = _contract()

    def blue_role(_contract: GameContract):
        return {"game_id": "game-1", "role": "blue"}

    def red_role(_contract: GameContract, _blue_move):
        return {"game_id": "game-1", "severity": "high", "confidence": "high", "claim": "risk found"}

    def referee_role(_contract: GameContract, _blue_move, _red_finding):
        return {"game_id": "game-1", "decision": "integrate", "rationale": "acceptable risk"}

    with pytest.raises(RoleInvocationError):
        engine.run_game(contract, blue_role, red_role, referee_role)


def test_blue_move_with_wrong_game_id_fails(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    engine = RuntimeEngine(board)
    contract = _contract()

    def blue_role(_contract: GameContract):
        return {"game_id": "wrong", "role": "blue", "summary": "proposed change"}

    def red_role(_contract: GameContract, _blue_move):
        return {"game_id": "game-1", "severity": "high", "confidence": "high", "claim": "risk found"}

    def referee_role(_contract: GameContract, _blue_move, _red_finding):
        return {"game_id": "game-1", "decision": "integrate", "rationale": "acceptable risk"}

    with pytest.raises(RoleInvocationError):
        engine.run_game(contract, blue_role, red_role, referee_role)


def test_blue_move_with_wrong_role_fails(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    engine = RuntimeEngine(board)
    contract = _contract()

    def blue_role(_contract: GameContract):
        return {"game_id": "game-1", "role": "red", "summary": "proposed change"}

    def red_role(_contract: GameContract, _blue_move):
        return {"game_id": "game-1", "severity": "high", "confidence": "high", "claim": "risk found"}

    def referee_role(_contract: GameContract, _blue_move, _red_finding):
        return {"game_id": "game-1", "decision": "integrate", "rationale": "acceptable risk"}

    with pytest.raises(RoleInvocationError):
        engine.run_game(contract, blue_role, red_role, referee_role)


def test_red_finding_with_wrong_game_id_fails(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    engine = RuntimeEngine(board)
    contract = _contract()

    def blue_role(_contract: GameContract):
        return {"game_id": "game-1", "role": "blue", "summary": "proposed change"}

    def red_role(_contract: GameContract, _blue_move):
        return {"game_id": "wrong", "severity": "high", "confidence": "high", "claim": "risk found"}

    def referee_role(_contract: GameContract, _blue_move, _red_finding):
        return {"game_id": "game-1", "decision": "integrate", "rationale": "acceptable risk"}

    with pytest.raises(RoleInvocationError):
        engine.run_game(contract, blue_role, red_role, referee_role)


def test_referee_decision_with_wrong_game_id_fails(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    engine = RuntimeEngine(board)
    contract = _contract()

    def blue_role(_contract: GameContract):
        return {"game_id": "game-1", "role": "blue", "summary": "proposed change"}

    def red_role(_contract: GameContract, _blue_move):
        return {"game_id": "game-1", "severity": "high", "confidence": "high", "claim": "risk found"}

    def referee_role(_contract: GameContract, _blue_move, _red_finding):
        return {"game_id": "wrong", "decision": "integrate", "rationale": "acceptable risk"}

    with pytest.raises(RoleInvocationError):
        engine.run_game(contract, blue_role, red_role, referee_role)


def test_runtime_uses_guard_retry_behavior_and_succeeds(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    engine = RuntimeEngine(board, guard=RoleInvocationGuard(max_attempts=2))
    contract = _contract()
    calls = {"count": 0}

    def blue_role(_contract: GameContract):
        calls["count"] += 1
        if calls["count"] == 1:
            return {"game_id": "game-1", "role": "blue"}
        return {"game_id": "game-1", "role": "blue", "summary": "proposed change"}

    def red_role(_contract: GameContract, _blue_move):
        return {"game_id": "game-1", "severity": "high", "confidence": "high", "claim": "risk found"}

    def referee_role(_contract: GameContract, _blue_move, _red_finding):
        return {"game_id": "game-1", "decision": "integrate", "rationale": "acceptable risk"}

    state = engine.run_game(contract, blue_role, red_role, referee_role)
    assert state.game_id == "game-1"
    assert calls["count"] == 2


def test_runtime_failure_after_retries_raises_role_invocation_error(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    engine = RuntimeEngine(board, guard=RoleInvocationGuard(max_attempts=2))
    contract = _contract()

    def blue_role(_contract: GameContract):
        return {"game_id": "game-1", "role": "blue"}

    def red_role(_contract: GameContract, _blue_move):
        return {"game_id": "game-1", "severity": "high", "confidence": "high", "claim": "risk found"}

    def referee_role(_contract: GameContract, _blue_move, _red_finding):
        return {"game_id": "game-1", "decision": "integrate", "rationale": "acceptable risk"}

    with pytest.raises(RoleInvocationError):
        engine.run_game(contract, blue_role, red_role, referee_role)
