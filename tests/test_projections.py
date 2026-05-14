from pathlib import Path

import pytest

from baps.blackboard import Blackboard
from baps.projections import (
    accepted_state_supersession_chain,
    accepted_artifact_proposals,
    artifact_proposal_records,
    build_projected_state,
    build_projected_state_from_blackboard,
    current_open_discrepancies,
    current_open_discrepancies_by_severity,
    deferred_integration_decisions,
    discrepancies_by_severity,
    discrepancies_for_artifact,
    discrepancy_supersession_chain,
    integration_review_queue,
    proposed_artifact_proposals,
    rejected_artifact_proposals,
    current_accepted_accomplishments,
    current_accepted_architecture,
    current_accepted_capabilities,
)
from baps.schemas import (
    ArtifactProposalRecord,
    Event,
    IntegrationDecision,
    ProjectedState,
    UnresolvedDiscrepancy,
)


def test_build_projected_state_empty_events_returns_empty_state() -> None:
    projected = build_projected_state([])
    assert projected.accepted_accomplishments == []
    assert projected.accepted_architecture == []
    assert projected.accepted_capabilities == []
    assert projected.unresolved_discrepancies == []
    assert projected.active_games == []
    assert projected.metadata["event_count"] == 0
    assert projected.metadata["active_game_count"] == 0
    assert projected.metadata["accepted_accomplishment_count"] == 0
    assert projected.metadata["accepted_architecture_count"] == 0
    assert projected.metadata["accepted_capability_count"] == 0
    assert projected.metadata["unresolved_discrepancy_count"] == 0


def test_build_projected_state_started_game_becomes_active() -> None:
    projected = build_projected_state(
        [
            Event(
                id="g1:run-1:r0001:game_started",
                type="game_started",
                payload={"game_id": "g1", "run_id": "run-1"},
            )
        ]
    )
    assert len(projected.active_games) == 1
    active = projected.active_games[0]
    assert active.id == "run-1"
    assert active.title == "g1"
    assert active.source_run_id == "run-1"


def test_build_projected_state_completed_game_is_removed_from_active() -> None:
    projected = build_projected_state(
        [
            Event(
                id="g1:run-1:r0001:game_started",
                type="game_started",
                payload={"game_id": "g1", "run_id": "run-1"},
            ),
            Event(
                id="g1:run-1:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "accepted_locally",
                    "integration_recommendation": "integration_recommended",
                    "state": {
                        "final_decision": {"rationale": "accepted rationale"},
                    },
                },
            ),
        ]
    )
    assert projected.active_games == []


def test_build_projected_state_unrelated_events_are_ignored() -> None:
    projected = build_projected_state(
        [
            Event(id="x1", type="blue_move_recorded", payload={"game_id": "g1", "run_id": "run-1"}),
            Event(id="x2", type="red_finding_recorded", payload={"game_id": "g1", "run_id": "run-1"}),
            Event(id="x3", type="custom_event", payload={"game_id": "g1", "run_id": "run-1"}),
        ]
    )
    assert projected.active_games == []


def test_build_projected_state_duplicate_started_event_does_not_duplicate_active_game() -> None:
    projected = build_projected_state(
        [
            Event(
                id="g1:run-1:r0001:game_started",
                type="game_started",
                payload={"game_id": "g1", "run_id": "run-1"},
            ),
            Event(
                id="g1:run-1:r0001:game_started-duplicate",
                type="game_started",
                payload={"game_id": "g1", "run_id": "run-1"},
            ),
        ]
    )
    assert len(projected.active_games) == 1
    assert projected.active_games[0].id == "run-1"


def test_build_projected_state_active_game_order_is_preserved() -> None:
    projected = build_projected_state(
        [
            Event(
                id="g1:run-1:r0001:game_started",
                type="game_started",
                payload={"game_id": "g1", "run_id": "run-1"},
            ),
            Event(
                id="g2:run-2:r0001:game_started",
                type="game_started",
                payload={"game_id": "g2", "run_id": "run-2"},
            ),
            Event(
                id="g3:run-3:r0001:game_started",
                type="game_started",
                payload={"game_id": "g3", "run_id": "run-3"},
            ),
            Event(
                id="g2:run-2:game_completed",
                type="game_completed",
                payload={"game_id": "g2", "run_id": "run-2"},
            ),
        ]
    )
    assert [active.id for active in projected.active_games] == ["run-1", "run-3"]


def test_build_projected_state_successful_completion_alone_does_not_produce_accomplishment() -> None:
    projected = build_projected_state(
        [
            Event(
                id="g1:run-1:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "accepted_locally",
                    "integration_recommendation": "integration_recommended",
                    "state": {
                        "final_decision": {
                            "rationale": "accepted outcome rationale",
                        }
                    },
                },
            )
        ]
    )
    assert projected.accepted_accomplishments == []


def test_build_projected_state_accepted_integration_decision_produces_accomplishment() -> None:
    projected = build_projected_state(
        [
            Event(
                id="integration:int-001",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "int-001",
                        "run_id": "run-1",
                        "outcome": "accepted",
                        "target_kind": "accomplishment",
                        "summary": "Accepted accomplishment summary",
                        "rationale": "Explicit integration authority accepted this.",
                    }
                },
            ),
        ]
    )
    assert len(projected.accepted_accomplishments) == 1
    accomplishment = projected.accepted_accomplishments[0]
    assert accomplishment.id == "int-001"
    assert accomplishment.source_run_id == "run-1"
    assert accomplishment.summary == "Accepted accomplishment summary"


def test_build_projected_state_non_accepted_integration_decisions_do_not_produce_accomplishment() -> None:
    projected = build_projected_state(
        [
            Event(
                id="integration:int-002",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "int-002",
                        "run_id": "run-1",
                        "outcome": "rejected",
                        "target_kind": "accomplishment",
                        "summary": "Rejected accomplishment summary",
                        "rationale": "Rejected integration outcome.",
                    }
                },
            )
        ]
    )
    assert projected.accepted_accomplishments == []


def test_build_projected_state_non_accomplishment_target_integration_decisions_do_not_produce_accomplishment() -> None:
    projected = build_projected_state(
        [
            Event(
                id="integration:int-003",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "int-003",
                        "run_id": "run-1",
                        "outcome": "accepted",
                        "target_kind": "capability",
                        "summary": "Accepted capability summary",
                        "rationale": "Accepted but not accomplishment.",
                    }
                },
            ),
        ]
    )
    assert projected.accepted_accomplishments == []


def test_build_projected_state_duplicate_accepted_integration_decisions_do_not_duplicate_accomplishment() -> None:
    projected = build_projected_state(
        [
            Event(
                id="integration:int-004-a",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "int-004",
                        "run_id": "run-1",
                        "outcome": "accepted",
                        "target_kind": "accomplishment",
                        "summary": "Accepted accomplishment summary",
                        "rationale": "First event",
                    }
                },
            ),
            Event(
                id="integration:int-004-b",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "int-004",
                        "run_id": "run-1",
                        "outcome": "accepted",
                        "target_kind": "accomplishment",
                        "summary": "Accepted accomplishment summary duplicate",
                        "rationale": "Second event",
                    }
                },
            ),
        ]
    )
    assert len(projected.accepted_accomplishments) == 1
    assert projected.accepted_accomplishments[0].id == "int-004"


def test_build_projected_state_accepted_integration_decision_produces_architecture_item() -> None:
    projected = build_projected_state(
        [
            Event(
                id="integration:int-arch-001",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "int-arch-001",
                        "run_id": "run-arch-1",
                        "outcome": "accepted",
                        "target_kind": "architecture",
                        "summary": "Adopt bounded projection pipeline",
                        "rationale": "Architecture accepted by integrator",
                    }
                },
            )
        ]
    )
    assert len(projected.accepted_architecture) == 1
    item = projected.accepted_architecture[0]
    assert item.id == "int-arch-001"
    assert item.title == "Adopt bounded projection pipeline"
    assert item.source_event_id == "run-arch-1"
    assert item.metadata["integration_decision_id"] == "int-arch-001"
    assert item.metadata["integration_target_kind"] == "architecture"


