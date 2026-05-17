from __future__ import annotations

from enum import Enum
from typing import Protocol

from pydantic import BaseModel, Field, field_validator

from baps.game_executor import GameExecutionResult
from baps.state import State, StateUpdateProposal, StateUpdateTarget, fingerprint_state
from baps.state_service import StateService


def _require_non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("must be a non-empty string")
    return value


class StateChange(BaseModel):
    id: str
    execution_result_id: str
    summary: str
    applied_delta: str
    risks: list[str] = Field(default_factory=list)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_execution_result_id = field_validator("execution_result_id")(_require_non_empty)
    _validate_summary = field_validator("summary")(_require_non_empty)
    _validate_applied_delta = field_validator("applied_delta")(_require_non_empty)


class IntegrationSatisfaction(str, Enum):
    NONE = "none"
    PARTIAL = "partial"
    FULL = "full"


class IntegrationDecision(BaseModel):
    id: str
    state_change: StateChange
    accepted: bool
    satisfaction: IntegrationSatisfaction = IntegrationSatisfaction.FULL
    rationale: str

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_rationale = field_validator("rationale")(_require_non_empty)


class Integrator(Protocol):
    def integrate(self, result: GameExecutionResult) -> IntegrationDecision:
        ...


class FakeIntegrator:
    def __init__(
        self,
        accepted: bool,
        rationale: str,
        applied_delta: str,
        satisfaction: IntegrationSatisfaction = IntegrationSatisfaction.FULL,
    ):
        self.accepted = accepted
        self.rationale = _require_non_empty(rationale)
        self.applied_delta = _require_non_empty(applied_delta)
        self.satisfaction = satisfaction

    def integrate(self, result: GameExecutionResult) -> IntegrationDecision:
        state_change = StateChange(
            id=f"state-change:{result.id}",
            execution_result_id=result.id,
            summary=result.summary,
            applied_delta=self.applied_delta,
            risks=list(result.risks),
        )
        return IntegrationDecision(
            id=f"integration-decision:{result.id}",
            state_change=state_change,
            accepted=self.accepted,
            satisfaction=self.satisfaction,
            rationale=self.rationale,
        )


def derive_state_update_from_decision(
    decision: IntegrationDecision,
) -> StateUpdateProposal | None:
    if not decision.accepted:
        return None

    return StateUpdateProposal(
        id=f"state-update:{decision.id}",
        target=StateUpdateTarget(artifact_id=decision.state_change.id),
        summary=decision.state_change.summary,
        base_state_fingerprint=None,
        payload={
            "applied_delta": decision.state_change.applied_delta,
            "execution_result_id": decision.state_change.execution_result_id,
            "integration_decision_id": decision.id,
        },
    )


def apply_decision_update(service: StateService, decision: IntegrationDecision) -> State | None:
    proposal = derive_state_update_from_decision(decision)
    if proposal is None:
        return None
    return service.apply_update(proposal)


def derive_state_update_from_decision_for_state(
    state: State,
    decision: IntegrationDecision,
) -> StateUpdateProposal | None:
    proposal = derive_state_update_from_decision(decision)
    if proposal is None:
        return None

    return StateUpdateProposal(
        id=proposal.id,
        target=proposal.target.model_copy(deep=True),
        summary=proposal.summary,
        payload=dict(proposal.payload),
        base_state_fingerprint=fingerprint_state(state),
    )
