from pathlib import Path

from baps.blackboard import Blackboard
from baps.game_executor import FakeGameExecutor, GameExecutionResult
from baps.integration import FakeIntegrator
from baps.loop import LoopResult, record_loop_result, run_loop
from baps.northstar_projection import NorthStarProjectionInput, NorthStarProjectionItem, render_northstar_view
from baps.state_progressor import FakeStateProgressor, GameProposal, StateProgressionProposal, StateProgressorInput


class _RecordingProgressor:
    def __init__(self, call_log: list[str], proposal: StateProgressionProposal):
        self.call_log = call_log
        self.proposal = proposal

    def progress(self, input: StateProgressorInput) -> StateProgressionProposal:
        self.call_log.append("progress")
        return self.proposal


class _RecordingExecutor:
    def __init__(self, call_log: list[str], result: GameExecutionResult):
        self.call_log = call_log
        self.result = result

    def execute(self, game: GameProposal) -> GameExecutionResult:
        self.call_log.append("execute")
        return self.result


class _RecordingIntegrator:
    def __init__(self, call_log: list[str], decision):
        self.call_log = call_log
        self.decision = decision

    def integrate(self, result: GameExecutionResult):
        self.call_log.append("integrate")
        return self.decision


def _input() -> StateProgressorInput:
    return StateProgressorInput(
        id="input-1",
        northstar_view=render_northstar_view(
            NorthStarProjectionInput(
                project_state=(
                    NorthStarProjectionItem(
                        id="state-item-1",
                        content="Current accepted state",
                        source="state",
                        authority="project",
                        status="accepted",
                    ),
                ),
            )
        ),
        runtime_objective="Improve clarity",
    )


def test_run_loop_executes_components_in_required_order() -> None:
    call_log: list[str] = []

    proposal = StateProgressionProposal(
        id="progression-1",
        input_id="input-1",
        game_proposal=GameProposal(
            id="game-1",
            title="Title",
            description="Description",
            expected_state_delta="Delta",
        ),
        rationale="Rationale",
    )
    execution_result = GameExecutionResult(
        id="result-1",
        game_proposal_id="game-1",
        status="completed",
        summary="Summary",
        state_delta="Delta",
    )
    decision = FakeIntegrator(
        accepted=True,
        rationale="Accepted",
        applied_delta="Applied",
    ).integrate(execution_result)

    progressor = _RecordingProgressor(call_log=call_log, proposal=proposal)
    executor = _RecordingExecutor(call_log=call_log, result=execution_result)
    integrator = _RecordingIntegrator(call_log=call_log, decision=decision)

    _ = run_loop(progressor=progressor, executor=executor, integrator=integrator, input=_input())

    assert call_log == ["progress", "execute", "integrate"]


def test_run_loop_preserves_proposal_result_decision_linkage() -> None:
    progressor = FakeStateProgressor(
        game_proposal=GameProposal(
            id="game-1",
            title="Title",
            description="Description",
            expected_state_delta="Delta",
        ),
        rationale="Progressor rationale",
    )
    executor = FakeGameExecutor(
        result=GameExecutionResult(
            id="result-1",
            game_proposal_id="template",
            status="completed",
            summary="Execution summary",
            state_delta="State delta",
            risks=["risk-a"],
        )
    )
    integrator = FakeIntegrator(
        accepted=True,
        rationale="Integrator rationale",
        applied_delta="Applied delta",
    )

    loop_result = run_loop(
        progressor=progressor,
        executor=executor,
        integrator=integrator,
        input=_input(),
    )

    assert isinstance(loop_result, LoopResult)
    assert loop_result.execution_result.game_proposal_id == loop_result.proposal.game_proposal.id
    assert loop_result.decision.state_change.execution_result_id == loop_result.execution_result.id


def test_run_loop_is_deterministic_for_deterministic_components() -> None:
    progressor = FakeStateProgressor(
        game_proposal=GameProposal(
            id="game-1",
            title="Title",
            description="Description",
            expected_state_delta="Delta",
        ),
        rationale="Progressor rationale",
    )
    executor = FakeGameExecutor(
        result=GameExecutionResult(
            id="result-1",
            game_proposal_id="template",
            status="completed",
            summary="Execution summary",
            state_delta="State delta",
            risks=["risk-a"],
        )
    )
    integrator = FakeIntegrator(
        accepted=False,
        rationale="Integrator rationale",
        applied_delta="Applied delta",
    )
    progressor_input = _input()

    first = run_loop(
        progressor=progressor,
        executor=executor,
        integrator=integrator,
        input=progressor_input,
    )
    second = run_loop(
        progressor=progressor,
        executor=executor,
        integrator=integrator,
        input=progressor_input,
    )

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def _deterministic_loop_result() -> LoopResult:
    progressor = FakeStateProgressor(
        game_proposal=GameProposal(
            id="game-1",
            title="Title",
            description="Description",
            expected_state_delta="Delta",
        ),
        rationale="Progressor rationale",
    )
    executor = FakeGameExecutor(
        result=GameExecutionResult(
            id="result-1",
            game_proposal_id="template",
            status="completed",
            summary="Execution summary",
            state_delta="State delta",
            risks=["risk-a"],
        )
    )
    integrator = FakeIntegrator(
        accepted=True,
        rationale="Integrator rationale",
        applied_delta="Applied delta",
    )
    return run_loop(progressor=progressor, executor=executor, integrator=integrator, input=_input())


def test_record_loop_result_appends_exactly_three_events(tmp_path: Path) -> None:
    blackboard = Blackboard(tmp_path / "events.jsonl")
    result = _deterministic_loop_result()

    record_loop_result(blackboard, result)

    events = blackboard.read_all()
    assert len(events) == 3


def test_record_loop_result_event_order_is_exact(tmp_path: Path) -> None:
    blackboard = Blackboard(tmp_path / "events.jsonl")
    result = _deterministic_loop_result()

    record_loop_result(blackboard, result)

    events = blackboard.read_all()
    assert [event.type for event in events] == [
        "state_progression_proposed",
        "game_executed",
        "integration_decided",
    ]


def test_record_loop_result_payloads_preserve_model_data(tmp_path: Path) -> None:
    blackboard = Blackboard(tmp_path / "events.jsonl")
    result = _deterministic_loop_result()

    record_loop_result(blackboard, result)

    events = blackboard.read_all()
    assert events[0].payload["proposal"] == result.proposal.model_dump(mode="json")
    assert events[1].payload["execution_result"] == result.execution_result.model_dump(mode="json")
    assert events[2].payload["decision"] == result.decision.model_dump(mode="json")


def test_run_loop_does_not_write_to_blackboard_implicitly(tmp_path: Path) -> None:
    blackboard = Blackboard(tmp_path / "events.jsonl")
    _ = _deterministic_loop_result()

    assert blackboard.read_all() == []
