"""Tests for create_game and play_game behavior, and blackboard events."""
from __future__ import annotations

import inspect
import json
import logging
from pathlib import Path

import pytest

from baps.models import FakeModelClient, ToolCall
from baps.run import create_state
from baps.game import create_game, play_game
from baps.document_adapter import DocumentProjectAdapter
from baps.parsers import (
    NoNewGameError,
    _parse_red_finding_json,
    _parse_referee_decision_json,
)
from baps.prompts import _render_create_game_prompt, _render_red_prompt, _render_referee_prompt
from baps.debug import _debug_print_blue_input
from baps.state import (
    GameSpec,
)
from baps.game import _VERIFICATION_SUMMARY_CAP
from baps.project_adapter import VerificationResult
import baps.state as state_module


def _make_doc_config(
    artifact_id: str = "main-document",
    goal: str = "Write a short report.",
) -> dict:
    return {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": artifact_id,
        "goal": goal,
        "northstar_markdown": f"# Goal\n\n{goal}",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }


def _make_document_spec_and_state(success_condition: str = "A section exists."):
    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition=success_condition,
    )
    state = create_state({
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    })
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


def _make_play_game_config(workspace: Path) -> dict:
    return {
        "workspace": workspace,
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": workspace / "output" / "report.md",
        "max_iterations": 1,
        "spec_path": None,
    }


def _make_document_game_spec(**kwargs) -> GameSpec:
    return GameSpec(
        objective="Add introduction section",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Introduction section must be present.",
        **kwargs,
    )


def test_create_game_receives_input_and_state_and_outputs_game_spec() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Advance report objective","target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}'
            ]
        ),
    )

    assert game_spec.target_artifact_id == "main-document"
    assert game_spec.allowed_delta_type == "DeltaDocumentState"
    assert "DeltaDocumentState" in game_spec.success_condition


def test_create_game_target_artifact_exists_in_state() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Advance report objective","target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}'
            ]
        ),
    )
    assert any(artifact.id == game_spec.target_artifact_id for artifact in state.artifacts)


def test_create_game_invalid_json_fails_cleanly() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    # Provide one response per attempt (initial + 2 retries) so FakeModelClient doesn't run dry.
    with pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient(["not-json", "not-json", "not-json"]))


def test_create_game_invalid_json_with_debug_prints_raw_model_output(
    monkeypatch, caplog
) -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)

    with caplog.at_level(logging.DEBUG), pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient(["not-json-output", "not-json-output", "not-json-output"]))
    assert "create_game.prompt:" in caplog.text
    assert "create_game.raw_model_output:" in caplog.text
    assert "not-json-output" in caplog.text
    assert "retrying with correction prompt" in caplog.text


def test_create_game_invalid_json_without_debug_does_not_print_raw_model_output(caplog) -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)

    with caplog.at_level(logging.INFO), pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient(["not-json-output", "not-json-output", "not-json-output"]))
    assert "create_game.prompt:" not in caplog.text
    assert "create_game.raw_model_output:" not in caplog.text


def test_create_game_json_retry_with_correction_prompt_succeeds() -> None:
    valid_response = (
        '{"objective":"Advance goal","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"section exists"}'
    )
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)

    # First response is invalid JSON; the retry with the correction prompt returns valid JSON.
    game_spec = create_game(config, state, model_client=FakeModelClient(["not-json", valid_response]))

    assert game_spec.target_artifact_id == "main-document"


def test_create_game_explicit_model_client_retries_on_invalid_json() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)

    # Explicit model_client — correction-prompt retries still apply (same model, not a fallback).
    with pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient(["not-json", "not-json", "not-json"]))


def test_create_game_structural_validation_failure_debug_prints_raw_output(
    monkeypatch, caplog
) -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    payload = (
        '{"objective":" ","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"Add introduction and conclusion"}'
    )
    with caplog.at_level(logging.DEBUG), pytest.raises(ValueError, match="create_game model output failed GameSpec validation"):
        create_game(config, state, model_client=FakeModelClient([payload]))
    assert "create_game.prompt:" in caplog.text
    assert "create_game.raw_model_output:" in caplog.text
    assert "create_game.validation_input:" not in caplog.text
    assert "create_game.validation_failure:" not in caplog.text
    assert payload in caplog.text