def test_build_projected_state_accepted_integration_decision_produces_capability() -> None:
    projected = build_projected_state(
        [
            Event(
                id="integration:int-cap-001",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "int-cap-001",
                        "run_id": "run-cap-1",
                        "outcome": "accepted",
                        "target_kind": "capability",
                        "summary": "Event-level integration decision recording",
                        "rationale": "Capability accepted by integrator",
                    }
                },
            )
        ]
    )
    assert len(projected.accepted_capabilities) == 1
    capability = projected.accepted_capabilities[0]
    assert capability.id == "int-cap-001"
    assert capability.name == "Event-level integration decision recording"
    assert capability.source_run_id == "run-cap-1"
    assert capability.metadata["integration_decision_id"] == "int-cap-001"
    assert capability.metadata["integration_target_kind"] == "capability"


def test_build_projected_state_non_accepted_architecture_and_capability_decisions_are_ignored() -> None:
    projected = build_projected_state(
        [
            Event(
                id="integration:int-arch-002",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "int-arch-002",
                        "run_id": "run-arch-2",
                        "outcome": "rejected",
                        "target_kind": "architecture",
                        "summary": "Rejected architecture item",
                        "rationale": "Not accepted",
                    }
                },
            ),
            Event(
                id="integration:int-cap-002",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "int-cap-002",
                        "run_id": "run-cap-2",
                        "outcome": "deferred",
                        "target_kind": "capability",
                        "summary": "Deferred capability",
                        "rationale": "Needs more evidence",
                    }
                },
            ),
        ]
    )
    assert projected.accepted_architecture == []
    assert projected.accepted_capabilities == []


def test_build_projected_state_duplicate_accepted_architecture_decision_id_does_not_duplicate() -> None:
    projected = build_projected_state(
        [
            Event(
                id="integration:int-arch-003-a",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "int-arch-003",
                        "run_id": "run-arch-3",
                        "outcome": "accepted",
                        "target_kind": "architecture",
                        "summary": "Architecture summary v1",
                        "rationale": "first",
                    }
                },
            ),
            Event(
                id="integration:int-arch-003-b",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "int-arch-003",
                        "run_id": "run-arch-3",
                        "outcome": "accepted",
                        "target_kind": "architecture",
                        "summary": "Architecture summary v2",
                        "rationale": "second",
                    }
                },
            ),
        ]
    )
    assert len(projected.accepted_architecture) == 1
    assert projected.accepted_architecture[0].id == "int-arch-003"


def test_build_projected_state_rejected_completion_produces_unresolved_discrepancy() -> None:
    projected = build_projected_state(
        [
            Event(
                id="g1:run-1:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "blocking issue found"}},
                },
            )
        ]
    )
    assert len(projected.unresolved_discrepancies) == 1
    discrepancy = projected.unresolved_discrepancies[0]
    assert discrepancy.id == "run-1"
    assert discrepancy.summary == "blocking issue found"
    assert discrepancy.kind == "unresolved_finding"
    assert discrepancy.severity == "medium"
    assert discrepancy.status == "open"
    assert discrepancy.metadata["terminal_outcome"] == "rejected_locally"
    assert discrepancy.metadata["integration_recommendation"] == "do_not_integrate"


def test_build_projected_state_budget_exhausted_completion_produces_unresolved_discrepancy() -> None:
    projected = build_projected_state(
        [
            Event(
                id="g1:run-1:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "revision_budget_exhausted",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "needs more revision"}},
                },
            )
        ]
    )
    assert len(projected.unresolved_discrepancies) == 1
    discrepancy = projected.unresolved_discrepancies[0]
    assert discrepancy.id == "run-1"
    assert discrepancy.summary == "needs more revision"
    assert discrepancy.kind == "unresolved_finding"
    assert discrepancy.severity == "medium"
    assert discrepancy.status == "open"
    assert discrepancy.metadata["terminal_outcome"] == "revision_budget_exhausted"
    assert discrepancy.metadata["integration_recommendation"] == "do_not_integrate"


def test_build_projected_state_accepted_completion_does_not_produce_discrepancy() -> None:
    projected = build_projected_state(
        [
            Event(
                id="g1:run-1:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "accepted_locally",
                    "integration_recommendation": "integration_recommended",
                    "state": {"final_decision": {"rationale": "accepted rationale"}},
                },
            )
        ]
    )
    assert projected.unresolved_discrepancies == []


def test_build_projected_state_duplicate_unsuccessful_completions_do_not_duplicate_discrepancy() -> None:
    projected = build_projected_state(
        [
            Event(
                id="g1:run-1:game_completed-a",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "rationale-a"}},
                },
            ),
            Event(
                id="g1:run-1:game_completed-b",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "rationale-b"}},
                },
            ),
        ]
    )
    assert len(projected.unresolved_discrepancies) == 1
    assert projected.unresolved_discrepancies[0].id == "run-1"


def test_build_projected_state_resolution_marks_known_discrepancy_resolved() -> None:
    projected = build_projected_state(
        [
            Event(
                id="g1:run-1:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "blocking issue found"}},
                },
            ),
            Event(
                id="res:001",
                type="discrepancy_resolution_recorded",
                payload={
                    "discrepancy_resolution": {
                        "id": "res-001",
                        "discrepancy_id": "run-1",
                        "resolution_summary": "Addressed by follow-up run",
                        "source_run_id": "run-2",
                    }
                },
            ),
        ]
    )
    assert len(projected.unresolved_discrepancies) == 1
    assert projected.unresolved_discrepancies[0].id == "run-1"
    assert projected.unresolved_discrepancies[0].status == "resolved"


def test_build_projected_state_resolution_for_unknown_discrepancy_is_ignored() -> None:
    projected = build_projected_state(
        [
            Event(
                id="res:002",
                type="discrepancy_resolution_recorded",
                payload={
                    "discrepancy_resolution": {
                        "id": "res-002",
                        "discrepancy_id": "run-unknown",
                        "resolution_summary": "Unknown target",
                        "source_run_id": "run-2",
                    }
                },
            )
        ]
    )
    assert projected.unresolved_discrepancies == []


def test_build_projected_state_resolution_does_not_change_other_open_discrepancies() -> None:
    projected = build_projected_state(
        [
            Event(
                id="g1:run-1:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "blocking issue run-1"}},
                },
            ),
            Event(
                id="g2:run-2:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g2",
                    "run_id": "run-2",
                    "terminal_outcome": "revision_budget_exhausted",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "blocking issue run-2"}},
                },
            ),
            Event(
                id="res:003",
                type="discrepancy_resolution_recorded",
                payload={
                    "discrepancy_resolution": {
                        "id": "res-003",
                        "discrepancy_id": "run-1",
                        "resolution_summary": "Resolved run-1",
                        "source_run_id": "run-3",
                    }
                },
            ),
        ]
    )
    statuses = {d.id: d.status for d in projected.unresolved_discrepancies}
    assert statuses["run-1"] == "resolved"
    assert statuses["run-2"] == "open"


def test_build_projected_state_supersession_marks_known_discrepancy_superseded() -> None:
    projected = build_projected_state(
        [
            Event(
                id="g1:run-1:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "blocking issue found"}},
                },
            ),
            Event(
                id="sup:001",
                type="discrepancy_supersession_recorded",
                payload={
                    "discrepancy_supersession": {
                        "id": "sup-001",
                        "superseded_discrepancy_id": "run-1",
                        "superseding_discrepancy_id": "run-2",
                        "rationale": "run-2 supersedes run-1",
                        "source_run_id": "run-2",
                    }
                },
            ),
        ]
    )
    assert len(projected.unresolved_discrepancies) == 1
    discrepancy = projected.unresolved_discrepancies[0]
    assert discrepancy.id == "run-1"
    assert discrepancy.status == "superseded"
    assert discrepancy.metadata["superseding_discrepancy_id"] == "run-2"


