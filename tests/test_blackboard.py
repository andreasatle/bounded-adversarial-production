import json
from pathlib import Path

import pytest

from baps.blackboard import Blackboard
from baps.schemas import (
    AcceptedStateRevocation,
    AcceptedStateSupersession,
    ArtifactProposalRecord,
    DiscrepancyResolution,
    DiscrepancySupersession,
    Event,
    IntegrationDecision,
)


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


def test_query_by_run_returns_only_matching_run_events_and_preserves_order(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "board.jsonl")
    board.append(Event(id="e1", type="game_started", payload={"game_id": "g1", "run_id": "run-1"}))
    board.append(Event(id="e2", type="blue_move_recorded", payload={"game_id": "g1", "run_id": "run-1"}))
    board.append(Event(id="e3", type="game_started", payload={"game_id": "g2", "run_id": "run-2"}))
    board.append(Event(id="e4", type="red_finding_recorded", payload={"game_id": "g1", "run_id": "run-1"}))

    run_events = board.query_by_run("run-1")
    assert [event.id for event in run_events] == ["e1", "e2", "e4"]
    assert all(event.payload["run_id"] == "run-1" for event in run_events)


def test_query_by_run_rejects_empty_run_id(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "board.jsonl")
    with pytest.raises(ValueError):
        board.query_by_run("   ")


def test_query_completed_runs_returns_only_game_completed_events(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "board.jsonl")
    board.append(Event(id="e1", type="game_started", payload={"game_id": "g1", "run_id": "run-1"}))
    board.append(Event(id="e2", type="game_completed", payload={"game_id": "g1", "run_id": "run-1"}))
    board.append(Event(id="e3", type="blue_move_recorded", payload={"game_id": "g2", "run_id": "run-2"}))
    board.append(Event(id="e4", type="game_completed", payload={"game_id": "g2", "run_id": "run-2"}))

    completed = board.query_completed_runs()
    assert [event.id for event in completed] == ["e2", "e4"]
    assert all(event.type == "game_completed" for event in completed)


def test_append_integration_decision_records_expected_event(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "board.jsonl")
    decision = IntegrationDecision(
        id="int-001",
        run_id="run-123",
        outcome="accepted",
        target_kind="accomplishment",
        summary="Accept for durable state",
        rationale="Meets integration criteria",
    )

    board.append_integration_decision(decision)

    events = board.read_all()
    assert len(events) == 1
    event = events[0]
    assert event.type == "integration_decision_recorded"
    assert event.payload["integration_decision"] == decision.model_dump(mode="json")


def test_query_can_retrieve_integration_decision_events(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "board.jsonl")
    board.append(Event(id="e1", type="game_started", payload={"run_id": "run-1"}))
    board.append_integration_decision(
        IntegrationDecision(
            id="int-002",
            run_id="run-1",
            outcome="deferred",
            target_kind="discrepancy",
            summary="Needs more evidence",
            rationale="Insufficient confidence for integration",
        )
    )

    integration_events = board.query("integration_decision_recorded")
    assert len(integration_events) == 1
    assert integration_events[0].payload["integration_decision"]["id"] == "int-002"


def test_append_discrepancy_resolution_records_expected_event(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "board.jsonl")
    resolution = DiscrepancyResolution(
        id="res-001",
        discrepancy_id="run-1",
        resolution_summary="Issue resolved by follow-up game",
        source_run_id="run-2",
    )

    board.append_discrepancy_resolution(resolution)

    events = board.read_all()
    assert len(events) == 1
    event = events[0]
    assert event.type == "discrepancy_resolution_recorded"
    assert event.payload["discrepancy_resolution"] == resolution.model_dump(mode="json")


def test_append_discrepancy_supersession_records_expected_event(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "board.jsonl")
    supersession = DiscrepancySupersession(
        id="sup-001",
        superseded_discrepancy_id="run-1",
        superseding_discrepancy_id="run-2",
        rationale="run-2 includes more complete evidence",
        source_run_id="run-2",
    )

    board.append_discrepancy_supersession(supersession)

    events = board.read_all()
    assert len(events) == 1
    event = events[0]
    assert event.type == "discrepancy_supersession_recorded"
    assert event.payload["discrepancy_supersession"] == supersession.model_dump(mode="json")


def test_append_accepted_state_supersession_records_expected_event(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "board.jsonl")
    supersession = AcceptedStateSupersession(
        id="asup-001",
        superseded_item_id="int-001",
        superseding_item_id="int-002",
        target_kind="accomplishment",
        rationale="newer accepted item supersedes older one",
        source_run_id="run-2",
    )

    board.append_accepted_state_supersession(supersession)

    events = board.read_all()
    assert len(events) == 1
    event = events[0]
    assert event.type == "accepted_state_supersession_recorded"
    assert event.payload["accepted_state_supersession"] == supersession.model_dump(mode="json")


def test_append_accepted_state_revocation_records_expected_event(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "board.jsonl")
    revocation = AcceptedStateRevocation(
        id="arev-001",
        revoked_item_id="int-001",
        target_kind="accomplishment",
        rationale="Revoked due to contradictory evidence",
        source_run_id="run-2",
    )

    board.append_accepted_state_revocation(revocation)

    events = board.read_all()
    assert len(events) == 1
    event = events[0]
    assert event.type == "accepted_state_revocation_recorded"
    assert event.payload["accepted_state_revocation"] == revocation.model_dump(mode="json")


def test_append_artifact_proposal_record_records_expected_event(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "board.jsonl")
    record = ArtifactProposalRecord(
        id="apr-001",
        artifact_id="art-1",
        change_id="chg-1",
        source_run_id="run-1",
        integration_decision_id="int-1",
        status="accepted",
        summary="Accepted proposal linked to integration outcome",
    )

    board.append_artifact_proposal_record(record)

    events = board.read_all()
    assert len(events) == 1
    event = events[0]
    assert event.type == "artifact_proposal_recorded"
    assert event.payload["artifact_proposal_record"] == record.model_dump(mode="json")


def test_query_can_retrieve_artifact_proposal_recorded_events(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "board.jsonl")
    board.append(Event(id="e1", type="game_started", payload={"run_id": "run-1"}))
    board.append_artifact_proposal_record(
        ArtifactProposalRecord(
            id="apr-002",
            artifact_id="art-2",
            change_id="chg-2",
            source_run_id="run-2",
            status="proposed",
            summary="Pending proposal",
        )
    )

    events = board.query("artifact_proposal_recorded")
    assert len(events) == 1
    assert events[0].payload["artifact_proposal_record"]["id"] == "apr-002"