def test_create_game_validation_input_debug_enabled(caplog) -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)

    with caplog.at_level(logging.DEBUG):
        create_game(
            config,
            state,
            model_client=FakeModelClient(
                [
                    '{"objective":"Advance report objective","target_artifact_id":"main-document",'
                    '"allowed_delta_type":"DeltaDocumentState",'
                    '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}'
                ]
            ),
        )
    assert "create_game.validation_input:" in caplog.text
    assert "objective: Advance report objective" in caplog.text
    assert "success_condition: PlayGame must return a valid DeltaDocumentState targeting main-document." in caplog.text
    assert "target_artifact_id: main-document" in caplog.text
    assert "allowed_delta_type: DeltaDocumentState" in caplog.text


def test_create_game_semantic_refinement_objective_is_accepted(caplog) -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)

    with caplog.at_level(logging.DEBUG):
        game_spec = create_game(
            config,
            state,
            model_client=FakeModelClient(
                [
                    '{"objective":"Add a Conclusion section to artifact main-document, summarizing bounded adversarial evaluation outcomes and reiterating relevance to software project improvement.",'
                    '"target_artifact_id":"main-document",'
                    '"allowed_delta_type":"DeltaDocumentState",'
                    '"success_condition":"Artifact contains a Conclusion section summarizing bounded adversarial evaluation outcomes and reiterating relevance to software project improvement."}'
                ]
            ),
        )
    assert game_spec.target_artifact_id == "main-document"
    assert "create_game.validation_input:" in caplog.text


def test_create_game_objective_with_multiple_tasks_is_accepted_by_structural_validation() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Update report and create appendix",'
                '"target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"Report is updated and appendix is created."}'
            ]
        ),
    )
    assert game_spec.objective == "Update report and create appendix"


def test_create_game_validation_debug_disabled_prints_nothing(caplog) -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)

    with caplog.at_level(logging.INFO):
        create_game(
            config,
            state,
            model_client=FakeModelClient(
                [
                    '{"objective":"Advance report objective","target_artifact_id":"main-document",'
                    '"allowed_delta_type":"DeltaDocumentState",'
                    '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}'
                ]
            ),
        )
    assert "create_game.validation_input:" not in caplog.text
    assert "create_game.validation_failure:" not in caplog.text


def test_create_game_raw_json_still_accepted() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Advance report objective","target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}'
            ]
        ),
    )
    assert game_spec.target_artifact_id == "main-document"


def test_create_game_exact_json_fence_accepted() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                "```json\n"
                '{"objective":"Advance report objective","target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}\n'
                "```"
            ]
        ),
    )
    assert game_spec.target_artifact_id == "main-document"


def test_create_game_exact_plain_fence_accepted() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                "```\n"
                '{"objective":"Advance report objective","target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}\n'
                "```"
            ]
        ),
    )
    assert game_spec.target_artifact_id == "main-document"


def test_create_game_prose_before_fence_extracted_and_parsed() -> None:
    # Pipeline extracts JSON from prose — prose wrapper is now handled correctly.
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    response = (
        "Here is the result:\n```json\n"
        '{"objective":"Advance report objective","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}\n'
        "```"
    )
    game_spec = create_game(config, state, model_client=FakeModelClient([response]))
    assert game_spec.objective == "Advance report objective"


def test_create_game_prose_after_fence_extracted_and_parsed() -> None:
    # Pipeline extracts JSON via brace search when fence anchoring fails — handled correctly.
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    response = (
        "```json\n"
        '{"objective":"Advance report objective","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}\n'
        "```\nDone."
    )
    game_spec = create_game(config, state, model_client=FakeModelClient([response]))
    assert game_spec.objective == "Advance report objective"


def test_create_game_multiple_fenced_blocks_rejected() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    bad = (
        "```json\n"
        '{"objective":"Advance report objective","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}\n'
        "```\n```json\n{}\n```"
    )
    with pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient([bad, bad, bad]))


