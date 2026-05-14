from pathlib import Path

import pytest

from baps.autonomous import run_one_autonomous_step
from baps.blackboard import Blackboard
from baps.schemas import Decision, GameRequest, GameResponse, ProjectedState


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
    response = run_one_autonomous_step(
        north_star="Protect project identity",
        blackboard=board,
        planner=planner,
        game_service=service,
    )

    assert response == expected_response
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
