from __future__ import annotations

from pydantic import BaseModel

from baps.blackboard import Blackboard
from baps.game_executor import GameExecutionResult, GameExecutor
from baps.integration import IntegrationDecision, Integrator, apply_decision_update
from baps.schemas import Event
from baps.state import State
from baps.state_progressor import StateProgressionProposal, StateProgressor, StateProgressorInput
from baps.state_service import StateService


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


def record_loop_result(blackboard: Blackboard, result: LoopResult) -> None:
    blackboard.append(
        Event(
            id=(
                f"loop:{result.proposal.id}:{result.execution_result.id}:"
                f"{result.decision.id}:state_progression_proposed"
            ),
            type="state_progression_proposed",
            payload={"proposal": result.proposal.model_dump(mode="json")},
        )
    )
    blackboard.append(
        Event(
            id=(
                f"loop:{result.proposal.id}:{result.execution_result.id}:"
                f"{result.decision.id}:game_executed"
            ),
            type="game_executed",
            payload={"execution_result": result.execution_result.model_dump(mode="json")},
        )
    )
    blackboard.append(
        Event(
            id=(
                f"loop:{result.proposal.id}:{result.execution_result.id}:"
                f"{result.decision.id}:integration_decided"
            ),
            type="integration_decided",
            payload={"decision": result.decision.model_dump(mode="json")},
        )
    )


def apply_loop_decision_update(service: StateService, result: LoopResult) -> State | None:
    return apply_decision_update(service, result.decision)