def test_create_game_invalid_json_inside_fence_rejected() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    bad = "```json\n{not valid json}\n```"
    with pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient([bad, bad, bad]))


def test_create_game_missing_gamespec_fields_fails_cleanly() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    with pytest.raises(ValueError, match="must contain exactly keys"):
        create_game(
            config,
            state,
            model_client=FakeModelClient(['{"objective":"only-objective"}']),
        )


def test_create_game_target_artifact_not_in_state_fails_cleanly() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    with pytest.raises(ValueError, match="target artifact must match configured artifact_id"):
        create_game(
            config,
            state,
            model_client=FakeModelClient(
                [
                    '{"objective":"Advance report objective","target_artifact_id":"missing-document",'
                    '"allowed_delta_type":"DeltaDocumentState",'
                    '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting missing-document."}'
                ]
            ),
        )


def test_create_game_uses_adapter_build_create_game_state_view(monkeypatch) -> None:

    class _CapturingAdapter(DocumentProjectAdapter):
        def __init__(self):
            super().__init__()
            self.called = False

        def build_create_game_state_view(self, state, config):
            self.called = True
            return super().build_create_game_state_view(state, config)

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    adapter = _CapturingAdapter()
    _ = create_game(
        config,
        state,
        adapter=adapter,
        model_client=FakeModelClient(
            [
                '{"objective":"Advance report objective","target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}'
            ]
        ),
    )
    assert adapter.called is True


def test_create_game_core_source_has_no_document_specific_refs() -> None:

    src = inspect.getsource(create_game)
    assert "DocumentArtifact" not in src
    assert "_document_artifact_from_state" not in src
    assert ".sections" not in src


def test_create_game_prompt_forbids_markdown_fences_and_lists_required_shape() -> None:

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    adapter = DocumentProjectAdapter()
    prompt = _render_create_game_prompt(
        config,
        state,
        adapter.build_create_game_state_view(state, config),
        adapter=adapter,
    )

    assert "Return only a JSON object" in prompt
    assert "Do not wrap output in markdown" in prompt
    assert "Do not use triple-backtick fences" in prompt
    assert '"objective"' in prompt
    assert '"target_artifact_id"' in prompt
    assert '"allowed_delta_type"' in prompt
    assert '"success_condition"' in prompt
    assert "Do not artificially split a coherent gap into multiple games" in prompt
    assert "All files or sections that must change together to close a gap belong in one game" in prompt
    assert "decompose" in prompt


def test_create_game_broad_goal_accepts_decomposed_atomic_gamespec() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "add introduction and conclusion",
        "northstar_markdown": "# Goal\n\nadd introduction and conclusion",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"add introduction section",'
                '"target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"Introduction section exists in main-document."}'
            ]
        ),
    )
    assert game_spec.objective == "add introduction section"
    assert game_spec.success_condition == "Introduction section exists in main-document."


def test_create_game_bundled_objective_and_success_condition_are_structurally_valid() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "add introduction and conclusion",
        "northstar_markdown": "# Goal\n\nadd introduction and conclusion",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"add introduction and conclusion",'
                '"target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"Introduction and conclusion sections both exist."}'
            ]
        ),
    )
    assert game_spec.objective == "add introduction and conclusion"


def test_create_game_multi_feature_wording_is_structurally_valid() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "implement parser and tests",
        "northstar_markdown": "# Goal\n\nimplement parser and tests",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"implement parser and tests",'
                '"target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"Parser and tests are implemented."}'
            ]
        ),
    )
    assert game_spec.objective == "implement parser and tests"


def test_create_game_red_accepts_game_spec_immediately() -> None:
    config = _make_doc_config()
    state = create_state(config)
    game_spec_json = (
        '{"objective":"Write introduction","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState","success_condition":"Introduction present."}'
    )
    red_accept_json = '{"disposition":"accept","rationale":"Good scope.","success_condition_met":null,"findings":[]}'
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient([game_spec_json]),
        create_game_red_client=FakeModelClient([red_accept_json]),
    )
    assert game_spec.objective == "Write introduction"


