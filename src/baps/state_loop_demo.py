from __future__ import annotations

import argparse
from pathlib import Path

from baps.game_executor import FakeGameExecutor, GameExecutionResult
from baps.integration import FakeIntegrator
from baps.loop import LoopResult, run_state_loop_once
from baps.northstar_projection import NorthStarView
from baps.state import (
    NorthStar,
    State,
    StateArtifact,
    StateUpdateProposal,
    build_default_state_artifact_registry,
)
from baps.state_progressor import FakeStateProgressor, GameProposal
from baps.state_service import StateService
from baps.state_store import JsonStateStore


def _initial_state() -> State:
    return State(
        northstar=NorthStar(
            artifacts=(
                StateArtifact(id="northstar-1", kind="document"),
                StateArtifact(id="northstar-2", kind="git_repository"),
            )
        ),
        artifacts=(
            StateArtifact(id="state-change:result-1", kind="document"),
            StateArtifact(id="artifact-2", kind="git_repository"),
        ),
    )


def _ensure_state_file(store: JsonStateStore) -> None:
    try:
        store.load()
    except FileNotFoundError:
        store.save(_initial_state())


def run_state_loop_demo(
    *,
    state_path: Path,
    runtime_objective: str,
) -> tuple[LoopResult, NorthStarView, StateUpdateProposal | None, State | None]:
    store = JsonStateStore(state_path)
    _ensure_state_file(store)

    service = StateService(
        store=store,
        registry=build_default_state_artifact_registry(),
    )
    progressor = FakeStateProgressor(
        game_proposal=GameProposal(
            id="game-1",
            title="Deterministic game proposal",
            description="Deterministic one-pass state loop demo proposal.",
            expected_state_delta="Demonstrate one pass from state to state update apply.",
        ),
        rationale="Deterministic progressor rationale",
    )
    executor = FakeGameExecutor(
        result=GameExecutionResult(
            id="result-1",
            game_proposal_id="template",
            status="completed",
            summary="Deterministic execution summary",
            state_delta="Deterministic state delta",
            risks=[],
        )
    )
    integrator = FakeIntegrator(
        accepted=True,
        rationale="Deterministic integration rationale",
        applied_delta="Deterministic applied delta",
    )

    return run_state_loop_once(
        service=service,
        progressor=progressor,
        executor=executor,
        integrator=integrator,
        runtime_objective=runtime_objective,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one deterministic state loop pass.")
    parser.add_argument(
        "--state-path",
        default="state/demo-state.json",
        help="Path to JSON state file (created if missing).",
    )
    parser.add_argument(
        "--runtime-objective",
        default="Run one deterministic state loop pass.",
        help="Runtime objective passed to StateProgressorInput.",
    )
    args = parser.parse_args()

    loop_result, _northstar_view, proposal, updated_state = run_state_loop_demo(
        state_path=Path(args.state_path),
        runtime_objective=args.runtime_objective,
    )

    print(f"loop_proposal_id={loop_result.proposal.id}")
    print(f"loop_execution_result_id={loop_result.execution_result.id}")
    print(f"loop_integration_decision_id={loop_result.decision.id}")
    print(f"update_proposal_produced={proposal is not None}")
    print(f"state_updated={updated_state is not None}")
    print(f"state_path={Path(args.state_path)}")
