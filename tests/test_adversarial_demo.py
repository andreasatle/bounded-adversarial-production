import re
from pathlib import Path

from baps.adversarial_demo import run_adversarial_demo
from baps.blackboard import Blackboard


def test_adversarial_demo_runs_deterministically(tmp_path: Path) -> None:
    path = tmp_path / "adversarial-events.jsonl"

    first = run_adversarial_demo(path)
    second = run_adversarial_demo(path)

    assert first.game_id == "adversarial-demo-001"
    assert second.game_id == "adversarial-demo-001"
    assert re.fullmatch(r"run-\d{8}-\d{6}-[0-9a-f]{8}", first.run_id)
    assert re.fullmatch(r"run-\d{8}-\d{6}-[0-9a-f]{8}", second.run_id)
    assert first.run_id != second.run_id
    assert first.rounds[0].moves[0].summary == second.rounds[0].moves[0].summary
    assert first.rounds[0].findings[0].claim == second.rounds[0].findings[0].claim
    assert first.final_decision is not None
    assert second.final_decision is not None
    assert first.final_decision.decision == second.final_decision.decision


def test_adversarial_demo_records_expected_events_in_order(tmp_path: Path) -> None:
    path = tmp_path / "adversarial-events.jsonl"
    state = run_adversarial_demo(path)

    events = Blackboard(path).read_all()
    assert [event.type for event in events] == [
        "game_started",
        "blue_move_recorded",
        "red_finding_recorded",
        "referee_decision_recorded",
        "game_completed",
    ]
    assert all(event.payload["game_id"] == state.game_id for event in events)
    assert all(event.payload["run_id"] == state.run_id for event in events)


def test_adversarial_demo_includes_red_finding_and_finding_driven_decision(tmp_path: Path) -> None:
    path = tmp_path / "adversarial-events.jsonl"
    state = run_adversarial_demo(path)

    round_1 = state.rounds[0]
    red_finding = round_1.findings[0]
    decision = state.final_decision

    assert red_finding.claim != ""
    assert len(red_finding.evidence) >= 1
    assert decision is not None
    assert decision.decision == "reject"
    assert red_finding.claim in decision.rationale
