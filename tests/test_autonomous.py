from pathlib import Path

import pytest

from baps.autonomous import run_autonomous_steps, run_one_autonomous_step
from baps.blackboard import Blackboard
from baps.schemas import (
    AutonomousStepResult,
    Decision,
    GameRequest,
    GameResponse,
    PlannerGroundingMetadata,
    ProjectedState,
    UnresolvedDiscrepancy,
)


def _response() -> GameResponse:
    return GameResponse(
        game_id="play-game-001",
        run_id="run-1",
        rounds_played=1,
        max_rounds=1,
        final_decision=Decision(game_id="play-game-001", decision="accept", rationale="ok"),
        terminal_reason="accepted",
        terminal_outcome="accepted_locally",
        integration_recommendation="integration_recommended",
        final_blue_summary="blue summary",
        final_red_claim="red claim",
    )


def _request() -> GameRequest:
    return GameRequest(
        game_type="documentation-refinement",
        subject="subject",
        goal="goal",
        target_kind="documentation",
        target_ref="README.md",
    )


def test_run_one_autonomous_step_builds_projected_state_before_planning_and_passes_to_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    planned_request = _request()
    expected_response = _response()
    expected_projected_state = ProjectedState(metadata={"event_count": 1})
    calls: list[str] = []

    def _stub_build_projected_state_from_blackboard(received_blackboard: Blackboard) -> ProjectedState:
        assert received_blackboard is board
        calls.append("build")
        return expected_projected_state

    class StubPlanner:
        def __init__(self) -> None:
            self.calls = 0

        def plan_next_game(self, projected_state: ProjectedState, north_star: str) -> GameRequest:
            self.calls += 1
            calls.append("plan")
            assert projected_state is expected_projected_state
            assert north_star == "Protect project identity"
            return planned_request

    class StubGameService:
        def __init__(self) -> None:
            self.calls = 0

        def play(self, request: GameRequest) -> GameResponse:
            self.calls += 1
            calls.append("play")
            assert request == planned_request
            return expected_response

    monkeypatch.setattr(
        "baps.autonomous.build_projected_state_from_blackboard",
        _stub_build_projected_state_from_blackboard,
    )

    planner = StubPlanner()
    service = StubGameService()
    result = run_one_autonomous_step(
        north_star="Protect project identity",
        blackboard=board,
        planner=planner,
        game_service=service,
    )

    assert result.response == expected_response
    assert result.planner_grounding is None
    assert planner.calls == 1
    assert service.calls == 1
    assert calls == ["build", "plan", "play"]


def test_run_one_autonomous_step_rejects_empty_north_star(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "events.jsonl")

    class StubPlanner:
        def plan_next_game(self, projected_state: ProjectedState, north_star: str) -> GameRequest:
            raise AssertionError("should not be called")

    class StubGameService:
        def play(self, request: GameRequest) -> GameResponse:
            raise AssertionError("should not be called")

    with pytest.raises(ValueError, match="north_star must be a non-empty string"):
        run_one_autonomous_step(
            north_star="   ",
            blackboard=board,
            planner=StubPlanner(),
            game_service=StubGameService(),
        )


def test_run_autonomous_steps_returns_max_steps_responses_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    call_index = {"value": 0}

    def _stub_run_one_autonomous_step(
        north_star: str,
        blackboard: Blackboard,
        planner: object,
        game_service: object,
    ) -> AutonomousStepResult:
        assert north_star == "Protect project identity"
        assert blackboard is board
        call_index["value"] += 1
        idx = call_index["value"]
        return AutonomousStepResult(
            response=GameResponse(
                game_id="play-game-001",
                run_id=f"run-{idx}",
                rounds_played=1,
                max_rounds=1,
                final_decision=Decision(game_id="play-game-001", decision="accept", rationale=f"ok-{idx}"),
                terminal_reason="accepted",
                terminal_outcome="accepted_locally",
                integration_recommendation="integration_recommended",
                final_blue_summary=f"blue-{idx}",
                final_red_claim=f"red-{idx}",
            )
        )

    monkeypatch.setattr(
        "baps.autonomous.run_one_autonomous_step",
        _stub_run_one_autonomous_step,
    )

    responses = run_autonomous_steps(
        north_star="Protect project identity",
        blackboard=board,
        planner=object(),  # not used by stubbed helper
        game_service=object(),  # not used by stubbed helper
        max_steps=3,
    )

    assert len(responses) == 3
    assert [result.response.run_id for result in responses] == ["run-1", "run-2", "run-3"]


