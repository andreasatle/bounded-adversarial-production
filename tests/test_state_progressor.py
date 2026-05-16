import pytest
from pydantic import ValidationError

from baps.northstar_projection import NorthStarProjectionInput, NorthStarProjectionItem, render_northstar_view
from baps.state_progressor import (
    FakeStateProgressor,
    GameProposal,
    parse_state_progression_proposal,
    render_state_progressor_prompt,
    StateProgressionProposal,
    StateProgressorInput,
)


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


def test_fake_state_progressor_returns_valid_state_progression_proposal() -> None:
    progressor = FakeStateProgressor(
        game_proposal=GameProposal(
            id="game-1",
            title="Refine docs",
            description="Run docs refinement game",
            expected_state_delta="Clearer docs",
            risks=["minor drift"],
        ),
        rationale="Deterministic fake rationale",
    )
    progressor_input = StateProgressorInput(
        id="input-1",
        northstar_view=_northstar_view(),
        runtime_objective="Improve clarity",
    )

    proposal = progressor.progress(progressor_input)

    assert isinstance(proposal, StateProgressionProposal)
    assert proposal.game_proposal.id == "game-1"


def test_fake_state_progressor_preserves_input_id_linkage() -> None:
    progressor = FakeStateProgressor(
        game_proposal=GameProposal(
            id="game-1",
            title="Refine docs",
            description="Run docs refinement game",
            expected_state_delta="Clearer docs",
        ),
        rationale="Deterministic fake rationale",
    )
    progressor_input = StateProgressorInput(
        id="input-77",
        northstar_view=_northstar_view(),
        runtime_objective="Improve clarity",
    )

    proposal = progressor.progress(progressor_input)

    assert proposal.input_id == "input-77"


def test_fake_state_progressor_repeated_calls_are_deterministic() -> None:
    progressor = FakeStateProgressor(
        game_proposal=GameProposal(
            id="game-1",
            title="Refine docs",
            description="Run docs refinement game",
            expected_state_delta="Clearer docs",
            risks=["minor drift"],
        ),
        rationale="Deterministic fake rationale",
    )
    progressor_input = StateProgressorInput(
        id="input-1",
        northstar_view=_northstar_view(),
        runtime_objective="Improve clarity",
    )

    first = progressor.progress(progressor_input)
    second = progressor.progress(progressor_input)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_fake_state_progressor_does_not_mutate_inputs() -> None:
    game_proposal = GameProposal(
        id="game-1",
        title="Refine docs",
        description="Run docs refinement game",
        expected_state_delta="Clearer docs",
        risks=["minor drift"],
    )
    progressor = FakeStateProgressor(
        game_proposal=game_proposal,
        rationale="Deterministic fake rationale",
    )
    progressor_input = StateProgressorInput(
        id="input-1",
        northstar_view=_northstar_view(),
        runtime_objective="Improve clarity",
    )
    before_input = progressor_input.model_dump(mode="json")
    before_game_proposal = game_proposal.model_dump(mode="json")

    _ = progressor.progress(progressor_input)

    after_input = progressor_input.model_dump(mode="json")
    after_game_proposal = game_proposal.model_dump(mode="json")
    assert after_input == before_input
    assert after_game_proposal == before_game_proposal


def test_render_state_progressor_prompt_includes_required_sections_in_order() -> None:
    progressor_input = StateProgressorInput(
        id="input-1",
        northstar_view=_northstar_view(),
        runtime_objective="Improve architecture clarity",
    )

    prompt = render_state_progressor_prompt(progressor_input)

    task_idx = prompt.index("## State Progressor Task")
    objective_idx = prompt.index("## Runtime Objective")
    view_idx = prompt.index("## North Star View")
    output_idx = prompt.index("## Required Output")

    assert task_idx < objective_idx < view_idx < output_idx


def test_render_state_progressor_prompt_renders_runtime_objective_verbatim() -> None:
    objective = "Objective line 1\nObjective line 2 with  spaces"
    progressor_input = StateProgressorInput(
        id="input-1",
        northstar_view=_northstar_view(),
        runtime_objective=objective,
    )

    prompt = render_state_progressor_prompt(progressor_input)

    assert f"## Runtime Objective\n{objective}" in prompt


def test_render_state_progressor_prompt_renders_northstar_view_content_verbatim() -> None:
    view = _northstar_view()
    progressor_input = StateProgressorInput(
        id="input-1",
        northstar_view=view,
        runtime_objective="Improve architecture clarity",
    )

    prompt = render_state_progressor_prompt(progressor_input)

    assert f"## North Star View\n{view.content}" in prompt