def test_build_projected_state_unknown_superseded_discrepancy_is_ignored() -> None:
    projected = build_projected_state(
        [
            Event(
                id="sup:002",
                type="discrepancy_supersession_recorded",
                payload={
                    "discrepancy_supersession": {
                        "id": "sup-002",
                        "superseded_discrepancy_id": "run-unknown",
                        "superseding_discrepancy_id": "run-2",
                        "rationale": "unknown superseded id",
                        "source_run_id": "run-2",
                    }
                },
            )
        ]
    )
    assert projected.unresolved_discrepancies == []


def test_build_projected_state_supersession_does_not_change_unrelated_discrepancies() -> None:
    projected = build_projected_state(
        [
            Event(
                id="g1:run-1:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "blocking issue run-1"}},
                },
            ),
            Event(
                id="g2:run-2:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g2",
                    "run_id": "run-2",
                    "terminal_outcome": "revision_budget_exhausted",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "blocking issue run-2"}},
                },
            ),
            Event(
                id="sup:003",
                type="discrepancy_supersession_recorded",
                payload={
                    "discrepancy_supersession": {
                        "id": "sup-003",
                        "superseded_discrepancy_id": "run-1",
                        "superseding_discrepancy_id": "run-3",
                        "rationale": "run-3 supersedes run-1",
                        "source_run_id": "run-3",
                    }
                },
            ),
        ]
    )
    statuses = {d.id: d.status for d in projected.unresolved_discrepancies}
    assert statuses["run-1"] == "superseded"
    assert statuses["run-2"] == "open"


def test_build_projected_state_resolution_behavior_still_works() -> None:
    projected = build_projected_state(
        [
            Event(
                id="g1:run-1:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "blocking issue run-1"}},
                },
            ),
            Event(
                id="res:004",
                type="discrepancy_resolution_recorded",
                payload={
                    "discrepancy_resolution": {
                        "id": "res-004",
                        "discrepancy_id": "run-1",
                        "resolution_summary": "resolved run-1",
                        "source_run_id": "run-2",
                    }
                },
            ),
        ]
    )
    assert len(projected.unresolved_discrepancies) == 1
    assert projected.unresolved_discrepancies[0].status == "resolved"


def test_build_projected_state_from_blackboard_preserves_active_game_projection(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "board.jsonl")
    board.append(
        Event(
            id="g1:run-1:r0001:game_started",
            type="game_started",
            payload={"game_id": "g1", "run_id": "run-1"},
        )
    )

    projected = build_projected_state_from_blackboard(board)
    assert [active.id for active in projected.active_games] == ["run-1"]


def test_build_projected_state_from_blackboard_preserves_integration_decision_projection(
    tmp_path: Path,
) -> None:
    board = Blackboard(tmp_path / "board.jsonl")
    board.append(
        Event(
            id="integration:int-001",
            type="integration_decision_recorded",
            payload={
                "integration_decision": {
                    "id": "int-001",
                    "run_id": "run-1",
                    "outcome": "accepted",
                    "target_kind": "accomplishment",
                    "summary": "Accepted accomplishment summary",
                    "rationale": "Accepted by integration authority",
                }
            },
        )
    )

    projected = build_projected_state_from_blackboard(board)
    assert len(projected.accepted_accomplishments) == 1
    assert projected.accepted_accomplishments[0].id == "int-001"


def test_build_projected_state_from_blackboard_preserves_discrepancy_lifecycle_projection(
    tmp_path: Path,
) -> None:
    board = Blackboard(tmp_path / "board.jsonl")
    board.append(
        Event(
            id="g1:run-1:game_completed",
            type="game_completed",
            payload={
                "game_id": "g1",
                "run_id": "run-1",
                "terminal_outcome": "rejected_locally",
                "integration_recommendation": "do_not_integrate",
                "state": {"final_decision": {"rationale": "blocking issue run-1"}},
            },
        )
    )
    board.append(
        Event(
            id="res:001",
            type="discrepancy_resolution_recorded",
            payload={
                "discrepancy_resolution": {
                    "id": "res-001",
                    "discrepancy_id": "run-1",
                    "resolution_summary": "resolved run-1",
                    "source_run_id": "run-2",
                }
            },
        )
    )
    board.append(
        Event(
            id="sup:001",
            type="discrepancy_supersession_recorded",
            payload={
                "discrepancy_supersession": {
                    "id": "sup-001",
                    "superseded_discrepancy_id": "run-1",
                    "superseding_discrepancy_id": "run-3",
                    "rationale": "run-3 supersedes run-1",
                    "source_run_id": "run-3",
                }
            },
        )
    )

    projected = build_projected_state_from_blackboard(board)
    assert len(projected.unresolved_discrepancies) == 1
    discrepancy = projected.unresolved_discrepancies[0]
    assert discrepancy.id == "run-1"
    assert discrepancy.status == "superseded"
    assert discrepancy.metadata["superseding_discrepancy_id"] == "run-3"


def test_build_projected_state_metadata_counts_match_projected_lists() -> None:
    events = [
        Event(
            id="g1:run-1:r0001:game_started",
            type="game_started",
            payload={"game_id": "g1", "run_id": "run-1"},
        ),
        Event(
            id="g2:run-2:game_completed",
            type="game_completed",
            payload={
                "game_id": "g2",
                "run_id": "run-2",
                "terminal_outcome": "rejected_locally",
                "integration_recommendation": "do_not_integrate",
                "state": {"final_decision": {"rationale": "blocking issue run-2"}},
            },
        ),
        Event(
            id="integration:int-1",
            type="integration_decision_recorded",
            payload={
                "integration_decision": {
                    "id": "int-1",
                    "run_id": "run-3",
                    "outcome": "accepted",
                    "target_kind": "accomplishment",
                    "summary": "Accepted accomplishment",
                    "rationale": "accepted",
                }
            },
        ),
        Event(
            id="integration:int-2",
            type="integration_decision_recorded",
            payload={
                "integration_decision": {
                    "id": "int-2",
                    "run_id": "run-4",
                    "outcome": "accepted",
                    "target_kind": "architecture",
                    "summary": "Accepted architecture",
                    "rationale": "accepted",
                }
            },
        ),
        Event(
            id="integration:int-3",
            type="integration_decision_recorded",
            payload={
                "integration_decision": {
                    "id": "int-3",
                    "run_id": "run-5",
                    "outcome": "accepted",
                    "target_kind": "capability",
                    "summary": "Accepted capability",
                    "rationale": "accepted",
                }
            },
        ),
    ]
    projected = build_projected_state(events)

    assert projected.metadata["event_count"] == len(events)
    assert projected.metadata["active_game_count"] == len(projected.active_games)
    assert projected.metadata["accepted_accomplishment_count"] == len(
        projected.accepted_accomplishments
    )
    assert projected.metadata["accepted_architecture_count"] == len(projected.accepted_architecture)
    assert projected.metadata["accepted_capability_count"] == len(projected.accepted_capabilities)
    assert projected.metadata["unresolved_discrepancy_count"] == len(
        projected.unresolved_discrepancies
    )


def test_build_projected_state_accepted_accomplishment_can_be_marked_superseded() -> None:
    projected = build_projected_state(
        [
            Event(
                id="integration:int-001",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "int-001",
                        "run_id": "run-1",
                        "outcome": "accepted",
                        "target_kind": "accomplishment",
                        "summary": "Accepted accomplishment",
                        "rationale": "accepted",
                    }
                },
            ),
            Event(
                id="asup:001",
                type="accepted_state_supersession_recorded",
                payload={
                    "accepted_state_supersession": {
                        "id": "asup-001",
                        "superseded_item_id": "int-001",
                        "superseding_item_id": "int-002",
                        "target_kind": "accomplishment",
                        "rationale": "newer accepted item",
                        "source_run_id": "run-2",
                    }
                },
            ),
        ]
    )
    item = projected.accepted_accomplishments[0]
    assert item.metadata["superseded"] is True
    assert item.metadata["superseding_item_id"] == "int-002"