def test_create_game_red_reject_triggers_retry_with_feedback() -> None:
    config = _make_doc_config()
    state = create_state(config)
    first_spec = (
        '{"objective":"Write everything","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState","success_condition":"All done."}'
    )
    second_spec = (
        '{"objective":"Write introduction section","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState","success_condition":"Introduction present."}'
    )
    red_reject = (
        '{"disposition":"reject","rationale":"Too broad.","success_condition_met":null,'
        '"findings":["Objective spans multiple concerns"]}'
    )
    # CreateGame is called twice; Red is called once (only on attempt 1)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient([first_spec, second_spec]),
        create_game_red_client=FakeModelClient([red_reject]),
        max_create_game_attempts=2,
    )
    assert game_spec.objective == "Write introduction section"


def test_create_game_red_feedback_appears_in_retry_prompt() -> None:
    config = _make_doc_config()
    state = create_state(config)
    spec_json = (
        '{"objective":"Write everything","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState","success_condition":"All done."}'
    )
    red_reject = (
        '{"disposition":"reject","rationale":"Too broad.","success_condition_met":null,'
        '"findings":["Scope too wide"]}'
    )
    prompts_seen: list[str] = []
    real_generate = FakeModelClient([spec_json, spec_json]).generate

    class CapturingClient:
        responses = iter([spec_json, spec_json])

        def generate(self, prompt: str, format=None) -> str:
            prompts_seen.append(prompt)
            return next(self.responses)

        def generate_with_tools(self, prompt, tools):
            return None

    create_game(
        config,
        state,
        model_client=CapturingClient(),
        create_game_red_client=FakeModelClient([red_reject]),
        max_create_game_attempts=2,
    )
    assert len(prompts_seen) == 2
    assert "Too broad" in prompts_seen[1]
    assert "Scope too wide" in prompts_seen[1]


def test_create_game_red_client_none_skips_challenge() -> None:
    config = _make_doc_config()
    state = create_state(config)
    spec_json = (
        '{"objective":"Write introduction","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState","success_condition":"Introduction present."}'
    )
    # No create_game_red_client — should return immediately after one CreateGame call
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient([spec_json]),
        create_game_red_client=None,
    )
    assert game_spec.objective == "Write introduction"


def test_create_game_red_unparseable_output_falls_back_to_accept() -> None:
    config = _make_doc_config()
    state = create_state(config)
    spec_json = (
        '{"objective":"Write introduction","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState","success_condition":"Introduction present."}'
    )
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient([spec_json]),
        create_game_red_client=FakeModelClient(["not valid json at all"]),
    )
    assert game_spec.objective == "Write introduction"


def test_create_game_red_revise_triggers_retry() -> None:
    config = _make_doc_config()
    state = create_state(config)
    first_spec = (
        '{"objective":"Write intro","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState","success_condition":"Vague."}'
    )
    second_spec = (
        '{"objective":"Write introduction section","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"Introduction section present with title and 2+ paragraphs."}'
    )
    red_revise = (
        '{"disposition":"revise","rationale":"Success condition too vague.","success_condition_met":null,'
        '"findings":["success_condition lacks specificity"]}'
    )
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient([first_spec, second_spec]),
        create_game_red_client=FakeModelClient([red_revise]),
        max_create_game_attempts=2,
    )
    assert "2+ paragraphs" in game_spec.success_condition


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

    import baps.game as game_module

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
    import baps.game as game_module

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
    import baps.game as game_module

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

    monkeypatch.setattr("baps.game._debug_print_referee_input", _capture_referee_input)
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

    monkeypatch.setattr("baps.game._debug_print_red_input", _capture_red_input)
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


def test_red_prompt_includes_success_condition(monkeypatch) -> None:

    captured: dict[str, object] = {}
    original = _render_red_prompt

    def _capture(*args, **kwargs):
        result = original(*args, **kwargs)
        captured["prompt"] = result
        return result

    monkeypatch.setattr("baps.game._render_red_prompt", _capture)
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

    monkeypatch.setattr("baps.game._render_referee_prompt", _capture)
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

    monkeypatch.setattr("baps.game._debug_print_blue_input", _capture)
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

