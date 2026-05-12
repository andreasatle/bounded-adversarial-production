import re
from pathlib import Path

from baps.blackboard import Blackboard
from baps.demo import run_demo


def test_run_demo_returns_expected_state_and_writes_five_events(tmp_path: Path) -> None:
    path = tmp_path / "custom" / "events.jsonl"

    state = run_demo(path)

    assert state.game_id == "demo-game-001"
    assert re.fullmatch(r"run-\d{8}-\d{6}-[0-9a-f]{8}", state.run_id)
    assert state.final_decision is not None
    assert state.final_decision.decision == "accept"

    events = Blackboard(path).read_all()
    assert len(events) == 5
    for event in events:
        assert event.payload["run_id"] == state.run_id
        assert event.id.startswith(f"demo-game-001:{state.run_id}:")


def test_run_demo_writes_events_to_provided_path(tmp_path: Path) -> None:
    path = tmp_path / "provided" / "events.jsonl"

    run_demo(path)

    assert path.exists()
