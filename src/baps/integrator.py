from __future__ import annotations

from baps.blackboard import Blackboard
from baps.schemas import GameResponse, IntegrationDecision


class Integrator:
    def integrate(self, response: GameResponse) -> IntegrationDecision:
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


def integrate_response(
    response: GameResponse,
    blackboard: Blackboard,
    integrator: Integrator | None = None,
) -> IntegrationDecision:
    active_integrator = integrator if integrator is not None else Integrator()
    decision = active_integrator.integrate(response)
    blackboard.append_integration_decision(decision)
    return decision
