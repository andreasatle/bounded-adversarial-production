"""Tests for play_game attempt/retry and debug behavior."""
from __future__ import annotations

from pathlib import Path

from baps.models.models import FakeModelClient, ToolCall
from baps.core.run import create_state
from baps.core.game import play_game
from baps.core.prompts import _render_red_prompt, _render_referee_prompt
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


    def _capture_event(name, payload):
        if name != "referee.input":
            return
        captured["state_view"] = payload["state_view"]
        captured["game_spec"] = payload["game_spec"]
        captured["delta_state"] = payload["delta_state"]
        captured["red_finding"] = payload["red_finding"]

    monkeypatch.setattr("baps.core.game.debug_event", _capture_event)
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
    assert captured["game_spec"] is not None
    assert captured["state_view"] is not None
    assert captured["delta_state"] is not None
    assert captured["red_finding"] is not None


def test_play_game_referee_revise_only_returns_none() -> None:

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
    assert delta is None


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

    def _capture_event(name, payload):
        if name != "red.input":
            return
        captured["state_view"] = payload["state_view"]
        captured["game_spec"] = payload["game_spec"]
        captured["delta_state"] = payload["delta_state"]

    monkeypatch.setattr("baps.core.game.debug_event", _capture_event)
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
    assert captured["game_spec"] is not None
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


def test_play_game_debug_output_distinguishes_current_best_from_integration_eligible(monkeypatch) -> None:
    captured: list[dict] = []

    def _capture_event(name, payload):
        if name == "play_game.output":
            captured.append(payload)

    monkeypatch.setattr("baps.core.game.debug_event", _capture_event)
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
                '{"disposition":"revise","rationale":"promising but not ready"}',
                '{"disposition":"reject","rationale":"still not acceptable"}',
            ]
        ),
        max_attempts=2,
    )
    assert delta is None
    assert len(captured) == 1
    output_payload = captured[0]
    assert output_payload["current_best_delta"] is not None
    assert output_payload["integration_eligible_delta"] is None
    assert output_payload["current_best_delta"]["payload"]["section"]["title"] == "Attempt One"


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
    def _capture_event(name, payload):
        if name == "blue.input":
            captured_feedback.append(payload["previous_feedback"])

    monkeypatch.setattr("baps.core.game.debug_event", _capture_event)
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