def test_create_game_writes_create_game_blackboard_event(tmp_path: Path) -> None:
    config = {
        "workspace": tmp_path / "ws-cg-bb",
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": tmp_path / "ws-cg-bb" / "output" / "report.md",
        "max_iterations": 1,
        "spec_path": None,
    }
    state = create_state(config)
    create_game(
        config,
        state,
        model_client=FakeModelClient([
            '{"objective":"Close the gap","target_artifact_id":"main-document",'
            '"allowed_delta_type":"DeltaDocumentState",'
            '"success_condition":"Section present."}'
        ]),
    )

    games_path = config["workspace"] / "blackboard" / "games.jsonl"
    assert games_path.exists(), "games.jsonl must be written by create_game"
    entry = json.loads(games_path.read_text(encoding="utf-8").strip())

    assert entry["event"] == "create_game"
    assert "created_at" in entry
    assert entry["depth"] == 0
    assert entry["context_chain"] == []
    assert "state_view_fingerprint" in entry
    assert entry["state_view_fingerprint"] != ""
    assert entry["result_type"] == "game_spec"
    assert entry["result"]["objective"] == "Close the gap"
    assert entry["result"]["target_artifact_id"] == "main-document"
    assert "model_used" in entry


def test_create_game_writes_no_new_game_event(tmp_path: Path) -> None:
    config = {
        "workspace": tmp_path / "ws-nng-bb",
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": tmp_path / "ws-nng-bb" / "output" / "report.md",
        "max_iterations": 1,
        "spec_path": None,
    }
    state = create_state(config)
    with pytest.raises(NoNewGameError):
        create_game(
            config,
            state,
            model_client=FakeModelClient(['{"no_new_game": true, "reason": "All gaps closed."}']),
        )

    games_path = config["workspace"] / "blackboard" / "games.jsonl"
    assert games_path.exists()
    entry = json.loads(games_path.read_text(encoding="utf-8").strip())
    assert entry["event"] == "create_game"
    assert entry["result_type"] == "no_new_game"
    assert entry["result"] is None
    assert "created_at" in entry


def test_create_game_writes_decompose_spec_event(tmp_path: Path) -> None:
    config = {
        "workspace": tmp_path / "ws-dc-bb",
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a long report.",
        "northstar_markdown": "# Goal\n\nWrite a long report.",
        "output_path": tmp_path / "ws-dc-bb" / "output" / "report.md",
        "max_iterations": 1,
        "spec_path": None,
    }
    state = create_state(config)
    create_game(
        config,
        state,
        model_client=FakeModelClient([
            '{"decompose": true, "rationale": "Too large", '
            '"sub_gaps": [{"description": "Part one"}, {"description": "Part two"}]}'
        ]),
    )

    games_path = config["workspace"] / "blackboard" / "games.jsonl"
    assert games_path.exists()
    entry = json.loads(games_path.read_text(encoding="utf-8").strip())
    assert entry["event"] == "create_game"
    assert entry["result_type"] == "decompose_spec"
    assert entry["result"]["rationale"] == "Too large"
    assert len(entry["result"]["sub_gaps"]) == 2
    assert entry["result"]["sub_gaps"][0]["description"] == "Part one"


def test_play_game_writes_play_game_blackboard_event(tmp_path: Path) -> None:
    workspace = tmp_path / "ws-pg-bb"
    config = {
        "workspace": workspace,
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": workspace / "output" / "report.md",
        "max_iterations": 1,
        "spec_path": None,
    }
    state = create_state(config)
    game_spec = GameSpec(
        objective="Add introduction section",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Introduction section must be present.",
    )
    play_game(state, game_spec, config=config)

    games_path = workspace / "blackboard" / "games.jsonl"
    assert games_path.exists(), "games.jsonl must be written by play_game"
    entry = json.loads(games_path.read_text(encoding="utf-8").strip())

    assert entry["event"] == "play_game"
    assert "game_id" in entry
    assert "created_at" in entry
    assert entry["depth"] == 0
    assert entry["context_chain"] == []
    assert "game_spec" in entry
    assert entry["game_spec"]["objective"] == "Add introduction section"
    assert isinstance(entry["attempts"], list)
    assert len(entry["attempts"]) >= 1
    attempt = entry["attempts"][0]
    assert attempt["attempt_number"] == 1
    assert "blue_delta" in attempt
    assert "red_finding" in attempt
    assert "referee_decision" in attempt
    assert entry["final_disposition"] in ("accepted", "rejected", "no_delta")


