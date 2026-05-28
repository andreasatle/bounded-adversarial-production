"""Tests for play_game behavior."""
from __future__ import annotations

from pathlib import Path

import pytest

from baps.models.models import FakeModelClient, ToolCall
from baps.core.run import create_state
from baps.core.game import play_game
from baps.core.parsers import (
    _parse_red_finding_json,
    _parse_referee_decision_json,
)
from baps.core.prompts import _render_red_prompt, _render_referee_prompt
from baps.core.debug import _debug_print_blue_input
from baps.state.state import GameSpec
import baps.state.state as state_module


def _make_document_spec_and_state(success_condition: str = "A section exists."):
    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition=success_condition,
    )
    state = create_state(
        {
            "workspace": Path(".baps-workspace"),
            "project_type": "document",
            "artifact_id": "main-document",
            "goal": "Write a short report.",
            "northstar_markdown": "# Goal\n\nWrite a short report.",
            "output_path": Path(".baps-workspace/output/report.md"),
            "max_iterations": 2,
            "spec_path": None,
        }
    )
    return spec, state


def _make_blue_client(*titles: str):
    return FakeModelClient(
        tool_responses=[
            ToolCall(
                name="append_section",
                arguments={"artifact_id": "main-document", "title": t, "body": "Body text."},
            )
            for t in titles
        ]
    )


def test_play_game_returns_delta_document_state() -> None:
    game_spec = {
        "objective": "Write an introduction section",
        "target_artifact_id": "main-document",
        "allowed_delta_type": "DeltaDocumentState",
        "success_condition": "PlayGame must return a valid DeltaDocumentState targeting main-document.",
    }

    state = create_state(
        {
            "workspace": Path(".baps-workspace"),
            "project_type": "document",
        "artifact_id": "main-document",
            "goal": "Write a short report.",
            "northstar_markdown": "# Goal\n\nWrite a short report.",
            "output_path": Path(".baps-workspace/output/report.md"),
            "max_iterations": 2,
            "spec_path": None,
        }
    )
    delta = play_game(state, GameSpec.model_validate(game_spec))
    assert delta is not None
    assert delta.model_dump(mode="json")["operation"] == "append_section"
    assert delta.model_dump(mode="json")["artifact_id"] == "main-document"


def test_play_game_accepted_candidate_becomes_current_best_delta() -> None:

    spec = GameSpec(
        objective="Write an introduction section",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
    )
    state = create_state(
        {
            "workspace": Path(".baps-workspace"),
            "project_type": "document",
        "artifact_id": "main-document",
            "goal": "Write a short report.",
            "northstar_markdown": "# Goal\n\nWrite a short report.",
            "output_path": Path(".baps-workspace/output/report.md"),
            "max_iterations": 2,
            "spec_path": None,
        }
    )
    delta = play_game(state, spec)
    assert delta is not None
    dumped = delta.model_dump(mode="json")
    assert dumped["payload"]["section"]["title"] == "Introduction"
    assert dumped["payload"]["section"]["body"] == "Advance goal"


def test_play_game_valid_blue_tool_call_returns_delta() -> None:

    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
    )
    state = create_state(
        {
            "workspace": Path(".baps-workspace"),
            "project_type": "document",
        "artifact_id": "main-document",
            "goal": "Write a short report.",
            "northstar_markdown": "# Goal\n\nWrite a short report.",
            "output_path": Path(".baps-workspace/output/report.md"),
            "max_iterations": 2,
            "spec_path": None,
        }
    )
    delta = play_game(
        state,
        spec,
        model_client=FakeModelClient(
            tool_responses=[
                ToolCall(
                    name="append_section",
                    arguments={
                        "artifact_id": "main-document",
                        "title": "Introduction",
                        "body": "Any objective",
                    },
                )
            ]
        ),
    )
    assert delta is not None
    assert delta.model_dump(mode="json")["artifact_id"] == "main-document"


