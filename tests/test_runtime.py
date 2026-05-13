import re
from pathlib import Path

import pytest

from baps.blackboard import Blackboard
from baps.roles import RoleInvocationError, RoleInvocationGuard
from baps.runtime import RuntimeEngine, generate_run_id
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
    assert re.fullmatch(r"run-\d{8}-\d{6}-[0-9a-f]{8}", state.run_id)
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
        assert event.payload["run_id"] == state.run_id
        assert event.id.startswith(f"game-1:{state.run_id}:")


def test_repeated_runs_produce_different_run_ids(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    engine = RuntimeEngine(board)
    contract = _contract()

    def blue_role(_contract: GameContract):
        return {"game_id": "game-1", "role": "blue", "summary": "proposed change"}

    def red_role(_contract: GameContract, _blue_move):
        return {"game_id": "game-1", "severity": "high", "confidence": "high", "claim": "risk found"}

    def referee_role(_contract: GameContract, _blue_move, _red_finding):
        return {"game_id": "game-1", "decision": "integrate", "rationale": "acceptable risk"}

    first = engine.run_game(contract, blue_role, red_role, referee_role)
    second = engine.run_game(contract, blue_role, red_role, referee_role)
    assert re.fullmatch(r"run-\d{8}-\d{6}-[0-9a-f]{8}", first.run_id)
    assert re.fullmatch(r"run-\d{8}-\d{6}-[0-9a-f]{8}", second.run_id)
    assert first.run_id != second.run_id


def test_two_runtime_instances_produce_different_run_ids(tmp_path: Path) -> None:
    board_one = Blackboard(tmp_path / "events-one.jsonl")
    board_two = Blackboard(tmp_path / "events-two.jsonl")
    engine_one = RuntimeEngine(board_one)
    engine_two = RuntimeEngine(board_two)
    contract = _contract()

    def blue_role(_contract: GameContract):
        return {"game_id": "game-1", "role": "blue", "summary": "proposed change"}

    def red_role(_contract: GameContract, _blue_move):
        return {"game_id": "game-1", "severity": "high", "confidence": "high", "claim": "risk found"}

    def referee_role(_contract: GameContract, _blue_move, _red_finding):
        return {"game_id": "game-1", "decision": "integrate", "rationale": "acceptable risk"}

    first = engine_one.run_game(contract, blue_role, red_role, referee_role)
    second = engine_two.run_game(contract, blue_role, red_role, referee_role)
    assert first.run_id != second.run_id


def test_generate_run_id_format() -> None:
    run_id = generate_run_id()
    assert re.fullmatch(r"run-\d{8}-\d{6}-[0-9a-f]{8}", run_id)


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


def test_accept_stops_after_one_round(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    engine = RuntimeEngine(board)
    contract = _contract()

    def blue_role(_contract: GameContract):
        return {"game_id": "game-1", "role": "blue", "summary": "s1"}

    def red_role(_contract: GameContract, _blue_move):
        return {"game_id": "game-1", "severity": "low", "confidence": "high", "claim": "minor"}

    def referee_role(_contract: GameContract, _blue_move, _red_finding):
        return {"game_id": "game-1", "decision": "accept", "rationale": "ok"}

    state = engine.run_game(contract, blue_role, red_role, referee_role)
    assert len(state.rounds) == 1
    assert state.final_decision is not None
    assert state.final_decision.decision == "accept"


def test_reject_stops_after_one_round(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    engine = RuntimeEngine(board)
    contract = _contract()

    def blue_role(_contract: GameContract):
        return {"game_id": "game-1", "role": "blue", "summary": "s1"}

    def red_role(_contract: GameContract, _blue_move):
        return {"game_id": "game-1", "severity": "high", "confidence": "high", "claim": "major"}

    def referee_role(_contract: GameContract, _blue_move, _red_finding):
        return {"game_id": "game-1", "decision": "reject", "rationale": "block"}

    state = engine.run_game(contract, blue_role, red_role, referee_role)
    assert len(state.rounds) == 1
    assert state.final_decision is not None
    assert state.final_decision.decision == "reject"


def test_revise_continues_when_max_rounds_allows(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    engine = RuntimeEngine(board)
    contract = GameContract(
        id="game-1",
        subject="auth",
        goal="find flaws",
        target=Target(kind="repo"),
        active_roles=["blue", "red", "referee"],
        max_rounds=3,
    )
    calls = {"blue": 0, "context_seen": False}

    def blue_role(_contract: GameContract, revision_context=None):
        calls["blue"] += 1
        if revision_context is not None:
            calls["context_seen"] = True
        return {"game_id": "game-1", "role": "blue", "summary": f"s{calls['blue']}"}

    def red_role(_contract: GameContract, blue_move):
        return {"game_id": "game-1", "severity": "medium", "confidence": "high", "claim": f"c-{blue_move.summary}"}

    def referee_role(_contract: GameContract, _blue_move, _red_finding):
        decision = "revise" if calls["blue"] == 1 else "accept"
        return {"game_id": "game-1", "decision": decision, "rationale": f"r{calls['blue']}"}

    state = engine.run_game(contract, blue_role, red_role, referee_role)
    assert len(state.rounds) == 2
    assert calls["context_seen"] is True
    assert state.final_decision is not None
    assert state.final_decision.decision == "accept"
    assert state.current_round == 2


def test_revise_stops_at_max_rounds(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    engine = RuntimeEngine(board)
    contract = GameContract(
        id="game-1",
        subject="auth",
        goal="find flaws",
        target=Target(kind="repo"),
        active_roles=["blue", "red", "referee"],
        max_rounds=2,
    )
    calls = {"blue": 0}

    def blue_role(_contract: GameContract, revision_context=None):
        calls["blue"] += 1
        return {"game_id": "game-1", "role": "blue", "summary": f"s{calls['blue']}"}

    def red_role(_contract: GameContract, blue_move):
        return {"game_id": "game-1", "severity": "medium", "confidence": "high", "claim": f"c-{blue_move.summary}"}

    def referee_role(_contract: GameContract, _blue_move, _red_finding):
        return {"game_id": "game-1", "decision": "revise", "rationale": "keep revising"}

    state = engine.run_game(contract, blue_role, red_role, referee_role)
    assert len(state.rounds) == 2
    assert state.current_round == 2
    assert state.final_decision is not None
    assert state.final_decision.decision == "revise"


def test_event_ids_do_not_collide_across_rounds(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    engine = RuntimeEngine(board)
    contract = GameContract(
        id="game-1",
        subject="auth",
        goal="find flaws",
        target=Target(kind="repo"),
        active_roles=["blue", "red", "referee"],
        max_rounds=2,
    )
    calls = {"blue": 0}

    def blue_role(_contract: GameContract, revision_context=None):
        calls["blue"] += 1
        return {"game_id": "game-1", "role": "blue", "summary": f"s{calls['blue']}"}

    def red_role(_contract: GameContract, _blue_move):
        return {"game_id": "game-1", "severity": "medium", "confidence": "high", "claim": "c"}

    def referee_role(_contract: GameContract, _blue_move, _red_finding):
        return {"game_id": "game-1", "decision": "revise", "rationale": "r"}

    engine.run_game(contract, blue_role, red_role, referee_role)
    events = board.read_all()
    ids = [event.id for event in events]
    assert len(ids) == len(set(ids))
