import pytest

from baps.models import FakeModelClient
from baps.planner import DefaultPlanner, LLMPlanner
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


def test_llm_planner_returns_game_request_from_valid_json() -> None:
    model = FakeModelClient(
        responses=[
            '{"game_type":"documentation-refinement","subject":"S","goal":"G","target_kind":"discrepancy","target_ref":"d1","state_source_ids":["architecture"]}'
        ]
    )
    planner = LLMPlanner(model_client=model)

    request = planner.plan_next_game(ProjectedState(), "North star")

    assert request.game_type == "documentation-refinement"
    assert request.subject == "S"
    assert request.goal == "G"
    assert len(model.prompts) == 1


def test_llm_planner_prompt_includes_north_star_and_projected_state_summary() -> None:
    model = FakeModelClient(
        responses=[
            '{"game_type":"documentation-refinement","subject":"S","goal":"G","target_kind":"maintenance","target_ref":"m1"}'
        ]
    )
    state = ProjectedState(
        unresolved_discrepancies=[_discrepancy(id="d1", severity="high")],
        accepted_accomplishments=[],
        accepted_architecture=[],
        accepted_capabilities=[],
        active_games=[],
    )
    planner = LLMPlanner(model_client=model)

    _ = planner.plan_next_game(state, "Preserve project identity")

    prompt = model.prompts[0]
    assert "NORTH_STAR: Preserve project identity" in prompt
    assert "OPEN_DISCREPANCIES_COUNT: 1" in prompt
    assert "ACCEPTED_ACCOMPLISHMENTS_COUNT: 0" in prompt
    assert "ACCEPTED_ARCHITECTURE_COUNT: 0" in prompt
    assert "ACCEPTED_CAPABILITIES_COUNT: 0" in prompt
    assert "ACTIVE_GAMES_COUNT: 0" in prompt


def test_llm_planner_malformed_json_uses_fallback_when_provided() -> None:
    model = FakeModelClient(responses=["not json"])
    fallback = DefaultPlanner()
    state = ProjectedState(
        unresolved_discrepancies=[_discrepancy(id="d1", severity="high")]
    )
    planner = LLMPlanner(model_client=model, fallback_planner=fallback)

    request = planner.plan_next_game(state, "North star")

    assert request.target_kind == "discrepancy"
    assert "discrepancy_id=d1" in request.target_ref
    assert len(model.prompts) == 1


def test_llm_planner_invalid_game_request_json_uses_fallback_when_provided() -> None:
    model = FakeModelClient(
        responses=[
            '{"game_type":"documentation-refinement","subject":"S","goal":"","target_kind":"discrepancy","target_ref":"d1"}'
        ]
    )
    fallback = DefaultPlanner()
    state = ProjectedState(
        unresolved_discrepancies=[_discrepancy(id="d2", severity="medium")]
    )
    planner = LLMPlanner(model_client=model, fallback_planner=fallback)

    request = planner.plan_next_game(state, "North star")

    assert request.target_kind == "discrepancy"
    assert "discrepancy_id=d2" in request.target_ref
    assert len(model.prompts) == 1


def test_llm_planner_malformed_output_raises_without_fallback() -> None:
    model = FakeModelClient(responses=["not json"])
    planner = LLMPlanner(model_client=model)

    with pytest.raises(ValueError, match="failed to parse valid GameRequest JSON"):
        planner.plan_next_game(ProjectedState(), "North star")
    assert len(model.prompts) == 1


def test_default_planner_rejects_empty_north_star() -> None:
    planner = DefaultPlanner()
    with pytest.raises(ValueError, match="north_star must be a non-empty string"):
        planner.plan_next_game(ProjectedState(), "   ")


def test_llm_planner_rejects_empty_north_star_before_model_call() -> None:
    model = FakeModelClient(
        responses=[
            '{"game_type":"documentation-refinement","subject":"S","goal":"G","target_kind":"maintenance","target_ref":"m1"}'
        ]
    )
    planner = LLMPlanner(model_client=model)

    with pytest.raises(ValueError, match="north_star must be a non-empty string"):
        planner.plan_next_game(ProjectedState(), "   ")
    assert model.prompts == []


def test_llm_planner_can_return_valid_but_ungrounded_request_when_no_fallback() -> None:
    model = FakeModelClient(
        responses=[
            '{"game_type":"documentation-refinement","subject":"Unrelated subject","goal":"Unrelated goal","target_kind":"maintenance","target_ref":"invented-ref"}'
        ]
    )
    planner = LLMPlanner(model_client=model)
    state = ProjectedState(
        unresolved_discrepancies=[_discrepancy(id="d1", severity="high")],
    )

    request = planner.plan_next_game(state, "Preserve project identity")

    assert request.target_kind == "maintenance"
    assert request.target_ref == "invented-ref"
