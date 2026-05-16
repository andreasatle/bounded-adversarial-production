import pytest
from pydantic import ValidationError

from baps.game_executor import GameExecutionResult
from baps.integration import FakeIntegrator, IntegrationDecision, StateChange


@pytest.mark.parametrize(
    "field_name",
    ["id", "execution_result_id", "summary", "applied_delta"],
)
@pytest.mark.parametrize("bad_value", ["", "   ", "\n\t"])
def test_state_change_rejects_empty_required_strings(field_name: str, bad_value: str) -> None:
    payload = {
        "id": "change-1",
        "execution_result_id": "result-1",
        "summary": "Summary",
        "applied_delta": "Applied delta",
    }
    payload[field_name] = bad_value

    with pytest.raises(ValidationError):
        StateChange.model_validate(payload)


@pytest.mark.parametrize("field_name", ["id", "rationale"])
@pytest.mark.parametrize("bad_value", ["", "   ", "\n\t"])
def test_integration_decision_rejects_empty_required_strings(field_name: str, bad_value: str) -> None:
    payload = {
        "id": "decision-1",
        "state_change": {
            "id": "change-1",
            "execution_result_id": "result-1",
            "summary": "Summary",
            "applied_delta": "Applied delta",
            "risks": [],
        },
        "accepted": True,
        "rationale": "Rationale",
    }
    payload[field_name] = bad_value

    with pytest.raises(ValidationError):
        IntegrationDecision.model_validate(payload)


def test_state_change_risks_default_isolated_per_instance() -> None:
    first = StateChange(
        id="change-1",
        execution_result_id="result-1",
        summary="Summary 1",
        applied_delta="Delta 1",
    )
    second = StateChange(
        id="change-2",
        execution_result_id="result-2",
        summary="Summary 2",
        applied_delta="Delta 2",
    )

    first.risks.append("risk-a")
    assert first.risks == ["risk-a"]
    assert second.risks == []


def test_fake_integrator_returns_valid_integration_decision() -> None:
    integrator = FakeIntegrator(
        accepted=True,
        rationale="Deterministic rationale",
        applied_delta="Applied delta",
    )
    result = GameExecutionResult(
        id="result-1",
        game_proposal_id="game-1",
        status="completed",
        summary="Execution summary",
        state_delta="State delta",
        risks=["risk-a"],
    )

    decision = integrator.integrate(result)

    assert isinstance(decision, IntegrationDecision)
    assert decision.accepted is True
    assert decision.rationale == "Deterministic rationale"


def test_fake_integrator_preserves_execution_result_id_linkage() -> None:
    integrator = FakeIntegrator(
        accepted=True,
        rationale="Deterministic rationale",
        applied_delta="Applied delta",
    )
    result = GameExecutionResult(
        id="result-link",
        game_proposal_id="game-1",
        status="completed",
        summary="Execution summary",
        state_delta="State delta",
        risks=[],
    )

    decision = integrator.integrate(result)

    assert decision.state_change.execution_result_id == "result-link"


def test_fake_integrator_repeated_integration_is_deterministic() -> None:
    integrator = FakeIntegrator(
        accepted=False,
        rationale="Deterministic rationale",
        applied_delta="Applied delta",
    )
    result = GameExecutionResult(
        id="result-1",
        game_proposal_id="game-1",
        status="completed",
        summary="Execution summary",
        state_delta="State delta",
        risks=["risk-a"],
    )

    first = integrator.integrate(result)
    second = integrator.integrate(result)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_fake_integrator_does_not_mutate_input_game_execution_result() -> None:
    integrator = FakeIntegrator(
        accepted=True,
        rationale="Deterministic rationale",
        applied_delta="Applied delta",
    )
    result = GameExecutionResult(
        id="result-1",
        game_proposal_id="game-1",
        status="completed",
        summary="Execution summary",
        state_delta="State delta",
        risks=["risk-a"],
    )
    before = result.model_dump(mode="json")

    _ = integrator.integrate(result)

    after = result.model_dump(mode="json")
    assert after == before
