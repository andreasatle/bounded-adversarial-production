import pytest
from pydantic import ValidationError

from baps.game_executor import GameExecutionResult
from baps.integration import (
    FakeIntegrator,
    IntegrationDecision,
    StateChange,
    derive_state_update_from_decision,
)
from baps.state import StateUpdateProposal


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


def test_derive_state_update_from_decision_returns_none_for_rejected_decision() -> None:
    decision = IntegrationDecision(
        id="decision-1",
        state_change=StateChange(
            id="artifact-1",
            execution_result_id="result-1",
            summary="Summary 1",
            applied_delta="Delta 1",
            risks=[],
        ),
        accepted=False,
        rationale="Rejected",
    )

    assert derive_state_update_from_decision(decision) is None


def test_derive_state_update_from_decision_returns_proposal_for_accepted_decision() -> None:
    decision = IntegrationDecision(
        id="decision-1",
        state_change=StateChange(
            id="artifact-1",
            execution_result_id="result-1",
            summary="Summary 1",
            applied_delta="Delta 1",
            risks=[],
        ),
        accepted=True,
        rationale="Accepted",
    )

    proposal = derive_state_update_from_decision(decision)

    assert isinstance(proposal, StateUpdateProposal)


def test_derive_state_update_from_decision_proposal_id_is_deterministic_from_decision_id() -> None:
    decision = IntegrationDecision(
        id="decision-123",
        state_change=StateChange(
            id="artifact-1",
            execution_result_id="result-1",
            summary="Summary 1",
            applied_delta="Delta 1",
            risks=[],
        ),
        accepted=True,
        rationale="Accepted",
    )

    first = derive_state_update_from_decision(decision)
    second = derive_state_update_from_decision(decision)

    assert first is not None
    assert second is not None
    assert first.id == "state-update:decision-123"
    assert first.id == second.id


def test_derive_state_update_from_decision_target_artifact_id_from_state_change_id() -> None:
    decision = IntegrationDecision(
        id="decision-1",
        state_change=StateChange(
            id="artifact-target",
            execution_result_id="result-1",
            summary="Summary 1",
            applied_delta="Delta 1",
            risks=[],
        ),
        accepted=True,
        rationale="Accepted",
    )

    proposal = derive_state_update_from_decision(decision)

    assert proposal is not None
    assert proposal.target.artifact_id == "artifact-target"


def test_derive_state_update_from_decision_payload_includes_required_fields() -> None:
    decision = IntegrationDecision(
        id="decision-1",
        state_change=StateChange(
            id="artifact-1",
            execution_result_id="result-123",
            summary="Summary 1",
            applied_delta="Delta 123",
            risks=[],
        ),
        accepted=True,
        rationale="Accepted",
    )

    proposal = derive_state_update_from_decision(decision)

    assert proposal is not None
    assert proposal.payload == {
        "applied_delta": "Delta 123",
        "execution_result_id": "result-123",
        "integration_decision_id": "decision-1",
    }


def test_derive_state_update_from_decision_does_not_mutate_input_decision() -> None:
    decision = IntegrationDecision(
        id="decision-1",
        state_change=StateChange(
            id="artifact-1",
            execution_result_id="result-1",
            summary="Summary 1",
            applied_delta="Delta 1",
            risks=["risk-a"],
        ),
        accepted=True,
        rationale="Accepted",
    )
    before = decision.model_dump(mode="json")

    _ = derive_state_update_from_decision(decision)

    after = decision.model_dump(mode="json")
    assert after == before
