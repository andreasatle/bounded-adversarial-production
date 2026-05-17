from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from baps.blackboard import Blackboard
from baps.game_executor import GameExecutionResult, GameExecutor
from baps.integration import (
    IntegrationDecision,
    Integrator,
    apply_decision_update,
    derive_state_update_from_decision_for_state,
)
from baps.northstar_projection import (
    NorthStarProjectionInput,
    NorthStarProjectionItem,
    NorthStarView,
    ProjectionPolicy,
    render_northstar_view,
)
from baps.schemas import Event
from baps.state import State, StateUpdateProposal, find_state_artifact
from baps.state_progressor import StateProgressionProposal, StateProgressor, StateProgressorInput
from baps.state_service import StateService


class LoopResult(BaseModel):
    proposal: StateProgressionProposal
    execution_result: GameExecutionResult
    decision: IntegrationDecision


@dataclass
class StateLoopRunResult:
    loop_result: LoopResult
    northstar_view: NorthStarView
    state_update_proposal: StateUpdateProposal | None
    updated_state: State | None


def _build_northstar_view_from_state(state: State) -> NorthStarView:
    project_items: list[NorthStarProjectionItem] = []
    for artifact in state.northstar.artifacts:
        project_items.append(
            NorthStarProjectionItem(
                id=f"northstar:{artifact.id}",
                content=f"northstar artifact {artifact.id} ({artifact.kind})",
                source="state.northstar.artifacts",
                authority="project",
                status="accepted",
                projection_policy=ProjectionPolicy.VERBATIM,
            )
        )
    for artifact in state.artifacts:
        project_items.append(
            NorthStarProjectionItem(
                id=f"state:{artifact.id}",
                content=f"state artifact {artifact.id} ({artifact.kind})",
                source="state.artifacts",
                authority="project",
                status="accepted",
                projection_policy=ProjectionPolicy.VERBATIM,
            )
        )

    return render_northstar_view(
        NorthStarProjectionInput(
            project_state=tuple(project_items),
        )
    )


def run_state_loop_once(
    service: StateService,
    progressor: StateProgressor,
    executor: GameExecutor,
    integrator: Integrator,
    runtime_objective: str,
) -> StateLoopRunResult:
    current_state = service.load_state()
    northstar_view = _build_northstar_view_from_state(current_state)
    progress_input = StateProgressorInput(
        id=f"state-loop:{northstar_view.input_fingerprint}",
        northstar_view=northstar_view,
        runtime_objective=runtime_objective,
    )

    loop_result = run_loop(
        progressor=progressor,
        executor=executor,
        integrator=integrator,
        input=progress_input,
    )
    proposal = derive_state_update_from_decision_for_state(current_state, loop_result.decision)
    updated_state = None
    if proposal is not None:
        proposal_for_apply = proposal
        if "operation" not in proposal.payload:
            target_artifact = find_state_artifact(current_state, proposal.target.artifact_id)
            proposal_for_apply = StateUpdateProposal(
                id=proposal.id,
                target=proposal.target.model_copy(deep=True),
                summary=proposal.summary,
                base_state_fingerprint=proposal.base_state_fingerprint,
                payload={
                    **proposal.payload,
                    "operation": "replace_artifact",
                    "artifact": {
                        "id": target_artifact.id,
                        "kind": target_artifact.kind,
                    },
                },
            )
        updated_state = service.apply_update(proposal_for_apply)

    return StateLoopRunResult(
        loop_result=loop_result,
        northstar_view=northstar_view,
        state_update_proposal=proposal,
        updated_state=updated_state,
    )


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