def test_integration_writes_integration_blackboard_event(
    monkeypatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-int-bb"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace", str(workspace),
            "--project-type", "document",
            "--artifact-id", "main-document",
            "--goal", "Write a short report.",
            "--output", "output/report.md",
            "--max-iterations", "1",
        ],
    )
    from baps.run import main as run_main
    run_main()

    games_path = workspace / "blackboard" / "games.jsonl"
    assert games_path.exists(), "games.jsonl must exist after a successful run"

    lines = [json.loads(l) for l in games_path.read_text(encoding="utf-8").strip().splitlines()]
    integration_events = [e for e in lines if e["event"] == "integration"]
    assert len(integration_events) >= 1, "at least one integration event must be written"

    evt = integration_events[0]
    assert "created_at" in evt
    assert "depth" in evt
    assert "proposal_id" in evt
    assert evt["proposal_id"] != ""
    assert "proposal_summary" in evt
    assert isinstance(evt["state_changed"], bool)
    assert "delta_type" in evt
    assert evt["delta_type"] != ""


# ---------------------------------------------------------------------------
# play_game blackboard — final_disposition branches
# ---------------------------------------------------------------------------

def _make_play_game_config(workspace: Path) -> dict:
    return {
        "workspace": workspace,
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": workspace / "output" / "report.md",
        "max_iterations": 1,
        "spec_path": None,
    }


def _make_document_game_spec(**kwargs) -> "GameSpec":
    return GameSpec(
        objective="Add introduction section",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Introduction section must be present.",
        **kwargs,
    )


def test_play_game_blackboard_final_disposition_accepted(tmp_path: Path) -> None:
    workspace = tmp_path / "ws-accept"
    config = _make_play_game_config(workspace)
    state = create_state(config)
    play_game(state, _make_document_game_spec(), config=config)

    entry = json.loads(
        (workspace / "blackboard" / "games.jsonl").read_text(encoding="utf-8").strip()
    )
    assert entry["final_disposition"] == "accepted"
    attempt = entry["attempts"][0]
    assert attempt["blue_delta"] is not None
    assert attempt["red_finding"]["disposition"] == "accept"
    assert attempt["referee_decision"]["disposition"] == "accept"


def test_play_game_blackboard_final_disposition_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "ws-reject"
    config = _make_play_game_config(workspace)
    state = create_state(config)
    play_game(
        state,
        _make_document_game_spec(),
        config=config,
        referee_model_client=FakeModelClient(
            ['{"disposition":"reject","rationale":"not good enough"}']
        ),
        max_attempts=1,
    )

    entry = json.loads(
        (workspace / "blackboard" / "games.jsonl").read_text(encoding="utf-8").strip()
    )
    assert entry["final_disposition"] == "rejected"
    attempt = entry["attempts"][0]
    assert attempt["blue_delta"] is not None
    assert attempt["referee_decision"]["disposition"] == "reject"


def test_play_game_blackboard_final_disposition_no_delta(tmp_path: Path) -> None:
    workspace = tmp_path / "ws-nodelta"
    config = _make_play_game_config(workspace)
    state = create_state(config)
    # Empty body fails Section._validate_body → tool_call_to_delta raises → blue_delta stays None
    play_game(
        state,
        _make_document_game_spec(),
        config=config,
        model_client=FakeModelClient(
            tool_responses=[ToolCall("append_section", {"artifact_id": "main-document", "title": "Intro", "body": ""})]
        ),
        max_attempts=1,
    )

    entry = json.loads(
        (workspace / "blackboard" / "games.jsonl").read_text(encoding="utf-8").strip()
    )
    assert entry["final_disposition"] == "no_delta"
    assert all(r["blue_delta"] is None for r in entry["attempts"])