def test_run_autonomous_steps_calls_planner_and_service_once_per_step_and_rebuilds_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    build_calls = {"count": 0}

    def _stub_build_projected_state_from_blackboard(received_blackboard: Blackboard) -> ProjectedState:
        assert received_blackboard is board
        build_calls["count"] += 1
        return ProjectedState(metadata={"build_index": build_calls["count"]})

    class StubPlanner:
        def __init__(self) -> None:
            self.calls = 0
            self.received_build_indexes: list[int] = []

        def plan_next_game(self, projected_state: ProjectedState, north_star: str) -> GameRequest:
            self.calls += 1
            assert north_star == "Protect project identity"
            self.received_build_indexes.append(projected_state.metadata["build_index"])
            return _request()

    class StubGameService:
        def __init__(self) -> None:
            self.calls = 0

        def play(self, request: GameRequest) -> GameResponse:
            self.calls += 1
            assert request == _request()
            idx = self.calls
            return GameResponse(
                game_id="play-game-001",
                run_id=f"run-{idx}",
                rounds_played=1,
                max_rounds=1,
                final_decision=Decision(game_id="play-game-001", decision="accept", rationale="ok"),
                terminal_reason="accepted",
                terminal_outcome="accepted_locally",
                integration_recommendation="integration_recommended",
                final_blue_summary=f"blue-{idx}",
                final_red_claim=f"red-{idx}",
            )

    monkeypatch.setattr(
        "baps.autonomous.build_projected_state_from_blackboard",
        _stub_build_projected_state_from_blackboard,
    )

    planner = StubPlanner()
    service = StubGameService()
    responses = run_autonomous_steps(
        north_star="Protect project identity",
        blackboard=board,
        planner=planner,
        game_service=service,
        max_steps=3,
    )

    assert len(responses) == 3
    assert build_calls["count"] == 3
    assert planner.calls == 3
    assert service.calls == 3
    assert planner.received_build_indexes == [1, 2, 3]
    assert [result.response.run_id for result in responses] == ["run-1", "run-2", "run-3"]


def test_run_autonomous_steps_rejects_invalid_inputs(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "events.jsonl")

    class StubPlanner:
        def plan_next_game(self, projected_state: ProjectedState, north_star: str) -> GameRequest:
            raise AssertionError("should not be called")

    class StubGameService:
        def play(self, request: GameRequest) -> GameResponse:
            raise AssertionError("should not be called")

    with pytest.raises(ValueError, match="north_star must be a non-empty string"):
        run_autonomous_steps(
            north_star="   ",
            blackboard=board,
            planner=StubPlanner(),
            game_service=StubGameService(),
            max_steps=1,
        )

    with pytest.raises(ValueError, match="max_steps must be >= 1"):
        run_autonomous_steps(
            north_star="Protect project identity",
            blackboard=board,
            planner=StubPlanner(),
            game_service=StubGameService(),
            max_steps=0,
        )