def test_play_game_no_tool_call_rejected() -> None:

    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
    )
    state = create_state(
        {
            "workspace": Path(".baps-workspace"),
            "project_type": "document",
        "artifact_id": "main-document",
            "goal": "Write a short report.",
            "northstar_markdown": "# Goal\n\nWrite a short report.",
            "output_path": Path(".baps-workspace/output/report.md"),
            "max_iterations": 2,
            "spec_path": None,
        }
    )
    delta = play_game(
        state,
        spec,
        model_client=FakeModelClient(tool_responses=[None], responses=["not-json"]),
        max_attempts=1,
    )
    assert delta is None


def test_play_game_tool_call_with_empty_body_rejected() -> None:

    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
    )
    state = create_state(
        {
            "workspace": Path(".baps-workspace"),
            "project_type": "document",
        "artifact_id": "main-document",
            "goal": "Write a short report.",
            "northstar_markdown": "# Goal\n\nWrite a short report.",
            "output_path": Path(".baps-workspace/output/report.md"),
            "max_iterations": 2,
            "spec_path": None,
        }
    )
    delta = play_game(
        state,
        spec,
        model_client=FakeModelClient(
            tool_responses=[
                ToolCall(
                    name="append_section",
                    arguments={"artifact_id": "main-document", "title": "Intro", "body": ""},
                )
            ]
        ),
        max_attempts=1,
    )
    assert delta is None


def test_play_game_valid_red_json_parses() -> None:

    red = _parse_red_finding_json(
        '{"disposition":"accept","rationale":"looks good"}'
    )
    assert red.disposition == "accept"
    assert red.rationale == "looks good"


def test_play_game_fenced_red_json_accepted() -> None:

    red = _parse_red_finding_json(
        "```json\n"
        '{"disposition":"revise","rationale":"tighten section body"}\n'
        "```"
    )
    assert red.disposition == "revise"


def test_play_game_invalid_red_json_rejected() -> None:

    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
    )
    state = create_state(
        {
            "workspace": Path(".baps-workspace"),
            "project_type": "document",
        "artifact_id": "main-document",
            "goal": "Write a short report.",
            "northstar_markdown": "# Goal\n\nWrite a short report.",
            "output_path": Path(".baps-workspace/output/report.md"),
            "max_iterations": 2,
            "spec_path": None,
        }
    )
    with pytest.raises(ValueError, match="red: model output must be valid JSON"):
        play_game(
            state,
            spec,
            model_client=FakeModelClient(
                tool_responses=[
                    ToolCall(
                        name="append_section",
                        arguments={
                            "artifact_id": "main-document",
                            "title": "Introduction",
                            "body": "Any objective",
                        },
                    )
                ]
            ),
            red_model_client=FakeModelClient(["not-json"]),
        )


def test_play_game_valid_referee_json_parses() -> None:

    decision = _parse_referee_decision_json(
        '{"disposition":"accept","rationale":"looks good"}'
    )
    assert decision.disposition == "accept"
    assert decision.rationale == "looks good"


def test_play_game_fenced_referee_json_accepted() -> None:

    decision = _parse_referee_decision_json(
        "```json\n"
        '{"disposition":"revise","rationale":"tighten acceptance criteria"}\n'
        "```"
    )
    assert decision.disposition == "revise"


def test_play_game_invalid_referee_json_rejected() -> None:

    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
    )
    state = create_state(
        {
            "workspace": Path(".baps-workspace"),
            "project_type": "document",
        "artifact_id": "main-document",
            "goal": "Write a short report.",
            "northstar_markdown": "# Goal\n\nWrite a short report.",
            "output_path": Path(".baps-workspace/output/report.md"),
            "max_iterations": 2,
            "spec_path": None,
        }
    )
    with pytest.raises(ValueError, match="referee: model output must be valid JSON"):
        play_game(
            state,
            spec,
            model_client=FakeModelClient(
                tool_responses=[
                    ToolCall(
                        name="append_section",
                        arguments={
                            "artifact_id": "main-document",
                            "title": "Introduction",
                            "body": "Any objective",
                        },
                    )
                ]
            ),
            red_model_client=FakeModelClient(
                ['{"disposition":"accept","rationale":"deterministic test path"}']
            ),
            referee_model_client=FakeModelClient(["not-json"]),
        )


