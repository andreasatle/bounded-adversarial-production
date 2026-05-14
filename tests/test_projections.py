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


def test_build_projected_state_accepted_completion_produces_accomplishment() -> None:
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
    assert len(projected.accepted_accomplishments) == 1
    accomplishment = projected.accepted_accomplishments[0]
    assert accomplishment.id == "run-1"
    assert accomplishment.source_run_id == "run-1"
    assert accomplishment.summary == "accepted outcome rationale"


def test_build_projected_state_rejected_completion_does_not_produce_accomplishment() -> None:
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
                },
            )
        ]
    )
    assert projected.accepted_accomplishments == []


def test_build_projected_state_unresolved_completion_does_not_produce_accomplishment() -> None:
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
                },
            )
        ]
    )
    assert projected.accepted_accomplishments == []


def test_build_projected_state_duplicate_successful_completions_do_not_duplicate_accomplishment() -> None:
    projected = build_projected_state(
        [
            Event(
                id="g1:run-1:game_completed-a",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "accepted_locally",
                    "integration_recommendation": "integration_recommended",
                    "state": {"final_decision": {"rationale": "accepted rationale"}},
                },
            ),
            Event(
                id="g1:run-1:game_completed-b",
                type="game_completed",
                payload={
                    "game_id": "g1",
                    "run_id": "run-1",
                    "terminal_outcome": "accepted_locally",
                    "integration_recommendation": "integration_recommended",
                    "state": {"final_decision": {"rationale": "accepted rationale duplicate"}},
                },
            ),
        ]
    )
    assert len(projected.accepted_accomplishments) == 1
    assert projected.accepted_accomplishments[0].id == "run-1"
