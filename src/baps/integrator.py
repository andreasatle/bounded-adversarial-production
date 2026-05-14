from __future__ import annotations

from typing import Protocol

from baps.blackboard import Blackboard
from baps.schemas import GameResponse, IntegrationDecision


class IntegrationPolicy(Protocol):
    def decide(self, response: GameResponse) -> IntegrationDecision: ...


class MultiCandidateIntegrationPolicy(Protocol):
    def decide_many(self, responses: list[GameResponse]) -> list[IntegrationDecision]: ...


class DefaultIntegrationPolicy:
    def decide(self, response: GameResponse) -> IntegrationDecision:
        accepted = (
            response.terminal_outcome == "accepted_locally"
            and response.integration_recommendation == "integration_recommended"
        )
        outcome = "accepted" if accepted else "deferred"

        return IntegrationDecision(
            id=f"integration:{response.run_id}:accomplishment",
            run_id=response.run_id,
            outcome=outcome,
            target_kind="accomplishment",
            summary=f"Integration outcome for run {response.run_id}: {outcome}",
            rationale=(
                "Accepted by deterministic integration policy based on local acceptance and "
                "integration recommendation."
                if accepted
                else (
                    "Deferred by deterministic integration policy because local runtime "
                    "semantics did not meet durable acceptance criteria."
                )
            ),
            metadata={
                "game_id": response.game_id,
                "terminal_outcome": response.terminal_outcome,
                "integration_recommendation": response.integration_recommendation,
                "final_decision": response.final_decision.decision,
            },
        )


class Integrator:
    def __init__(self, policy: IntegrationPolicy | None = None):
        self.policy = policy if policy is not None else DefaultIntegrationPolicy()

    def integrate(self, response: GameResponse) -> IntegrationDecision:
        return self.policy.decide(response)


class DefaultMultiCandidateIntegrationPolicy:
    def __init__(self, base_policy: IntegrationPolicy | None = None):
        self.base_policy = base_policy if base_policy is not None else DefaultIntegrationPolicy()

    def decide_many(self, responses: list[GameResponse]) -> list[IntegrationDecision]:
        decisions = [self.base_policy.decide(response) for response in responses]
        accepted_seen = False
        first_accepted_run_id: str | None = None
        for decision in decisions:
            if decision.outcome != "accepted":
                continue
            if not accepted_seen:
                accepted_seen = True
                first_accepted_run_id = decision.run_id
                continue
            decision.outcome = "deferred"
            decision.summary = f"Integration outcome for run {decision.run_id}: deferred"
            decision.rationale = (
                "Deferred by deterministic multi-candidate policy because an earlier accepted "
                "candidate already claimed acceptance."
            )
            decision.metadata["deferred_reason"] = "competing_candidate_already_accepted"
            decision.metadata["accepted_competitor_run_id"] = first_accepted_run_id
        return decisions


def integrate_response(
    response: GameResponse,
    blackboard: Blackboard,
    integrator: Integrator | None = None,
) -> IntegrationDecision:
    active_integrator = integrator if integrator is not None else Integrator()
    decision = active_integrator.integrate(response)
    blackboard.append_integration_decision(decision)
    return decision


def integrate_many(
    responses: list[GameResponse],
    blackboard: Blackboard,
    policy: MultiCandidateIntegrationPolicy | None = None,
) -> list[IntegrationDecision]:
    active_policy = policy if policy is not None else DefaultMultiCandidateIntegrationPolicy()
    decisions = active_policy.decide_many(responses)
    for decision in decisions:
        blackboard.append_integration_decision(decision)
    return decisions