def test_red_finding_optional_fields_parse_when_present() -> None:

    red = _parse_red_finding_json(
        '{"disposition":"revise","rationale":"needs work",'
        '"success_condition_met":false,'
        '"findings":["section body is too short","title duplicates existing section"]}'
    )
    assert red.disposition == "revise"
    assert red.success_condition_met is False
    assert red.findings == ("section body is too short", "title duplicates existing section")


def test_red_finding_defaults_when_optional_fields_absent() -> None:

    red = _parse_red_finding_json(
        '{"disposition":"accept","rationale":"looks good"}'
    )
    assert red.success_condition_met is None
    assert red.findings == ()


def test_red_finding_unexpected_key_stripped() -> None:

    red = _parse_red_finding_json(
        '{"disposition":"accept","rationale":"ok","confidence":0.9}'
    )
    assert red.disposition == "accept"
    assert not hasattr(red, "confidence")


def test_red_finding_missing_required_key_rejected() -> None:

    with pytest.raises(ValueError, match="missing required keys"):
        _parse_red_finding_json('{"disposition":"accept"}')


def test_referee_decision_optional_fields_parse_when_present() -> None:

    decision = _parse_referee_decision_json(
        '{"disposition":"revise","rationale":"override Red",'
        '"red_override":true,'
        '"improvement_hints":["add concrete section body","cite NorthStar goal"]}'
    )
    assert decision.disposition == "revise"
    assert decision.red_override is True
    assert decision.improvement_hints == ("add concrete section body", "cite NorthStar goal")


def test_referee_decision_defaults_when_optional_fields_absent() -> None:

    decision = _parse_referee_decision_json(
        '{"disposition":"accept","rationale":"approved"}'
    )
    assert decision.red_override is None
    assert decision.improvement_hints == ()


def test_referee_decision_unexpected_key_stripped() -> None:

    decision = _parse_referee_decision_json(
        '{"disposition":"accept","rationale":"ok","confidence":0.9}'
    )
    assert decision.disposition == "accept"
    assert not hasattr(decision, "confidence")


def test_referee_decision_missing_required_key_rejected() -> None:

    with pytest.raises(ValueError, match="missing required keys"):
        _parse_referee_decision_json('{"rationale":"ok"}')


def test_improvement_hints_appear_in_previous_feedback_for_blue() -> None:
    """improvement_hints from Referee flow into Blue's previous_feedback via model_dump."""

    captured_feedback: list[dict | None] = []
    original_debug = _debug_print_blue_input

    def _capture(state_view, game_spec, attempt, previous_feedback):
        captured_feedback.append(previous_feedback)
        original_debug(state_view, game_spec, attempt, previous_feedback)

    import baps.core.game as game_module

    spec, state = _make_document_spec_and_state()

    from unittest.mock import patch
    with patch.object(game_module, "_debug_print_blue_input", _capture):
        play_game(
            state,
            spec,
            model_client=_make_blue_client("Attempt One", "Attempt Two"),
            red_model_client=FakeModelClient(
                [
                    '{"disposition":"accept","rationale":"ok"}',
                    '{"disposition":"accept","rationale":"ok"}',
                ]
            ),
            referee_model_client=FakeModelClient(
                [
                    '{"disposition":"revise","rationale":"needs work",'
                    '"red_override":false,'
                    '"improvement_hints":["make body longer","cite NorthStar"]}',
                    '{"disposition":"accept","rationale":"approved"}',
                ]
            ),
            max_attempts=2,
        )

    assert len(captured_feedback) >= 2
    feedback = captured_feedback[1]
    assert feedback is not None
    assert "referee_decision" in feedback
    hints = feedback["referee_decision"]["improvement_hints"]
    assert hints == ["make body longer", "cite NorthStar"]