def test_build_projected_state_accepted_architecture_can_be_marked_superseded() -> None:
    projected = build_projected_state(
        [
            Event(
                id="integration:int-arch-001",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "int-arch-001",
                        "run_id": "run-arch-1",
                        "outcome": "accepted",
                        "target_kind": "architecture",
                        "summary": "Accepted architecture",
                        "rationale": "accepted",
                    }
                },
            ),
            Event(
                id="asup:002",
                type="accepted_state_supersession_recorded",
                payload={
                    "accepted_state_supersession": {
                        "id": "asup-002",
                        "superseded_item_id": "int-arch-001",
                        "superseding_item_id": "int-arch-002",
                        "target_kind": "architecture",
                        "rationale": "newer architecture item",
                        "source_run_id": "run-arch-2",
                    }
                },
            ),
        ]
    )
    item = projected.accepted_architecture[0]
    assert item.metadata["superseded"] is True
    assert item.metadata["superseding_item_id"] == "int-arch-002"


def test_build_projected_state_accepted_capability_can_be_marked_superseded() -> None:
    projected = build_projected_state(
        [
            Event(
                id="integration:int-cap-001",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "int-cap-001",
                        "run_id": "run-cap-1",
                        "outcome": "accepted",
                        "target_kind": "capability",
                        "summary": "Accepted capability",
                        "rationale": "accepted",
                    }
                },
            ),
            Event(
                id="asup:003",
                type="accepted_state_supersession_recorded",
                payload={
                    "accepted_state_supersession": {
                        "id": "asup-003",
                        "superseded_item_id": "int-cap-001",
                        "superseding_item_id": "int-cap-002",
                        "target_kind": "capability",
                        "rationale": "newer capability item",
                        "source_run_id": "run-cap-2",
                    }
                },
            ),
        ]
    )
    item = projected.accepted_capabilities[0]
    assert item.metadata["superseded"] is True
    assert item.metadata["superseding_item_id"] == "int-cap-002"


def test_build_projected_state_unknown_accepted_state_superseded_id_is_ignored() -> None:
    projected = build_projected_state(
        [
            Event(
                id="asup:004",
                type="accepted_state_supersession_recorded",
                payload={
                    "accepted_state_supersession": {
                        "id": "asup-004",
                        "superseded_item_id": "unknown-item",
                        "superseding_item_id": "int-002",
                        "target_kind": "accomplishment",
                        "rationale": "unknown superseded id",
                        "source_run_id": "run-2",
                    }
                },
            ),
        ]
    )
    assert projected.accepted_accomplishments == []
    assert projected.accepted_architecture == []
    assert projected.accepted_capabilities == []


def test_build_projected_state_accepted_accomplishment_can_be_marked_revoked() -> None:
    projected = build_projected_state(
        [
            Event(
                id="integration:int-101",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "int-101",
                        "run_id": "run-1",
                        "outcome": "accepted",
                        "target_kind": "accomplishment",
                        "summary": "Accepted accomplishment",
                        "rationale": "accepted",
                    }
                },
            ),
            Event(
                id="arev:001",
                type="accepted_state_revocation_recorded",
                payload={
                    "accepted_state_revocation": {
                        "id": "arev-001",
                        "revoked_item_id": "int-101",
                        "target_kind": "accomplishment",
                        "rationale": "revoked",
                        "source_run_id": "run-2",
                    }
                },
            ),
        ]
    )
    item = projected.accepted_accomplishments[0]
    assert item.metadata["revoked"] is True
    assert item.metadata["revocation_id"] == "arev-001"


def test_build_projected_state_accepted_architecture_can_be_marked_revoked() -> None:
    projected = build_projected_state(
        [
            Event(
                id="integration:int-arch-101",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "int-arch-101",
                        "run_id": "run-arch-1",
                        "outcome": "accepted",
                        "target_kind": "architecture",
                        "summary": "Accepted architecture",
                        "rationale": "accepted",
                    }
                },
            ),
            Event(
                id="arev:002",
                type="accepted_state_revocation_recorded",
                payload={
                    "accepted_state_revocation": {
                        "id": "arev-002",
                        "revoked_item_id": "int-arch-101",
                        "target_kind": "architecture",
                        "rationale": "revoked",
                        "source_run_id": "run-arch-2",
                    }
                },
            ),
        ]
    )
    item = projected.accepted_architecture[0]
    assert item.metadata["revoked"] is True
    assert item.metadata["revocation_id"] == "arev-002"


def test_build_projected_state_accepted_capability_can_be_marked_revoked() -> None:
    projected = build_projected_state(
        [
            Event(
                id="integration:int-cap-101",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "int-cap-101",
                        "run_id": "run-cap-1",
                        "outcome": "accepted",
                        "target_kind": "capability",
                        "summary": "Accepted capability",
                        "rationale": "accepted",
                    }
                },
            ),
            Event(
                id="arev:003",
                type="accepted_state_revocation_recorded",
                payload={
                    "accepted_state_revocation": {
                        "id": "arev-003",
                        "revoked_item_id": "int-cap-101",
                        "target_kind": "capability",
                        "rationale": "revoked",
                        "source_run_id": "run-cap-2",
                    }
                },
            ),
        ]
    )
    item = projected.accepted_capabilities[0]
    assert item.metadata["revoked"] is True
    assert item.metadata["revocation_id"] == "arev-003"


def test_build_projected_state_unknown_accepted_state_revoked_id_is_ignored() -> None:
    projected = build_projected_state(
        [
            Event(
                id="arev:004",
                type="accepted_state_revocation_recorded",
                payload={
                    "accepted_state_revocation": {
                        "id": "arev-004",
                        "revoked_item_id": "unknown-item",
                        "target_kind": "accomplishment",
                        "rationale": "unknown revoked id",
                        "source_run_id": "run-2",
                    }
                },
            ),
        ]
    )
    assert projected.accepted_accomplishments == []
    assert projected.accepted_architecture == []
    assert projected.accepted_capabilities == []


def test_current_helpers_return_all_items_when_not_superseded_or_revoked() -> None:
    state = build_projected_state(
        [
            Event(
                id="integration:acc-1",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "acc-1",
                        "run_id": "run-1",
                        "outcome": "accepted",
                        "target_kind": "accomplishment",
                        "summary": "acc",
                        "rationale": "ok",
                    }
                },
            ),
            Event(
                id="integration:arch-1",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "arch-1",
                        "run_id": "run-1",
                        "outcome": "accepted",
                        "target_kind": "architecture",
                        "summary": "arch",
                        "rationale": "ok",
                    }
                },
            ),
            Event(
                id="integration:cap-1",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "cap-1",
                        "run_id": "run-1",
                        "outcome": "accepted",
                        "target_kind": "capability",
                        "summary": "cap",
                        "rationale": "ok",
                    }
                },
            ),
        ]
    )

    assert len(current_accepted_accomplishments(state)) == 1
    assert len(current_accepted_architecture(state)) == 1
    assert len(current_accepted_capabilities(state)) == 1


def test_current_helpers_exclude_superseded_and_revoked_items() -> None:
    state = build_projected_state(
        [
            Event(
                id="integration:acc-1",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "acc-1",
                        "run_id": "run-1",
                        "outcome": "accepted",
                        "target_kind": "accomplishment",
                        "summary": "acc",
                        "rationale": "ok",
                    }
                },
            ),
            Event(
                id="integration:acc-2",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "acc-2",
                        "run_id": "run-2",
                        "outcome": "accepted",
                        "target_kind": "accomplishment",
                        "summary": "acc2",
                        "rationale": "ok",
                    }
                },
            ),
            Event(
                id="asup:acc-1",
                type="accepted_state_supersession_recorded",
                payload={
                    "accepted_state_supersession": {
                        "id": "asup-acc-1",
                        "superseded_item_id": "acc-1",
                        "superseding_item_id": "acc-3",
                        "target_kind": "accomplishment",
                        "rationale": "superseded",
                        "source_run_id": "run-3",
                    }
                },
            ),
            Event(
                id="arev:acc-2",
                type="accepted_state_revocation_recorded",
                payload={
                    "accepted_state_revocation": {
                        "id": "arev-acc-2",
                        "revoked_item_id": "acc-2",
                        "target_kind": "accomplishment",
                        "rationale": "revoked",
                        "source_run_id": "run-4",
                    }
                },
            ),
        ]
    )

    assert current_accepted_accomplishments(state) == []


