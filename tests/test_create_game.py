"""Tests for create_game behavior."""
from __future__ import annotations

import inspect
import logging
from pathlib import Path

import pytest

from baps.models.models import FakeModelClient
from baps.core.run import create_state
from baps.core.run_config import RunConfig
from baps.game.engine import create_game
from baps.adapters.document_adapter import DocumentProjectAdapter
from baps.core.prompts import _render_create_game_prompt


def _make_doc_config(
    artifact_id: str = "main-document",
    goal: str = "Write a short report.",
) -> RunConfig:
    return RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id=artifact_id,
        goal=goal,
        northstar_markdown=f"# Goal\n\n{goal}",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
        spec_path=None,
    )


def test_create_game_receives_input_and_state_and_outputs_game_spec() -> None:
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
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
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
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
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
    state = create_state(config)
    # Provide one response per attempt (initial + 2 retries) so FakeModelClient doesn't run dry.
    with pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient(["not-json", "not-json", "not-json"]))


def test_create_game_invalid_json_with_debug_prints_raw_model_output(
    monkeypatch, caplog
) -> None:
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
    state = create_state(config)

    with caplog.at_level(logging.DEBUG), pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient(["not-json-output", "not-json-output", "not-json-output"]))
    assert "create_game.prompt:" in caplog.text
    assert "create_game.raw_model_output:" in caplog.text
    assert "not-json-output" in caplog.text
    assert "retrying with correction prompt" in caplog.text


def test_create_game_invalid_json_without_debug_does_not_print_raw_model_output(caplog) -> None:
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
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
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
    state = create_state(config)

    # First response is invalid JSON; the retry with the correction prompt returns valid JSON.
    game_spec = create_game(config, state, model_client=FakeModelClient(["not-json", valid_response]))

    assert game_spec.target_artifact_id == "main-document"


def test_create_game_explicit_model_client_retries_on_invalid_json() -> None:
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
    state = create_state(config)

    # Explicit model_client — correction-prompt retries still apply (same model, not a fallback).
    with pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient(["not-json", "not-json", "not-json"]))


def test_create_game_structural_validation_failure_debug_prints_raw_output(
    monkeypatch, caplog
) -> None:
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
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
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
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
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
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
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
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
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
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
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
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
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
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
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
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
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
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
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
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
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
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
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
    state = create_state(config)
    bad = "```json\n{not valid json}\n```"
    with pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient([bad, bad, bad]))


def test_create_game_missing_gamespec_fields_fails_cleanly() -> None:
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
    state = create_state(config)
    with pytest.raises(ValueError, match="must contain exactly keys"):
        create_game(
            config,
            state,
            model_client=FakeModelClient(['{"objective":"only-objective"}']),
        )


def test_create_game_target_artifact_not_in_state_fails_cleanly() -> None:
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
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

    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
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

    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
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
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="add introduction and conclusion",
        northstar_markdown="# Goal\n\nadd introduction and conclusion",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
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
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="add introduction and conclusion",
        northstar_markdown="# Goal\n\nadd introduction and conclusion",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
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
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="implement parser and tests",
        northstar_markdown="# Goal\n\nimplement parser and tests",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
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