def test_red_prompt_includes_success_condition_met_and_findings_fields() -> None:
    import baps.core.game as game_module

    captured: dict[str, object] = {}
    original = _render_red_prompt

    def _capture(*args, **kwargs):
        result = original(*args, **kwargs)
        captured["prompt"] = result
        return result

    from unittest.mock import patch
    spec, state = _make_document_spec_and_state()
    with patch.object(game_module, "_render_red_prompt", _capture):
        play_game(state, spec, model_client=_make_blue_client("Introduction"))
    prompt = str(captured["prompt"])
    assert "success_condition_met" in prompt
    assert "findings" in prompt


def test_referee_prompt_includes_red_override_and_improvement_hints_fields() -> None:
    import baps.core.game as game_module

    captured: dict[str, object] = {}
    original = _render_referee_prompt

    def _capture(*args, **kwargs):
        result = original(*args, **kwargs)
        captured["prompt"] = result
        return result

    from unittest.mock import patch
    spec, state = _make_document_spec_and_state()
    with patch.object(game_module, "_render_referee_prompt", _capture):
        play_game(state, spec, model_client=_make_blue_client("Introduction"))
    prompt = str(captured["prompt"])
    assert "red_override" in prompt
    assert "improvement_hints" in prompt


def test_play_game_referee_receives_gamespec_state_view_delta_and_red(monkeypatch) -> None:

    captured: dict[str, object] = {}

    def _capture_referee_input(state_view, game_spec, delta_state, red_finding):
        captured["state_view"] = state_view
        captured["game_spec"] = game_spec
        captured["delta_state"] = delta_state
        captured["red_finding"] = red_finding

    monkeypatch.setattr("baps.core.game._debug_print_referee_input", _capture_referee_input)
    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
    )
    state = create_state(
        {
            "workspace": Path(".baps-workspace"),
            "project_type": "document",
        "artifact_id": "main-document",
            "goal": "Write a short report.",
            "northstar_markdown": "# Goal\n\nWrite a short report.",
            "output_path": Path(".baps-workspace/output/report.md"),
            "max_iterations": 2,
            "spec_path": None,
        }
    )
    delta = play_game(state, spec)
    assert delta is not None
    assert captured["game_spec"] is spec
    assert captured["state_view"] is not None
    assert captured["delta_state"] is not None
    assert captured["red_finding"] is not None


def test_play_game_referee_revise_promotes_candidate_as_fallback() -> None:

    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
    )
    state = create_state(
        {
            "workspace": Path(".baps-workspace"),
            "project_type": "document",
        "artifact_id": "main-document",
            "goal": "Write a short report.",
            "northstar_markdown": "# Goal\n\nWrite a short report.",
            "output_path": Path(".baps-workspace/output/report.md"),
            "max_iterations": 2,
            "spec_path": None,
        }
    )
    delta = play_game(
        state,
        spec,
        model_client=FakeModelClient(
            tool_responses=[
                ToolCall(
                    name="append_section",
                    arguments={
                        "artifact_id": "main-document",
                        "title": "Introduction",
                        "body": "Any objective",
                    },
                )
            ]
        ),
        red_model_client=FakeModelClient(
            ['{"disposition":"accept","rationale":"deterministic test path"}']
        ),
        referee_model_client=FakeModelClient(
            ['{"disposition":"revise","rationale":"needs changes"}']
        ),
        max_attempts=1,
    )
    assert delta is not None
    assert delta.artifact_id == "main-document"