def test_current_helpers_preserve_order() -> None:
    state = build_projected_state(
        [
            Event(
                id="integration:cap-1",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "cap-1",
                        "run_id": "run-1",
                        "outcome": "accepted",
                        "target_kind": "capability",
                        "summary": "cap1",
                        "rationale": "ok",
                    }
                },
            ),
            Event(
                id="integration:cap-2",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "cap-2",
                        "run_id": "run-2",
                        "outcome": "accepted",
                        "target_kind": "capability",
                        "summary": "cap2",
                        "rationale": "ok",
                    }
                },
            ),
        ]
    )

    current = current_accepted_capabilities(state)
    assert [item.id for item in current] == ["cap-1", "cap-2"]


def test_current_helpers_do_not_mutate_input_state() -> None:
    state = build_projected_state(
        [
            Event(
                id="integration:arch-1",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "arch-1",
                        "run_id": "run-1",
                        "outcome": "accepted",
                        "target_kind": "architecture",
                        "summary": "arch1",
                        "rationale": "ok",
                    }
                },
            ),
        ]
    )
    before_metadata = dict(state.accepted_architecture[0].metadata)

    _ = current_accepted_architecture(state)

    assert state.accepted_architecture[0].metadata == before_metadata


def test_accepted_state_supersession_chain_single_item_no_supersession() -> None:
    state = build_projected_state(
        [
            Event(
                id="integration:item-1",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "item-1",
                        "run_id": "run-1",
                        "outcome": "accepted",
                        "target_kind": "accomplishment",
                        "summary": "item 1",
                        "rationale": "ok",
                    }
                },
            ),
        ]
    )
    assert accepted_state_supersession_chain(state, "item-1") == ["item-1"]


def test_accepted_state_supersession_chain_one_step() -> None:
    state = build_projected_state(
        [
            Event(
                id="integration:item-1",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "item-1",
                        "run_id": "run-1",
                        "outcome": "accepted",
                        "target_kind": "accomplishment",
                        "summary": "item 1",
                        "rationale": "ok",
                    }
                },
            ),
            Event(
                id="asup:1",
                type="accepted_state_supersession_recorded",
                payload={
                    "accepted_state_supersession": {
                        "id": "asup-1",
                        "superseded_item_id": "item-1",
                        "superseding_item_id": "item-2",
                        "target_kind": "accomplishment",
                        "rationale": "superseded",
                        "source_run_id": "run-2",
                    }
                },
            ),
        ]
    )
    assert accepted_state_supersession_chain(state, "item-1") == ["item-1", "item-2"]


def test_accepted_state_supersession_chain_multi_step() -> None:
    state = build_projected_state(
        [
            Event(
                id="integration:item-1",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "item-1",
                        "run_id": "run-1",
                        "outcome": "accepted",
                        "target_kind": "accomplishment",
                        "summary": "item 1",
                        "rationale": "ok",
                    }
                },
            ),
            Event(
                id="integration:item-2",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "item-2",
                        "run_id": "run-2",
                        "outcome": "accepted",
                        "target_kind": "accomplishment",
                        "summary": "item 2",
                        "rationale": "ok",
                    }
                },
            ),
            Event(
                id="integration:item-3",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "item-3",
                        "run_id": "run-3",
                        "outcome": "accepted",
                        "target_kind": "accomplishment",
                        "summary": "item 3",
                        "rationale": "ok",
                    }
                },
            ),
            Event(
                id="asup:1",
                type="accepted_state_supersession_recorded",
                payload={
                    "accepted_state_supersession": {
                        "id": "asup-1",
                        "superseded_item_id": "item-1",
                        "superseding_item_id": "item-2",
                        "target_kind": "accomplishment",
                        "rationale": "superseded",
                        "source_run_id": "run-2",
                    }
                },
            ),
            Event(
                id="asup:2",
                type="accepted_state_supersession_recorded",
                payload={
                    "accepted_state_supersession": {
                        "id": "asup-2",
                        "superseded_item_id": "item-2",
                        "superseding_item_id": "item-3",
                        "target_kind": "accomplishment",
                        "rationale": "superseded",
                        "source_run_id": "run-3",
                    }
                },
            ),
        ]
    )
    assert accepted_state_supersession_chain(state, "item-1") == ["item-1", "item-2", "item-3"]


def test_accepted_state_supersession_chain_stops_on_unknown_next_id() -> None:
    state = build_projected_state(
        [
            Event(
                id="integration:item-1",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "item-1",
                        "run_id": "run-1",
                        "outcome": "accepted",
                        "target_kind": "architecture",
                        "summary": "item 1",
                        "rationale": "ok",
                    }
                },
            ),
            Event(
                id="asup:1",
                type="accepted_state_supersession_recorded",
                payload={
                    "accepted_state_supersession": {
                        "id": "asup-1",
                        "superseded_item_id": "item-1",
                        "superseding_item_id": "missing-item",
                        "target_kind": "architecture",
                        "rationale": "superseded",
                        "source_run_id": "run-2",
                    }
                },
            ),
        ]
    )
    assert accepted_state_supersession_chain(state, "item-1") == ["item-1", "missing-item"]


def test_accepted_state_supersession_chain_stops_on_cycle() -> None:
    state = build_projected_state(
        [
            Event(
                id="integration:item-1",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "item-1",
                        "run_id": "run-1",
                        "outcome": "accepted",
                        "target_kind": "capability",
                        "summary": "item 1",
                        "rationale": "ok",
                    }
                },
            ),
            Event(
                id="integration:item-2",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "item-2",
                        "run_id": "run-2",
                        "outcome": "accepted",
                        "target_kind": "capability",
                        "summary": "item 2",
                        "rationale": "ok",
                    }
                },
            ),
            Event(
                id="asup:1",
                type="accepted_state_supersession_recorded",
                payload={
                    "accepted_state_supersession": {
                        "id": "asup-1",
                        "superseded_item_id": "item-1",
                        "superseding_item_id": "item-2",
                        "target_kind": "capability",
                        "rationale": "superseded",
                        "source_run_id": "run-2",
                    }
                },
            ),
            Event(
                id="asup:2",
                type="accepted_state_supersession_recorded",
                payload={
                    "accepted_state_supersession": {
                        "id": "asup-2",
                        "superseded_item_id": "item-2",
                        "superseding_item_id": "item-1",
                        "target_kind": "capability",
                        "rationale": "cycle",
                        "source_run_id": "run-3",
                    }
                },
            ),
        ]
    )
    assert accepted_state_supersession_chain(state, "item-1") == ["item-1", "item-2"]


def test_accepted_state_supersession_chain_rejects_empty_item_id() -> None:
    state = build_projected_state([])
    with pytest.raises(ValueError, match="item_id must be a non-empty string"):
        accepted_state_supersession_chain(state, "   ")


def test_accepted_state_supersession_chain_does_not_mutate_input_state() -> None:
    state = build_projected_state(
        [
            Event(
                id="integration:item-1",
                type="integration_decision_recorded",
                payload={
                    "integration_decision": {
                        "id": "item-1",
                        "run_id": "run-1",
                        "outcome": "accepted",
                        "target_kind": "accomplishment",
                        "summary": "item 1",
                        "rationale": "ok",
                    }
                },
            ),
        ]
    )
    before_metadata = dict(state.accepted_accomplishments[0].metadata)
    _ = accepted_state_supersession_chain(state, "item-1")
    assert state.accepted_accomplishments[0].metadata == before_metadata


