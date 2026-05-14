from pathlib import Path

from baps.blackboard import Blackboard
from baps.integrator import Integrator, integrate_response
from baps.schemas import Decision, GameResponse, IntegrationDecision


def _make_response(*, run_id: str, terminal_outcome: str, integration_recommendation: str) -> GameResponse:
    return GameResponse(
        game_id="game-1",
        run_id=run_id,
        rounds_played=1,
        max_rounds=1,
        final_decision=Decision(game_id="game-1", decision="accept", rationale="done"),
        terminal_reason="accepted",
        terminal_outcome=terminal_outcome,
        integration_recommendation=integration_recommendation,
        final_blue_summary="blue summary",
        final_red_claim="red claim",
    )


def test_integrator_accepts_when_locally_accepted_and_recommended() -> None:
    integrator = Integrator()
    response = _make_response(
        run_id="run-1",
        terminal_outcome="accepted_locally",
        integration_recommendation="integration_recommended",
    )

    decision = integrator.integrate(response)

    assert decision.outcome == "accepted"
    assert decision.target_kind == "accomplishment"
    assert decision.run_id == "run-1"
    assert decision.summary
    assert decision.rationale


def test_integrator_defers_when_rejected_locally() -> None:
    integrator = Integrator()
    response = _make_response(
        run_id="run-2",
        terminal_outcome="rejected_locally",
        integration_recommendation="do_not_integrate",
    )

    decision = integrator.integrate(response)

    assert decision.outcome == "deferred"
    assert decision.target_kind == "accomplishment"
    assert decision.run_id == "run-2"
    assert decision.summary
    assert decision.rationale


def test_integrator_defers_when_revision_budget_exhausted() -> None:
    integrator = Integrator()
    response = _make_response(
        run_id="run-3",
        terminal_outcome="revision_budget_exhausted",
        integration_recommendation="do_not_integrate",
    )

    decision = integrator.integrate(response)

    assert decision.outcome == "deferred"
    assert decision.target_kind == "accomplishment"
    assert decision.run_id == "run-3"
    assert decision.summary
    assert decision.rationale


def test_integrate_response_returns_integration_decision_and_appends_event(tmp_path: Path) -> None:
    board = Blackboard(tmp_path / "board.jsonl")
    response = _make_response(
        run_id="run-4",
        terminal_outcome="accepted_locally",
        integration_recommendation="integration_recommended",
    )

    decision = integrate_response(response=response, blackboard=board)

    assert isinstance(decision, IntegrationDecision)
    events = board.query("integration_decision_recorded")
    assert len(events) == 1
    assert events[0].payload["integration_decision"] == decision.model_dump(mode="json")


def test_integrate_response_uses_injected_integrator(tmp_path: Path) -> None:
    class StubIntegrator(Integrator):
        def integrate(self, response: GameResponse) -> IntegrationDecision:
            return IntegrationDecision(
                id="stub-id",
                run_id=response.run_id,
                outcome="deferred",
                target_kind="accomplishment",
                summary="stub summary",
                rationale="stub rationale",
            )

    board = Blackboard(tmp_path / "board.jsonl")
    response = _make_response(
        run_id="run-5",
        terminal_outcome="accepted_locally",
        integration_recommendation="integration_recommended",
    )

    decision = integrate_response(response=response, blackboard=board, integrator=StubIntegrator())

    assert decision.id == "stub-id"
    events = board.query("integration_decision_recorded")
    assert len(events) == 1
    assert events[0].payload["integration_decision"]["id"] == "stub-id"
