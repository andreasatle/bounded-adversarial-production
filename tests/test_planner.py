from baps.planner import DefaultPlanner
from baps.schemas import ProjectedState, UnresolvedDiscrepancy


def _discrepancy(
    *,
    id: str,
    severity: str,
    status: str = "open",
    related_artifact_id: str | None = None,
    related_artifact_version: str | None = None,
) -> UnresolvedDiscrepancy:
    return UnresolvedDiscrepancy(
        id=id,
        summary=f"summary-{id}",
        kind="unresolved_finding",
        severity=severity,
        status=status,
        source_event_id=f"event-{id}",
        related_artifact_id=related_artifact_id,
        related_artifact_version=related_artifact_version,
    )


def test_default_planner_prioritizes_high_severity_open_discrepancy() -> None:
    planner = DefaultPlanner()
    state = ProjectedState(
        unresolved_discrepancies=[
            _discrepancy(id="d1", severity="medium"),
            _discrepancy(id="d2", severity="high"),
            _discrepancy(id="d3", severity="low"),
        ]
    )

    request = planner.plan_next_game(state, "Keep project goals coherent")

    assert request.target_kind == "discrepancy"
    assert "discrepancy_id=d2" in request.target_ref


def test_default_planner_prioritizes_open_discrepancies_over_maintenance() -> None:
    planner = DefaultPlanner()
    state = ProjectedState(
        unresolved_discrepancies=[
            _discrepancy(id="d1", severity="medium", status="resolved"),
            _discrepancy(id="d2", severity="low", status="open"),
        ]
    )

    request = planner.plan_next_game(state, "Keep project goals coherent")

    assert request.target_kind == "discrepancy"
    assert "discrepancy_id=d2" in request.target_ref


def test_default_planner_produces_maintenance_game_when_no_open_discrepancies() -> None:
    planner = DefaultPlanner()
    state = ProjectedState(
        unresolved_discrepancies=[
            _discrepancy(id="d1", severity="high", status="resolved"),
            _discrepancy(id="d2", severity="medium", status="superseded"),
        ]
    )

    request = planner.plan_next_game(state, "Keep project goals coherent")

    assert request.target_kind == "maintenance"
    assert request.target_ref == "project-maintenance"


def test_default_planner_is_deterministic_for_discrepancy_ordering() -> None:
    planner = DefaultPlanner()
    state = ProjectedState(
        unresolved_discrepancies=[
            _discrepancy(id="d1", severity="high"),
            _discrepancy(id="d2", severity="high"),
        ]
    )

    request = planner.plan_next_game(state, "Keep project goals coherent")

    assert "discrepancy_id=d1" in request.target_ref


def test_default_planner_includes_artifact_linkage_when_present() -> None:
    planner = DefaultPlanner()
    state = ProjectedState(
        unresolved_discrepancies=[
            _discrepancy(
                id="d1",
                severity="high",
                related_artifact_id="artifact-1",
                related_artifact_version="v7",
            )
        ]
    )

    request = planner.plan_next_game(state, "Keep project goals coherent")

    assert request.target_kind == "discrepancy"
    assert "discrepancy_id=d1" in request.target_ref
    assert "artifact_id=artifact-1" in request.target_ref
    assert "artifact_version=v7" in request.target_ref