def test_play_game_referee_accept_sets_current_best_delta() -> None:

    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
    )
    state = create_state(
        {
            "workspace": Path(".baps-workspace"),
            "project_type": "document",
        "artifact_id": "main-document",
            "goal": "Write a short report.",
            "northstar_markdown": "# Goal\n\nWrite a short report.",
            "output_path": Path(".baps-workspace/output/report.md"),
            "max_iterations": 2,
            "spec_path": None,
        }
    )
    delta = play_game(
        state,
        spec,
        model_client=FakeModelClient(
            tool_responses=[
                ToolCall(
                    name="append_section",
                    arguments={
                        "artifact_id": "main-document",
                        "title": "Introduction",
                        "body": "Any objective",
                    },
                )
            ]
        ),
        red_model_client=FakeModelClient(
            ['{"disposition":"accept","rationale":"deterministic test path"}']
        ),
        referee_model_client=FakeModelClient(
            ['{"disposition":"accept","rationale":"approved"}']
        ),
    )
    assert delta is not None


def test_play_game_red_receives_gamespec_state_view_and_delta_state(monkeypatch) -> None:

    captured: dict[str, object] = {}

    def _capture_red_input(state_view, game_spec, delta_state):
        captured["state_view"] = state_view
        captured["game_spec"] = game_spec
        captured["delta_state"] = delta_state

    monkeypatch.setattr("baps.core.game._debug_print_red_input", _capture_red_input)
    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
    )
    state = create_state(
        {
            "workspace": Path(".baps-workspace"),
            "project_type": "document",
        "artifact_id": "main-document",
            "goal": "Write a short report.",
            "northstar_markdown": "# Goal\n\nWrite a short report.",
            "output_path": Path(".baps-workspace/output/report.md"),
            "max_iterations": 2,
            "spec_path": None,
        }
    )
    delta = play_game(state, spec)
    assert delta is not None
    assert captured["game_spec"] is spec
    assert captured["state_view"] is not None
    assert captured["delta_state"] is not None


def test_red_prompt_includes_success_condition(monkeypatch) -> None:

    captured: dict[str, object] = {}
    original = _render_red_prompt

    def _capture(*args, **kwargs):
        result = original(*args, **kwargs)
        captured["prompt"] = result
        return result

    monkeypatch.setattr("baps.core.game._render_red_prompt", _capture)
    success_condition = "Unique success_condition string for red prompt contract test."
    spec, state = _make_document_spec_and_state(success_condition)
    play_game(state, spec, model_client=_make_blue_client("Introduction"))
    assert "prompt" in captured
    assert success_condition in str(captured["prompt"])


def test_referee_prompt_includes_success_condition_and_red_rationale(monkeypatch) -> None:

    captured: dict[str, object] = {}
    original = _render_referee_prompt

    def _capture(*args, **kwargs):
        result = original(*args, **kwargs)
        captured["prompt"] = result
        return result

    monkeypatch.setattr("baps.core.game._render_referee_prompt", _capture)
    success_condition = "Unique success_condition string for referee prompt contract test."
    spec, state = _make_document_spec_and_state(success_condition)
    red_rationale = "Unique red rationale for referee prompt test."
    play_game(
        state,
        spec,
        model_client=_make_blue_client("Introduction"),
        red_model_client=FakeModelClient(
            [f'{{"disposition":"accept","rationale":"{red_rationale}"}}']
        ),
    )
    prompt = str(captured["prompt"])
    assert success_condition in prompt
    assert red_rationale in prompt


def test_play_game_referee_revise_retries_and_second_attempt_accepted() -> None:

    spec, state = _make_document_spec_and_state()
    delta = play_game(
        state,
        spec,
        model_client=_make_blue_client("Attempt One", "Attempt Two"),
        red_model_client=FakeModelClient(
            [
                '{"disposition":"accept","rationale":"ok"}',
                '{"disposition":"accept","rationale":"ok"}',
            ]
        ),
        referee_model_client=FakeModelClient(
            [
                '{"disposition":"revise","rationale":"needs work"}',
                '{"disposition":"accept","rationale":"approved"}',
            ]
        ),
        max_attempts=2,
    )
    assert delta is not None
    assert delta.artifact_id == "main-document"
    assert isinstance(delta, state_module.DeltaDocumentState)
    assert delta.payload.section.title == "Attempt Two"