def test_run_autonomous_steps_stops_early_when_no_open_discrepancies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    build_calls = {"count": 0}

    def _state_with_open() -> ProjectedState:
        return ProjectedState(
            unresolved_discrepancies=[
                UnresolvedDiscrepancy(
                    id="d1",
                    summary="s1",
                    kind="unresolved_finding",
                    severity="high",
                    status="open",
                    source_event_id="e1",
                )
            ]
        )

    def _state_without_open() -> ProjectedState:
        return ProjectedState(
            unresolved_discrepancies=[
                UnresolvedDiscrepancy(
                    id="d1",
                    summary="s1",
                    kind="unresolved_finding",
                    severity="high",
                    status="resolved",
                    source_event_id="e1",
                )
            ]
        )

    # First pre-step check sees open discrepancy and executes one step.
    # Second pre-step check sees no open discrepancy and stops.
    sequence = [_state_with_open(), _state_with_open(), _state_without_open()]

    def _stub_build_projected_state_from_blackboard(received_blackboard: Blackboard) -> ProjectedState:
        assert received_blackboard is board
        build_calls["count"] += 1
        return sequence.pop(0)

    class StubPlanner:
        def __init__(self) -> None:
            self.calls = 0

        def plan_next_game(self, projected_state: ProjectedState, north_star: str) -> GameRequest:
            self.calls += 1
            return _request()

    class StubGameService:
        def __init__(self) -> None:
            self.calls = 0

        def play(self, request: GameRequest) -> GameResponse:
            self.calls += 1
            return _response()

    monkeypatch.setattr(
        "baps.autonomous.build_projected_state_from_blackboard",
        _stub_build_projected_state_from_blackboard,
    )

    planner = StubPlanner()
    service = StubGameService()
    responses = run_autonomous_steps(
        north_star="Protect project identity",
        blackboard=board,
        planner=planner,
        game_service=service,
        max_steps=5,
        stop_when_no_open_discrepancies=True,
    )

    assert len(responses) == 1
    assert planner.calls == 1
    assert service.calls == 1
    assert build_calls["count"] == 3


def test_run_autonomous_steps_continues_when_open_discrepancies_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    build_calls = {"count": 0}

    def _open_state() -> ProjectedState:
        return ProjectedState(
            unresolved_discrepancies=[
                UnresolvedDiscrepancy(
                    id="d1",
                    summary="s1",
                    kind="unresolved_finding",
                    severity="medium",
                    status="open",
                    source_event_id="e1",
                )
            ]
        )

    def _stub_build_projected_state_from_blackboard(received_blackboard: Blackboard) -> ProjectedState:
        assert received_blackboard is board
        build_calls["count"] += 1
        return _open_state()

    class StubPlanner:
        def __init__(self) -> None:
            self.calls = 0

        def plan_next_game(self, projected_state: ProjectedState, north_star: str) -> GameRequest:
            self.calls += 1
            return _request()

    class StubGameService:
        def __init__(self) -> None:
            self.calls = 0

        def play(self, request: GameRequest) -> GameResponse:
            self.calls += 1
            response = _response()
            response.run_id = f"run-{self.calls}"
            return response

    monkeypatch.setattr(
        "baps.autonomous.build_projected_state_from_blackboard",
        _stub_build_projected_state_from_blackboard,
    )

    planner = StubPlanner()
    service = StubGameService()
    responses = run_autonomous_steps(
        north_star="Protect project identity",
        blackboard=board,
        planner=planner,
        game_service=service,
        max_steps=3,
        stop_when_no_open_discrepancies=True,
    )

    assert len(responses) == 3
    assert [result.response.run_id for result in responses] == ["run-1", "run-2", "run-3"]
    assert planner.calls == 3
    assert service.calls == 3
    assert build_calls["count"] == 6


def test_run_autonomous_steps_stop_flag_false_preserves_default_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    call_index = {"value": 0}

    def _stub_run_one_autonomous_step(
        north_star: str,
        blackboard: Blackboard,
        planner: object,
        game_service: object,
    ) -> AutonomousStepResult:
        assert north_star == "Protect project identity"
        assert blackboard is board
        call_index["value"] += 1
        idx = call_index["value"]
        response = _response()
        response.run_id = f"run-{idx}"
        return AutonomousStepResult(response=response)

    monkeypatch.setattr(
        "baps.autonomous.run_one_autonomous_step",
        _stub_run_one_autonomous_step,
    )

    responses = run_autonomous_steps(
        north_star="Protect project identity",
        blackboard=board,
        planner=object(),
        game_service=object(),
        max_steps=3,
        stop_when_no_open_discrepancies=False,
    )

    assert len(responses) == 3
    assert [result.response.run_id for result in responses] == ["run-1", "run-2", "run-3"]