def test_render_state_progressor_prompt_repeated_calls_are_byte_identical() -> None:
    progressor_input = StateProgressorInput(
        id="input-1",
        northstar_view=_northstar_view(),
        runtime_objective="Improve architecture clarity",
    )

    first = render_state_progressor_prompt(progressor_input)
    second = render_state_progressor_prompt(progressor_input)

    assert first == second


def test_parse_state_progression_proposal_valid_json() -> None:
    text = """
    {
      "id": "progression-1",
      "game_proposal": {
        "id": "game-1",
        "title": "Refine docs",
        "description": "Run documentation refinement game",
        "expected_state_delta": "Clearer docs",
        "risks": ["minor drift"]
      },
      "rationale": "Bounded improvement with low risk"
    }
    """

    parsed = parse_state_progression_proposal(text=text, input_id="input-1")

    assert isinstance(parsed, StateProgressionProposal)
    assert parsed.id == "progression-1"
    assert parsed.input_id == "input-1"
    assert parsed.game_proposal.id == "game-1"
    assert parsed.game_proposal.risks == ["minor drift"]


def test_parse_state_progression_proposal_uses_function_input_id_not_json() -> None:
    text = """
    {
      "id": "progression-1",
      "game_proposal": {
        "id": "game-1",
        "title": "Refine docs",
        "description": "Run documentation refinement game",
        "expected_state_delta": "Clearer docs",
        "risks": []
      },
      "rationale": "Bounded improvement"
    }
    """

    parsed = parse_state_progression_proposal(text=text, input_id="input-from-function")

    assert parsed.input_id == "input-from-function"


@pytest.mark.parametrize("bad_text", ["{", "[]", "\"string\"", "123"])
def test_parse_state_progression_proposal_rejects_invalid_json(bad_text: str) -> None:
    with pytest.raises(ValueError):
        parse_state_progression_proposal(text=bad_text, input_id="input-1")


@pytest.mark.parametrize(
    "missing_top_level_key",
    ["id", "game_proposal", "rationale"],
)
def test_parse_state_progression_proposal_rejects_missing_required_top_level_field(
    missing_top_level_key: str,
) -> None:
    payload = {
        "id": "progression-1",
        "game_proposal": {
            "id": "game-1",
            "title": "Refine docs",
            "description": "Run documentation refinement game",
            "expected_state_delta": "Clearer docs",
            "risks": [],
        },
        "rationale": "Bounded improvement",
    }
    del payload[missing_top_level_key]

    with pytest.raises(ValueError):
        parse_state_progression_proposal(text=str(payload).replace("'", '"'), input_id="input-1")


def test_parse_state_progression_proposal_rejects_extra_top_level_field() -> None:
    text = """
    {
      "id": "progression-1",
      "game_proposal": {
        "id": "game-1",
        "title": "Refine docs",
        "description": "Run documentation refinement game",
        "expected_state_delta": "Clearer docs",
        "risks": []
      },
      "rationale": "Bounded improvement",
      "extra": "not-allowed"
    }
    """
    with pytest.raises(ValueError):
        parse_state_progression_proposal(text=text, input_id="input-1")


def test_parse_state_progression_proposal_rejects_extra_game_proposal_field() -> None:
    text = """
    {
      "id": "progression-1",
      "game_proposal": {
        "id": "game-1",
        "title": "Refine docs",
        "description": "Run documentation refinement game",
        "expected_state_delta": "Clearer docs",
        "risks": [],
        "extra": "not-allowed"
      },
      "rationale": "Bounded improvement"
    }
    """
    with pytest.raises(ValueError):
        parse_state_progression_proposal(text=text, input_id="input-1")


@pytest.mark.parametrize(
    "bad_risks",
    [
        "\"not-a-list\"",
        "123",
        "[1, 2]",
        "[\"ok\", 3]",
    ],
)
def test_parse_state_progression_proposal_rejects_non_list_string_risks(bad_risks: str) -> None:
    text = f"""
    {{
      "id": "progression-1",
      "game_proposal": {{
        "id": "game-1",
        "title": "Refine docs",
        "description": "Run documentation refinement game",
        "expected_state_delta": "Clearer docs",
        "risks": {bad_risks}
      }},
      "rationale": "Bounded improvement"
    }}
    """
    with pytest.raises(ValueError):
        parse_state_progression_proposal(text=text, input_id="input-1")
