import pytest
from pydantic import ValidationError

from baps.northstar_projection import NorthStarProjectionInput, NorthStarProjectionItem, render_northstar_view
from baps.state_progressor import GameProposal, StateProgressionProposal, StateProgressorInput


def _northstar_view():
    return render_northstar_view(
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
    )


@pytest.mark.parametrize("bad_value", ["", "   ", "\n\t"])
def test_state_progressor_input_rejects_empty_required_strings(bad_value: str) -> None:
    with pytest.raises(ValidationError):
        StateProgressorInput(
            id=bad_value,
            northstar_view=_northstar_view(),
            runtime_objective="Valid objective",
        )
    with pytest.raises(ValidationError):
        StateProgressorInput(
            id="input-1",
            northstar_view=_northstar_view(),
            runtime_objective=bad_value,
        )


@pytest.mark.parametrize("field_name", ["id", "title", "description", "expected_state_delta"])
@pytest.mark.parametrize("bad_value", ["", "   ", "\n\t"])
def test_game_proposal_rejects_empty_required_strings(field_name: str, bad_value: str) -> None:
    payload = {
        "id": "game-1",
        "title": "Proposal title",
        "description": "Proposal description",
        "expected_state_delta": "Expected delta",
    }
    payload[field_name] = bad_value
    with pytest.raises(ValidationError):
        GameProposal.model_validate(payload)


@pytest.mark.parametrize("field_name", ["id", "input_id", "rationale"])
@pytest.mark.parametrize("bad_value", ["", "   ", "\n\t"])
def test_state_progression_proposal_rejects_empty_required_strings(
    field_name: str,
    bad_value: str,
) -> None:
    payload = {
        "id": "progression-1",
        "input_id": "input-1",
        "game_proposal": {
            "id": "game-1",
            "title": "Proposal title",
            "description": "Proposal description",
            "expected_state_delta": "Expected delta",
        },
        "rationale": "Because this game advances objective",
    }
    payload[field_name] = bad_value
    with pytest.raises(ValidationError):
        StateProgressionProposal.model_validate(payload)


def test_game_proposal_risks_default_is_isolated_per_instance() -> None:
    first = GameProposal(
        id="game-1",
        title="Title 1",
        description="Description 1",
        expected_state_delta="Delta 1",
    )
    second = GameProposal(
        id="game-2",
        title="Title 2",
        description="Description 2",
        expected_state_delta="Delta 2",
    )

    first.risks.append("risk-a")
    assert first.risks == ["risk-a"]
    assert second.risks == []


def test_valid_nested_state_progressor_models_validate_successfully() -> None:
    view = _northstar_view()
    progressor_input = StateProgressorInput(
        id="input-1",
        northstar_view=view,
        runtime_objective="Advance project state with bounded risk",
    )

    game_proposal = GameProposal(
        id="game-1",
        title="Refine architecture docs",
        description="Run a bounded documentation refinement game",
        expected_state_delta="Clearer architecture constraints",
        risks=["minor documentation drift"],
    )

    progression = StateProgressionProposal(
        id="progression-1",
        input_id=progressor_input.id,
        game_proposal=game_proposal,
        rationale="Improves clarity while preserving bounded scope",
    )

    assert progression.input_id == progressor_input.id
    assert progression.game_proposal.id == "game-1"
    assert progression.game_proposal.risks == ["minor documentation drift"]
