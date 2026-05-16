import pytest
from pydantic import ValidationError

from baps.game_executor import FakeGameExecutor, GameExecutionResult
from baps.state_progressor import GameProposal


@pytest.mark.parametrize("field_name", ["id", "game_proposal_id", "status", "summary", "state_delta"])
@pytest.mark.parametrize("bad_value", ["", "   ", "\n\t"])
def test_game_execution_result_rejects_empty_required_strings(
    field_name: str,
    bad_value: str,
) -> None:
    payload = {
        "id": "result-1",
        "game_proposal_id": "game-1",
        "status": "completed",
        "summary": "Execution summary",
        "state_delta": "Expected state delta",
    }
    payload[field_name] = bad_value

    with pytest.raises(ValidationError):
        GameExecutionResult.model_validate(payload)


def test_game_execution_result_risks_default_isolated_per_instance() -> None:
    first = GameExecutionResult(
        id="result-1",
        game_proposal_id="game-1",
        status="completed",
        summary="Summary 1",
        state_delta="Delta 1",
    )
    second = GameExecutionResult(
        id="result-2",
        game_proposal_id="game-2",
        status="completed",
        summary="Summary 2",
        state_delta="Delta 2",
    )

    first.risks.append("risk-a")
    assert first.risks == ["risk-a"]
    assert second.risks == []


def test_fake_game_executor_returns_valid_result() -> None:
    executor = FakeGameExecutor(
        result=GameExecutionResult(
            id="result-1",
            game_proposal_id="template-id",
            status="completed",
            summary="Execution summary",
            state_delta="Expected state delta",
            risks=["minor-risk"],
        )
    )
    game = GameProposal(
        id="game-1",
        title="Game title",
        description="Game description",
        expected_state_delta="Expected delta",
    )

    result = executor.execute(game)

    assert isinstance(result, GameExecutionResult)
    assert result.id == "result-1"
    assert result.status == "completed"


def test_fake_game_executor_sets_game_proposal_id_from_game_id() -> None:
    executor = FakeGameExecutor(
        result=GameExecutionResult(
            id="result-1",
            game_proposal_id="template-id",
            status="completed",
            summary="Execution summary",
            state_delta="Expected state delta",
        )
    )
    game = GameProposal(
        id="game-from-input",
        title="Game title",
        description="Game description",
        expected_state_delta="Expected delta",
    )

    result = executor.execute(game)

    assert result.game_proposal_id == "game-from-input"


def test_fake_game_executor_repeated_execution_is_deterministic() -> None:
    executor = FakeGameExecutor(
        result=GameExecutionResult(
            id="result-1",
            game_proposal_id="template-id",
            status="completed",
            summary="Execution summary",
            state_delta="Expected state delta",
            risks=["minor-risk"],
        )
    )
    game = GameProposal(
        id="game-1",
        title="Game title",
        description="Game description",
        expected_state_delta="Expected delta",
    )

    first = executor.execute(game)
    second = executor.execute(game)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_fake_game_executor_does_not_mutate_input_game_proposal() -> None:
    executor = FakeGameExecutor(
        result=GameExecutionResult(
            id="result-1",
            game_proposal_id="template-id",
            status="completed",
            summary="Execution summary",
            state_delta="Expected state delta",
            risks=["minor-risk"],
        )
    )
    game = GameProposal(
        id="game-1",
        title="Game title",
        description="Game description",
        expected_state_delta="Expected delta",
        risks=["input-risk"],
    )
    before = game.model_dump(mode="json")

    _ = executor.execute(game)

    after = game.model_dump(mode="json")
    assert after == before
