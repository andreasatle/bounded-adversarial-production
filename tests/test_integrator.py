from baps.integrator import Integrator
from baps.schemas import Decision, GameResponse


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