def test_run_autonomous_steps_stop_flag_true_can_return_zero_steps_when_initially_no_open_discrepancies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = Blackboard(tmp_path / "events.jsonl")

    def _state_without_open() -> ProjectedState:
        return ProjectedState(
            unresolved_discrepancies=[
                UnresolvedDiscrepancy(
                    id="d1",
                    summary="s1",
                    kind="unresolved_finding",
                    severity="high",
                    status="resolved",
                    source_event_id="e1",
                )
            ]
        )

    def _stub_build_projected_state_from_blackboard(received_blackboard: Blackboard) -> ProjectedState:
        assert received_blackboard is board
        return _state_without_open()

    class StubPlanner:
        def plan_next_game(self, projected_state: ProjectedState, north_star: str) -> GameRequest:
            raise AssertionError("should not be called")

    class StubGameService:
        def play(self, request: GameRequest) -> GameResponse:
            raise AssertionError("should not be called")

    monkeypatch.setattr(
        "baps.autonomous.build_projected_state_from_blackboard",
        _stub_build_projected_state_from_blackboard,
    )

    responses = run_autonomous_steps(
        north_star="Protect project identity",
        blackboard=board,
        planner=StubPlanner(),
        game_service=StubGameService(),
        max_steps=3,
        stop_when_no_open_discrepancies=True,
    )

    assert responses == []


def test_run_one_autonomous_step_exposes_grounded_planner_metadata(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "events.jsonl")

    class StubPlanner:
        def plan_next_game(self, projected_state: ProjectedState, north_star: str) -> GameRequest:
            return GameRequest(
                game_type="documentation-refinement",
                subject="s",
                goal="g",
                target_kind="documentation",
                target_ref="README.md",
                planner_grounding=PlannerGroundingMetadata(
                    grounding_status="grounded",
                    grounding_rationale="Grounded in discrepancy d1 and north star.",
                ),
            )

    class StubGameService:
        def play(self, request: GameRequest) -> GameResponse:
            return _response()

    result = run_one_autonomous_step(
        north_star="Protect project identity",
        blackboard=board,
        planner=StubPlanner(),
        game_service=StubGameService(),
    )

    assert result.planner_grounding is not None
    assert result.planner_grounding.grounding_status == "grounded"


def test_run_one_autonomous_step_exposes_weakly_grounded_planner_metadata(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "events.jsonl")

    class StubPlanner:
        def plan_next_game(self, projected_state: ProjectedState, north_star: str) -> GameRequest:
            return GameRequest(
                game_type="documentation-refinement",
                subject="s",
                goal="g",
                target_kind="maintenance",
                target_ref="project-maintenance",
                planner_grounding=PlannerGroundingMetadata(
                    grounding_status="weakly_grounded",
                    grounding_rationale="No open discrepancies; maintenance selected.",
                ),
            )

    class StubGameService:
        def play(self, request: GameRequest) -> GameResponse:
            return _response()

    result = run_one_autonomous_step(
        north_star="Protect project identity",
        blackboard=board,
        planner=StubPlanner(),
        game_service=StubGameService(),
    )

    assert result.planner_grounding is not None
    assert result.planner_grounding.grounding_status == "weakly_grounded"


def test_run_one_autonomous_step_supports_missing_planner_grounding_for_backward_compatibility(
    tmp_path: Path,
) -> None:
    board = Blackboard(tmp_path / "events.jsonl")

    class StubPlanner:
        def plan_next_game(self, projected_state: ProjectedState, north_star: str) -> GameRequest:
            return GameRequest(
                game_type="documentation-refinement",
                subject="s",
                goal="g",
                target_kind="documentation",
                target_ref="README.md",
            )

    class StubGameService:
        def play(self, request: GameRequest) -> GameResponse:
            return _response()

    result = run_one_autonomous_step(
        north_star="Protect project identity",
        blackboard=board,
        planner=StubPlanner(),
        game_service=StubGameService(),
    )

    assert result.planner_grounding is None
