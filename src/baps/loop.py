from __future__ import annotations

from pydantic import BaseModel

from baps.game_executor import GameExecutionResult, GameExecutor
from baps.integration import IntegrationDecision, Integrator
from baps.state_progressor import StateProgressionProposal, StateProgressor, StateProgressorInput


class LoopResult(BaseModel):
    proposal: StateProgressionProposal
    execution_result: GameExecutionResult
    decision: IntegrationDecision


def run_loop(
    progressor: StateProgressor,
    executor: GameExecutor,
    integrator: Integrator,
    input: StateProgressorInput,
) -> LoopResult:
    proposal = progressor.progress(input)
    execution_result = executor.execute(proposal.game_proposal)
    decision = integrator.integrate(execution_result)
    return LoopResult(
        proposal=proposal,
        execution_result=execution_result,
        decision=decision,
    )