# ---------------------------------------------------------------------------
# depth and context_chain captured in create_game and play_game events
# ---------------------------------------------------------------------------

def test_create_game_blackboard_captures_depth_and_context_chain(tmp_path: Path) -> None:
    config = {
        "workspace": tmp_path / "ws-cg-depth",
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a report.",
        "northstar_markdown": "# Goal\n\nWrite a report.",
        "output_path": tmp_path / "ws-cg-depth" / "output" / "report.md",
        "max_iterations": 1,
        "spec_path": None,
    }
    state = create_state(config)
    chain = ("Top-level gap", "Sub-level concern")
    create_game(
        config,
        state,
        depth=2,
        context_chain=chain,
        model_client=FakeModelClient([
            '{"objective":"Close the gap","target_artifact_id":"main-document",'
            '"allowed_delta_type":"DeltaDocumentState",'
            '"success_condition":"Section present."}'
        ]),
    )

    entry = json.loads(
        (config["workspace"] / "blackboard" / "games.jsonl").read_text(encoding="utf-8").strip()
    )
    assert entry["depth"] == 2
    assert entry["context_chain"] == list(chain)


def test_play_game_blackboard_captures_depth_and_context_chain(tmp_path: Path) -> None:
    workspace = tmp_path / "ws-pg-depth"
    config = _make_play_game_config(workspace)
    state = create_state(config)
    chain = ("Parent gap", "Child concern")
    game_spec = _make_document_game_spec(context_chain=chain)
    play_game(state, game_spec, config=config, depth=1)

    entry = json.loads(
        (workspace / "blackboard" / "games.jsonl").read_text(encoding="utf-8").strip()
    )
    assert entry["depth"] == 1
    assert entry["context_chain"] == list(chain)


# ---------------------------------------------------------------------------
# Verification summary truncation — blackboard truncates, source is unchanged
# ---------------------------------------------------------------------------

def test_blackboard_verification_summary_truncated_to_cap(
    tmp_path: Path, monkeypatch
) -> None:

    long_stdout = "O" * 700
    long_stderr = "E" * 600
    mock_vr = VerificationResult(
        command="pytest", cwd="/tmp", exit_code=0,
        stdout=long_stdout, stderr=long_stderr, passed=True,
    )
    monkeypatch.setattr("baps.game._verify_candidate_with_adapter", lambda *a, **kw: mock_vr)

    workspace = tmp_path / "ws-trunc"
    config = _make_play_game_config(workspace)
    state = create_state(config)
    play_game(state, _make_document_game_spec(), config=config)

    entry = json.loads(
        (workspace / "blackboard" / "games.jsonl").read_text(encoding="utf-8").strip()
    )
    cap = _VERIFICATION_SUMMARY_CAP
    vr_summary = entry["verification_result"]
    assert vr_summary["stdout_summary"] == "O" * cap
    assert vr_summary["stderr_summary"] == "E" * cap
    assert len(vr_summary["stdout_summary"]) == cap
    assert len(vr_summary["stderr_summary"]) == cap

    attempt_vr = entry["attempts"][0]["candidate_verification"]
    assert attempt_vr["stdout_summary"] == "O" * cap
    assert attempt_vr["stderr_summary"] == "E" * cap

    # Original VerificationResult object is not mutated
    assert mock_vr.stdout == long_stdout
    assert mock_vr.stderr == long_stderr