def test_discrepancy_supersession_chain_single_item_no_supersession() -> None:
    state = build_projected_state(
        [
            Event(
                id="g1:run-1:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "issue run-1"}},
                },
            ),
        ]
    )
    assert discrepancy_supersession_chain(state, "run-1") == ["run-1"]


def test_discrepancy_supersession_chain_one_step() -> None:
    state = build_projected_state(
        [
            Event(
                id="g1:run-1:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "issue run-1"}},
                },
            ),
            Event(
                id="g2:run-2:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g2",
                    "run_id": "run-2",
                    "terminal_outcome": "revision_budget_exhausted",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "issue run-2"}},
                },
            ),
            Event(
                id="sup:1",
                type="discrepancy_supersession_recorded",
                payload={
                    "discrepancy_supersession": {
                        "id": "sup-1",
                        "superseded_discrepancy_id": "run-1",
                        "superseding_discrepancy_id": "run-2",
                        "rationale": "run-2 supersedes run-1",
                        "source_run_id": "run-2",
                    }
                },
            ),
        ]
    )
    assert discrepancy_supersession_chain(state, "run-1") == ["run-1", "run-2"]


def test_discrepancy_supersession_chain_multi_step() -> None:
    state = build_projected_state(
        [
            Event(
                id="g1:run-1:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "issue run-1"}},
                },
            ),
            Event(
                id="g2:run-2:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g2",
                    "run_id": "run-2",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "issue run-2"}},
                },
            ),
            Event(
                id="g3:run-3:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g3",
                    "run_id": "run-3",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "issue run-3"}},
                },
            ),
            Event(
                id="sup:1",
                type="discrepancy_supersession_recorded",
                payload={
                    "discrepancy_supersession": {
                        "id": "sup-1",
                        "superseded_discrepancy_id": "run-1",
                        "superseding_discrepancy_id": "run-2",
                        "rationale": "run-2 supersedes run-1",
                        "source_run_id": "run-2",
                    }
                },
            ),
            Event(
                id="sup:2",
                type="discrepancy_supersession_recorded",
                payload={
                    "discrepancy_supersession": {
                        "id": "sup-2",
                        "superseded_discrepancy_id": "run-2",
                        "superseding_discrepancy_id": "run-3",
                        "rationale": "run-3 supersedes run-2",
                        "source_run_id": "run-3",
                    }
                },
            ),
        ]
    )
    assert discrepancy_supersession_chain(state, "run-1") == ["run-1", "run-2", "run-3"]


def test_discrepancy_supersession_chain_stops_on_unknown_next_id() -> None:
    state = build_projected_state(
        [
            Event(
                id="g1:run-1:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "issue run-1"}},
                },
            ),
            Event(
                id="sup:1",
                type="discrepancy_supersession_recorded",
                payload={
                    "discrepancy_supersession": {
                        "id": "sup-1",
                        "superseded_discrepancy_id": "run-1",
                        "superseding_discrepancy_id": "run-missing",
                        "rationale": "unknown next id",
                        "source_run_id": "run-2",
                    }
                },
            ),
        ]
    )
    assert discrepancy_supersession_chain(state, "run-1") == ["run-1", "run-missing"]


def test_discrepancy_supersession_chain_stops_on_cycle() -> None:
    state = build_projected_state(
        [
            Event(
                id="g1:run-1:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "issue run-1"}},
                },
            ),
            Event(
                id="g2:run-2:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g2",
                    "run_id": "run-2",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "issue run-2"}},
                },
            ),
            Event(
                id="sup:1",
                type="discrepancy_supersession_recorded",
                payload={
                    "discrepancy_supersession": {
                        "id": "sup-1",
                        "superseded_discrepancy_id": "run-1",
                        "superseding_discrepancy_id": "run-2",
                        "rationale": "run-2 supersedes run-1",
                        "source_run_id": "run-2",
                    }
                },
            ),
            Event(
                id="sup:2",
                type="discrepancy_supersession_recorded",
                payload={
                    "discrepancy_supersession": {
                        "id": "sup-2",
                        "superseded_discrepancy_id": "run-2",
                        "superseding_discrepancy_id": "run-1",
                        "rationale": "cycle",
                        "source_run_id": "run-3",
                    }
                },
            ),
        ]
    )
    assert discrepancy_supersession_chain(state, "run-1") == ["run-1", "run-2"]


def test_discrepancy_supersession_chain_rejects_empty_discrepancy_id() -> None:
    state = build_projected_state([])
    with pytest.raises(ValueError, match="discrepancy_id must be a non-empty string"):
        discrepancy_supersession_chain(state, "   ")


def test_discrepancy_supersession_chain_does_not_mutate_input_state() -> None:
    state = build_projected_state(
        [
            Event(
                id="g1:run-1:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "issue run-1"}},
                },
            ),
        ]
    )
    before_metadata = dict(state.unresolved_discrepancies[0].metadata)
    _ = discrepancy_supersession_chain(state, "run-1")
    assert state.unresolved_discrepancies[0].metadata == before_metadata


def test_current_open_discrepancies_returns_only_open_items() -> None:
    state = build_projected_state(
        [
            Event(
                id="g1:run-1:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "issue run-1"}},
                },
            ),
            Event(
                id="g2:run-2:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g2",
                    "run_id": "run-2",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "issue run-2"}},
                },
            ),
            Event(
                id="g3:run-3:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g3",
                    "run_id": "run-3",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "issue run-3"}},
                },
            ),
            Event(
                id="res:2",
                type="discrepancy_resolution_recorded",
                payload={
                    "discrepancy_resolution": {
                        "id": "res-2",
                        "discrepancy_id": "run-2",
                        "resolution_summary": "resolved run-2",
                        "source_run_id": "run-9",
                    }
                },
            ),
            Event(
                id="sup:3",
                type="discrepancy_supersession_recorded",
                payload={
                    "discrepancy_supersession": {
                        "id": "sup-3",
                        "superseded_discrepancy_id": "run-3",
                        "superseding_discrepancy_id": "run-10",
                        "rationale": "run-10 supersedes run-3",
                        "source_run_id": "run-10",
                    }
                },
            ),
        ]
    )

    current = current_open_discrepancies(state)
    assert [item.id for item in current] == ["run-1"]


def test_current_open_discrepancies_preserves_order() -> None:
    state = build_projected_state(
        [
            Event(
                id="g1:run-1:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "issue run-1"}},
                },
            ),
            Event(
                id="g2:run-2:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g2",
                    "run_id": "run-2",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "issue run-2"}},
                },
            ),
        ]
    )
    assert [item.id for item in current_open_discrepancies(state)] == ["run-1", "run-2"]


def test_current_open_discrepancies_does_not_mutate_input_state() -> None:
    state = build_projected_state(
        [
            Event(
                id="g1:run-1:game_completed",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "rejected_locally",
                    "integration_recommendation": "do_not_integrate",
                    "state": {"final_decision": {"rationale": "issue run-1"}},
                },
            ),
        ]
    )
    before_status = state.unresolved_discrepancies[0].status
    before_metadata = dict(state.unresolved_discrepancies[0].metadata)
    _ = current_open_discrepancies(state)
    assert state.unresolved_discrepancies[0].status == before_status
    assert state.unresolved_discrepancies[0].metadata == before_metadata


def test_discrepancies_by_severity_returns_matching_discrepancies_only() -> None:
    state = ProjectedState(
        unresolved_discrepancies=[
            UnresolvedDiscrepancy(
                id="d1",
                summary="s1",
                kind="unresolved_finding",
                severity="high",
                status="open",
                source_event_id="e1",
            ),
            UnresolvedDiscrepancy(
                id="d2",
                summary="s2",
                kind="unresolved_finding",
                severity="medium",
                status="resolved",
                source_event_id="e2",
            ),
            UnresolvedDiscrepancy(
                id="d3",
                summary="s3",
                kind="unresolved_finding",
                severity="high",
                status="superseded",
                source_event_id="e3",
            ),
        ]
    )

    filtered = discrepancies_by_severity(state, "high")
    assert [d.id for d in filtered] == ["d1", "d3"]


