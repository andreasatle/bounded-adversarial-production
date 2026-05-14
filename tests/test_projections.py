from baps.projections import build_projected_state
from baps.schemas import Event


def test_build_projected_state_empty_events_returns_empty_state() -> None:
    projected = build_projected_state([])
    assert projected.accepted_accomplishments == []
    assert projected.accepted_architecture == []
    assert projected.accepted_capabilities == []
    assert projected.unresolved_discrepancies == []
    assert projected.active_games == []


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