def test_play_game_referee_reject_retries_and_second_attempt_accepted() -> None:

    spec, state = _make_document_spec_and_state()
    delta = play_game(
        state,
        spec,
        model_client=_make_blue_client("Bad Attempt", "Good Attempt"),
        red_model_client=FakeModelClient(
            [
                '{"disposition":"accept","rationale":"ok"}',
                '{"disposition":"accept","rationale":"ok"}',
            ]
        ),
        referee_model_client=FakeModelClient(
            [
                '{"disposition":"reject","rationale":"wrong direction"}',
                '{"disposition":"accept","rationale":"approved"}',
            ]
        ),
        max_attempts=2,
    )
    assert delta is not None
    assert isinstance(delta, state_module.DeltaDocumentState)
    assert delta.payload.section.title == "Good Attempt"


def test_play_game_previous_feedback_on_retry_contains_red_and_referee(monkeypatch) -> None:


    captured_feedback: list[dict | None] = []
    original_debug = _debug_print_blue_input

    def _capture(state_view, game_spec, attempt, previous_feedback):
        captured_feedback.append(previous_feedback)
        original_debug(state_view, game_spec, attempt, previous_feedback)

    monkeypatch.setattr("baps.core.game._debug_print_blue_input", _capture)
    spec, state = _make_document_spec_and_state()
    play_game(
        state,
        spec,
        model_client=_make_blue_client("Attempt One", "Attempt Two"),
        red_model_client=FakeModelClient(
            [
                '{"disposition":"accept","rationale":"red rationale for feedback test"}',
                '{"disposition":"accept","rationale":"ok"}',
            ]
        ),
        referee_model_client=FakeModelClient(
            [
                '{"disposition":"revise","rationale":"referee rationale for feedback test"}',
                '{"disposition":"accept","rationale":"approved"}',
            ]
        ),
        max_attempts=2,
    )
    assert len(captured_feedback) >= 2
    assert captured_feedback[0] is None
    feedback = captured_feedback[1]
    assert feedback is not None
    assert "red_finding" in feedback
    assert "referee_decision" in feedback
    assert feedback["red_finding"]["rationale"] == "red rationale for feedback test"
    assert feedback["referee_decision"]["rationale"] == "referee rationale for feedback test"
    assert feedback["referee_decision"]["disposition"] == "revise"


def test_play_game_red_reject_with_referee_accept_returns_delta() -> None:
    """Red is advisory: a Red reject must not prevent acceptance when Referee accepts."""
    spec, state = _make_document_spec_and_state()
    delta = play_game(
        state,
        spec,
        model_client=_make_blue_client("Introduction"),
        red_model_client=FakeModelClient(
            ['{"disposition":"reject","rationale":"red says no"}']
        ),
        referee_model_client=FakeModelClient(
            ['{"disposition":"accept","rationale":"referee overrides"}']
        ),
    )
    assert delta is not None
    assert delta.artifact_id == "main-document"


def test_play_game_all_referee_rejects_returns_none() -> None:
    spec, state = _make_document_spec_and_state()
    delta = play_game(
        state,
        spec,
        model_client=_make_blue_client("Attempt One", "Attempt Two"),
        red_model_client=FakeModelClient(
            [
                '{"disposition":"accept","rationale":"ok"}',
                '{"disposition":"accept","rationale":"ok"}',
            ]
        ),
        referee_model_client=FakeModelClient(
            [
                '{"disposition":"reject","rationale":"wrong"}',
                '{"disposition":"reject","rationale":"still wrong"}',
            ]
        ),
        max_attempts=2,
    )
    assert delta is None