def test_current_open_discrepancies_by_severity_excludes_resolved_and_superseded() -> None:
    state = ProjectedState(
        unresolved_discrepancies=[
            UnresolvedDiscrepancy(
                id="d1",
                summary="s1",
                kind="unresolved_finding",
                severity="high",
                status="open",
                source_event_id="e1",
            ),
            UnresolvedDiscrepancy(
                id="d2",
                summary="s2",
                kind="unresolved_finding",
                severity="high",
                status="resolved",
                source_event_id="e2",
            ),
            UnresolvedDiscrepancy(
                id="d3",
                summary="s3",
                kind="unresolved_finding",
                severity="high",
                status="superseded",
                source_event_id="e3",
            ),
        ]
    )

    filtered = current_open_discrepancies_by_severity(state, "high")
    assert [d.id for d in filtered] == ["d1"]


def test_discrepancy_severity_helpers_preserve_order() -> None:
    state = ProjectedState(
        unresolved_discrepancies=[
            UnresolvedDiscrepancy(
                id="d1",
                summary="s1",
                kind="unresolved_finding",
                severity="medium",
                status="open",
                source_event_id="e1",
            ),
            UnresolvedDiscrepancy(
                id="d2",
                summary="s2",
                kind="unresolved_finding",
                severity="medium",
                status="open",
                source_event_id="e2",
            ),
        ]
    )

    assert [d.id for d in discrepancies_by_severity(state, "medium")] == ["d1", "d2"]
    assert [d.id for d in current_open_discrepancies_by_severity(state, "medium")] == ["d1", "d2"]


def test_discrepancy_severity_helpers_reject_invalid_severity() -> None:
    state = ProjectedState()
    with pytest.raises(ValueError, match="severity must be one of: low, medium, high"):
        discrepancies_by_severity(state, "critical")
    with pytest.raises(ValueError, match="severity must be one of: low, medium, high"):
        current_open_discrepancies_by_severity(state, "critical")


def test_discrepancy_severity_helpers_do_not_mutate_input_state() -> None:
    state = ProjectedState(
        unresolved_discrepancies=[
            UnresolvedDiscrepancy(
                id="d1",
                summary="s1",
                kind="unresolved_finding",
                severity="low",
                status="open",
                source_event_id="e1",
            ),
        ]
    )
    before_status = state.unresolved_discrepancies[0].status
    before_metadata = dict(state.unresolved_discrepancies[0].metadata)
    _ = discrepancies_by_severity(state, "low")
    _ = current_open_discrepancies_by_severity(state, "low")
    assert state.unresolved_discrepancies[0].status == before_status
    assert state.unresolved_discrepancies[0].metadata == before_metadata


def test_deferred_integration_decisions_returns_only_deferred_in_order() -> None:
    events = [
        Event(
            id="e1",
            type="integration_decision_recorded",
            payload={
                "integration_decision": {
                    "id": "int-1",
                    "run_id": "run-1",
                    "outcome": "deferred",
                    "target_kind": "accomplishment",
                    "summary": "deferred one",
                    "rationale": "deferred rationale",
                    "metadata": {"deferred_reason": "reason-1"},
                }
            },
        ),
        Event(
            id="e2",
            type="integration_decision_recorded",
            payload={
                "integration_decision": {
                    "id": "int-2",
                    "run_id": "run-2",
                    "outcome": "accepted",
                    "target_kind": "accomplishment",
                    "summary": "accepted one",
                    "rationale": "accepted rationale",
                }
            },
        ),
        Event(
            id="e3",
            type="integration_decision_recorded",
            payload={
                "integration_decision": {
                    "id": "int-3",
                    "run_id": "run-3",
                    "outcome": "rejected",
                    "target_kind": "accomplishment",
                    "summary": "rejected one",
                    "rationale": "rejected rationale",
                }
            },
        ),
        Event(
            id="e4",
            type="integration_decision_recorded",
            payload={
                "integration_decision": {
                    "id": "int-4",
                    "run_id": "run-4",
                    "outcome": "deferred",
                    "target_kind": "accomplishment",
                    "summary": "deferred two",
                    "rationale": "deferred rationale two",
                    "metadata": {
                        "deferred_reason": "competing_candidate_already_accepted",
                        "accepted_competitor_run_id": "run-1",
                    },
                }
            },
        ),
    ]

    decisions = deferred_integration_decisions(events)
    assert [decision.id for decision in decisions] == ["int-1", "int-4"]


def test_deferred_integration_decisions_ignores_malformed_and_unrelated_events() -> None:
    events = [
        Event(
            id="e1",
            type="game_started",
            payload={"game_id": "g1", "run_id": "run-1"},
        ),
        Event(
            id="e2",
            type="integration_decision_recorded",
            payload={"integration_decision": "not-a-dict"},
        ),
        Event(
            id="e3",
            type="integration_decision_recorded",
            payload={
                "integration_decision": {
                    "id": "",
                    "run_id": "run-2",
                    "outcome": "deferred",
                    "target_kind": "accomplishment",
                    "summary": "bad decision",
                    "rationale": "bad",
                }
            },
        ),
    ]

    decisions = deferred_integration_decisions(events)
    assert decisions == []


def test_deferred_integration_decisions_preserve_conflict_metadata() -> None:
    events = [
        Event(
            id="e1",
            type="integration_decision_recorded",
            payload={
                "integration_decision": {
                    "id": "int-1",
                    "run_id": "run-2",
                    "outcome": "deferred",
                    "target_kind": "accomplishment",
                    "summary": "deferred due to conflict",
                    "rationale": "deferred",
                    "metadata": {
                        "deferred_reason": "competing_candidate_already_accepted",
                        "accepted_competitor_run_id": "run-1",
                    },
                }
            },
        ),
    ]

    decisions = deferred_integration_decisions(events)
    assert len(decisions) == 1
    assert isinstance(decisions[0], IntegrationDecision)
    assert decisions[0].metadata["deferred_reason"] == "competing_candidate_already_accepted"
    assert decisions[0].metadata["accepted_competitor_run_id"] == "run-1"


def test_integration_review_queue_contains_deferred_only_in_order() -> None:
    events = [
        Event(
            id="e1",
            type="integration_decision_recorded",
            payload={
                "integration_decision": {
                    "id": "int-1",
                    "run_id": "run-1",
                    "outcome": "deferred",
                    "target_kind": "accomplishment",
                    "summary": "queue-1",
                    "rationale": "r1",
                }
            },
        ),
        Event(
            id="e2",
            type="integration_decision_recorded",
            payload={
                "integration_decision": {
                    "id": "int-2",
                    "run_id": "run-2",
                    "outcome": "accepted",
                    "target_kind": "accomplishment",
                    "summary": "accepted",
                    "rationale": "r2",
                }
            },
        ),
        Event(
            id="e3",
            type="integration_decision_recorded",
            payload={
                "integration_decision": {
                    "id": "int-3",
                    "run_id": "run-3",
                    "outcome": "rejected",
                    "target_kind": "accomplishment",
                    "summary": "rejected",
                    "rationale": "r3",
                }
            },
        ),
        Event(
            id="e4",
            type="integration_decision_recorded",
            payload={
                "integration_decision": {
                    "id": "int-4",
                    "run_id": "run-4",
                    "outcome": "deferred",
                    "target_kind": "accomplishment",
                    "summary": "queue-2",
                    "rationale": "r4",
                    "metadata": {
                        "deferred_reason": "competing_candidate_already_accepted",
                        "accepted_competitor_run_id": "run-1",
                    },
                }
            },
        ),
    ]

    queue = integration_review_queue(events)
    assert [decision.id for decision in queue] == ["int-1", "int-4"]
    assert queue[1].metadata["deferred_reason"] == "competing_candidate_already_accepted"
    assert queue[1].metadata["accepted_competitor_run_id"] == "run-1"


