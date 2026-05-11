import json
from pathlib import Path

import pytest

from baps.blackboard import Blackboard
from baps.schemas import Event


def test_append_one_event_creates_file(tmp_path: Path) -> None:
    path = tmp_path / "events" / "board.jsonl"
    board = Blackboard(path)

    board.append(Event(id="e1", type="move", payload={"k": "v"}))

    assert path.exists()
    events = board.read_all()
    assert len(events) == 1
    assert events[0].id == "e1"


def test_append_multiple_events_preserves_order(tmp_path: Path) -> None:
    path = tmp_path / "board.jsonl"
    board = Blackboard(path)
    board.append(Event(id="e1", type="move"))
    board.append(Event(id="e2", type="finding"))
    board.append(Event(id="e3", type="move"))

    events = board.read_all()
    assert [event.id for event in events] == ["e1", "e2", "e3"]


def test_read_all_returns_empty_for_missing_file(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "missing.jsonl")
    assert board.read_all() == []


def test_query_returns_only_matching_type(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "board.jsonl")
    board.append(Event(id="e1", type="move"))
    board.append(Event(id="e2", type="finding"))
    board.append(Event(id="e3", type="move"))

    move_events = board.query("move")
    assert [event.id for event in move_events] == ["e1", "e3"]


def test_query_rejects_empty_event_type(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "board.jsonl")
    with pytest.raises(ValueError):
        board.query("   ")


def test_invalid_jsonl_content_raises_on_read_all(tmp_path: Path) -> None:
    path = tmp_path / "board.jsonl"
    path.write_text("{not valid json}\n", encoding="utf-8")
    board = Blackboard(path)

    with pytest.raises(Exception):
        board.read_all()


def test_event_mutable_payload_default_not_shared() -> None:
    event_a = Event(id="e1", type="move")
    event_b = Event(id="e2", type="move")

    event_a.payload["x"] = 1
    assert event_b.payload == {}


def test_append_does_not_overwrite_previous_events(tmp_path: Path) -> None:
    path = tmp_path / "board.jsonl"
    board = Blackboard(path)

    board.append(Event(id="e1", type="move"))
    first_contents = path.read_text(encoding="utf-8")
    board.append(Event(id="e2", type="finding"))
    second_contents = path.read_text(encoding="utf-8")

    assert first_contents in second_contents
    lines = second_contents.strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["id"] == "e1"
    assert json.loads(lines[1])["id"] == "e2"