def test_blackboard_verification_feedback_loop_uses_full_text(
    tmp_path: Path, monkeypatch
) -> None:
    """When candidate verification fails and Blue retries, the full stdout/stderr
    must appear in Blue's next prompt — only the blackboard summary is truncated."""

    long_stdout = "F" * 700
    failing_vr = VerificationResult(
        command="pytest", cwd="/tmp", exit_code=1,
        stdout=long_stdout, stderr="", passed=False,
    )
    passing_vr = VerificationResult(
        command="pytest", cwd="/tmp", exit_code=0,
        stdout="ok", stderr="", passed=True,
    )
    call_count = {"n": 0}

    def _mock_verify(*a, **kw):
        call_count["n"] += 1
        return failing_vr if call_count["n"] == 1 else passing_vr

    monkeypatch.setattr("baps.game._verify_candidate_with_adapter", _mock_verify)

    workspace = tmp_path / "ws-feedbackloop"
    config = _make_play_game_config(workspace)
    state = create_state(config)
    blue_client = FakeModelClient(
        tool_responses=[
            ToolCall("append_section", {"artifact_id": "main-document", "title": "Intro", "body": "first"}),
            ToolCall("append_section", {"artifact_id": "main-document", "title": "Intro2", "body": "second"}),
        ]
    )
    accept_response = '{"disposition":"accept","rationale":"ok"}'
    play_game(
        state,
        _make_document_game_spec(),
        config=config,
        model_client=blue_client,
        red_model_client=FakeModelClient([accept_response, accept_response]),
        referee_model_client=FakeModelClient([accept_response, accept_response]),
        max_attempts=2,
    )

    # Blue's second prompt must contain the full stdout, not the truncated version
    assert len(blue_client.tool_prompts) == 2
    second_prompt = blue_client.tool_prompts[1]
    assert long_stdout in second_prompt


# ---------------------------------------------------------------------------
# integration event — explicit field value verification
# ---------------------------------------------------------------------------

def test_integration_event_all_required_fields_with_correct_types(
    monkeypatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-int-fields"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run", "start",
            "--workspace", str(workspace),
            "--project-type", "document",
            "--artifact-id", "main-document",
            "--goal", "Write a short report.",
            "--output", "output/report.md",
            "--max-iterations", "1",
        ],
    )
    from baps.run import main as run_main
    run_main()

    lines = [
        json.loads(line)
        for line in (workspace / "blackboard" / "games.jsonl")
        .read_text(encoding="utf-8")
        .strip()
        .splitlines()
    ]
    evt = next(e for e in lines if e["event"] == "integration")

    assert evt["event"] == "integration"
    assert isinstance(evt["created_at"], str) and evt["created_at"] != ""
    assert isinstance(evt["depth"], int)
    assert isinstance(evt["proposal_id"], str) and len(evt["proposal_id"]) == 36  # UUID
    assert isinstance(evt["proposal_summary"], str) and evt["proposal_summary"] != ""
    assert isinstance(evt["state_changed"], bool)
    assert isinstance(evt["delta_type"], str) and evt["delta_type"] != ""
    # For a document project the only supported delta op is append_section
    assert evt["delta_type"] == "append_section"


# ---------------------------------------------------------------------------
# create_game no_new_game blackboard event — with failing verification context
# ---------------------------------------------------------------------------

def test_create_game_blackboard_no_new_game_with_failing_verification(
    tmp_path: Path,
) -> None:
    """create_game writes result_type=no_new_game even when a failing verification
    result is in context. Runtime-level rejection of no_new_game happens in
    _solve_gap, not inside create_game; the blackboard must faithfully record
    what the model actually returned."""

    config = {
        "workspace": tmp_path / "ws-nng-vr",
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": tmp_path / "ws-nng-vr" / "output" / "report.md",
        "max_iterations": 1,
        "spec_path": None,
    }
    state = create_state(config)
    failing_vr = VerificationResult(
        command="pytest", cwd="/tmp", exit_code=1,
        stdout="FAILED tests/test_foo.py::test_bar", stderr="", passed=False,
    )

    with pytest.raises(NoNewGameError):
        create_game(
            config,
            state,
            verification_result=failing_vr,
            model_client=FakeModelClient(
                ['{"no_new_game": true, "reason": "No gap identified."}']
            ),
        )

    games_path = config["workspace"] / "blackboard" / "games.jsonl"
    assert games_path.exists()
    entry = json.loads(games_path.read_text(encoding="utf-8").strip())
    assert entry["event"] == "create_game"
    assert entry["result_type"] == "no_new_game"
    assert entry["result"] is None
    assert "created_at" in entry
    assert entry["depth"] == 0