def test_integration_review_queue_reuses_deferred_integration_decisions_behavior() -> None:
    events = [
        Event(
            id="e1",
            type="integration_decision_recorded",
            payload={
                "integration_decision": {
                    "id": "int-1",
                    "run_id": "run-1",
                    "outcome": "deferred",
                    "target_kind": "accomplishment",
                    "summary": "queue-1",
                    "rationale": "r1",
                }
            },
        ),
        Event(id="e2", type="integration_decision_recorded", payload={"integration_decision": "invalid"}),
    ]

    assert [d.model_dump(mode="json") for d in integration_review_queue(events)] == [
        d.model_dump(mode="json") for d in deferred_integration_decisions(events)
    ]


def test_discrepancies_for_artifact_returns_matching_discrepancies_only() -> None:
    state = ProjectedState(
        unresolved_discrepancies=[
            UnresolvedDiscrepancy(
                id="d1",
                summary="s1",
                kind="unresolved_finding",
                severity="medium",
                status="open",
                source_event_id="e1",
                related_artifact_id="artifact-a",
                related_artifact_version="v1",
            ),
            UnresolvedDiscrepancy(
                id="d2",
                summary="s2",
                kind="unresolved_finding",
                severity="high",
                status="open",
                source_event_id="e2",
                related_artifact_id="artifact-b",
            ),
            UnresolvedDiscrepancy(
                id="d3",
                summary="s3",
                kind="unresolved_finding",
                severity="low",
                status="resolved",
                source_event_id="e3",
            ),
        ]
    )

    filtered = discrepancies_for_artifact(state, "artifact-a")
    assert [d.id for d in filtered] == ["d1"]


def test_discrepancies_for_artifact_preserves_order_and_ignores_unlinked() -> None:
    state = ProjectedState(
        unresolved_discrepancies=[
            UnresolvedDiscrepancy(
                id="d1",
                summary="s1",
                kind="unresolved_finding",
                severity="medium",
                status="open",
                source_event_id="e1",
                related_artifact_id="artifact-a",
            ),
            UnresolvedDiscrepancy(
                id="d2",
                summary="s2",
                kind="unresolved_finding",
                severity="medium",
                status="open",
                source_event_id="e2",
            ),
            UnresolvedDiscrepancy(
                id="d3",
                summary="s3",
                kind="unresolved_finding",
                severity="medium",
                status="open",
                source_event_id="e3",
                related_artifact_id="artifact-a",
            ),
        ]
    )

    filtered = discrepancies_for_artifact(state, "artifact-a")
    assert [d.id for d in filtered] == ["d1", "d3"]


def test_discrepancies_for_artifact_rejects_empty_artifact_id() -> None:
    state = ProjectedState()
    with pytest.raises(ValueError, match="artifact_id must be a non-empty string"):
        discrepancies_for_artifact(state, "   ")


def test_discrepancies_for_artifact_does_not_mutate_input_state() -> None:
    state = ProjectedState(
        unresolved_discrepancies=[
            UnresolvedDiscrepancy(
                id="d1",
                summary="s1",
                kind="unresolved_finding",
                severity="medium",
                status="open",
                source_event_id="e1",
                related_artifact_id="artifact-a",
                metadata={"k": "v"},
            ),
        ]
    )
    before_status = state.unresolved_discrepancies[0].status
    before_metadata = dict(state.unresolved_discrepancies[0].metadata)
    _ = discrepancies_for_artifact(state, "artifact-a")
    assert state.unresolved_discrepancies[0].status == before_status
    assert state.unresolved_discrepancies[0].metadata == before_metadata


def test_artifact_proposal_records_parse_valid_events_in_order() -> None:
    events = [
        Event(
            id="e1",
            type="artifact_proposal_recorded",
            payload={
                "artifact_proposal_record": {
                    "id": "apr-1",
                    "artifact_id": "art-1",
                    "change_id": "chg-1",
                    "source_run_id": "run-1",
                    "status": "proposed",
                    "summary": "summary-1",
                }
            },
        ),
        Event(
            id="e2",
            type="artifact_proposal_recorded",
            payload={
                "artifact_proposal_record": {
                    "id": "apr-2",
                    "artifact_id": "art-2",
                    "change_id": "chg-2",
                    "source_run_id": "run-2",
                    "integration_decision_id": "int-2",
                    "status": "accepted",
                    "summary": "summary-2",
                }
            },
        ),
    ]

    records = artifact_proposal_records(events)
    assert [record.id for record in records] == ["apr-1", "apr-2"]
    assert records[1].integration_decision_id == "int-2"


def test_artifact_proposal_records_ignore_malformed_and_unrelated_events() -> None:
    events = [
        Event(id="e1", type="game_started", payload={"game_id": "g1", "run_id": "run-1"}),
        Event(
            id="e2",
            type="artifact_proposal_recorded",
            payload={"artifact_proposal_record": "not-a-dict"},
        ),
        Event(
            id="e3",
            type="artifact_proposal_recorded",
            payload={
                "artifact_proposal_record": {
                    "id": "",
                    "artifact_id": "art-3",
                    "change_id": "chg-3",
                    "source_run_id": "run-3",
                    "status": "proposed",
                    "summary": "bad",
                }
            },
        ),
    ]
    assert artifact_proposal_records(events) == []


def test_artifact_proposal_status_filters_and_order_preserved() -> None:
    events = [
        Event(
            id="e1",
            type="artifact_proposal_recorded",
            payload={
                "artifact_proposal_record": {
                    "id": "apr-1",
                    "artifact_id": "art-1",
                    "change_id": "chg-1",
                    "source_run_id": "run-1",
                    "status": "accepted",
                    "summary": "accepted-1",
                }
            },
        ),
        Event(
            id="e2",
            type="artifact_proposal_recorded",
            payload={
                "artifact_proposal_record": {
                    "id": "apr-2",
                    "artifact_id": "art-2",
                    "change_id": "chg-2",
                    "source_run_id": "run-2",
                    "status": "proposed",
                    "summary": "proposed-1",
                }
            },
        ),
        Event(
            id="e3",
            type="artifact_proposal_recorded",
            payload={
                "artifact_proposal_record": {
                    "id": "apr-3",
                    "artifact_id": "art-3",
                    "change_id": "chg-3",
                    "source_run_id": "run-3",
                    "status": "accepted",
                    "summary": "accepted-2",
                }
            },
        ),
        Event(
            id="e4",
            type="artifact_proposal_recorded",
            payload={
                "artifact_proposal_record": {
                    "id": "apr-4",
                    "artifact_id": "art-4",
                    "change_id": "chg-4",
                    "source_run_id": "run-4",
                    "status": "rejected",
                    "summary": "rejected-1",
                }
            },
        ),
    ]

    accepted = accepted_artifact_proposals(events)
    proposed = proposed_artifact_proposals(events)
    rejected = rejected_artifact_proposals(events)

    assert [record.id for record in accepted] == ["apr-1", "apr-3"]
    assert [record.id for record in proposed] == ["apr-2"]
    assert [record.id for record in rejected] == ["apr-4"]


def test_artifact_proposal_helpers_do_not_mutate_inputs() -> None:
    payload = {
        "id": "apr-1",
        "artifact_id": "art-1",
        "change_id": "chg-1",
        "source_run_id": "run-1",
        "status": "accepted",
        "summary": "accepted",
        "metadata": {"k": "v"},
    }
    events = [
        Event(
            id="e1",
            type="artifact_proposal_recorded",
            payload={"artifact_proposal_record": dict(payload)},
        )
    ]
    before = events[0].model_dump(mode="json")

    records = artifact_proposal_records(events)
    _ = accepted_artifact_proposals(events)
    _ = proposed_artifact_proposals(events)
    _ = rejected_artifact_proposals(events)

    assert len(records) == 1
    assert isinstance(records[0], ArtifactProposalRecord)
    assert events[0].model_dump(mode="json") == before
