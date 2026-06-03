"""Tests for prompt rendering: create_game, blue, red, referee prompts for all adapters."""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import patch

import baps.state.state as state_module
from baps.adapters.coding_adapter import CodingProjectAdapter
from baps.adapters.document_adapter import DocumentProjectAdapter
from baps.core.prompts import (
    render_create_game_prompt,
    render_red_prompt,
    render_referee_prompt,
)
from baps.core.run import create_state as _create_state
from baps.core.run_config import RunConfig
from baps.game.engine import play_game
from baps.models.models import FakeModelClient, ToolCall
from baps.state.state import GameSpec, RedFinding


def create_state(config: RunConfig | dict) -> state_module.State:
    return _create_state(config if isinstance(config, RunConfig) else RunConfig(**config))


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


def _make_document_spec_and_state(success_condition: str = "A section exists."):
    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition=success_condition,
    )
    state = create_state(_make_doc_config())
    return spec, state


def _make_blue_client(*titles: str):
    return FakeModelClient(
        tool_responses=[
            ToolCall(
                name="append_section",
                arguments={
                    "artifact_id": "main-document",
                    "title": t,
                    "body": "Body text.",
                },
            )
            for t in titles
        ]
    )

    # ---------------------------------------------------------------------------
    # create_game prompt tests
    # ---------------------------------------------------------------------------


def test_create_game_prompt_forbids_markdown_fences_and_lists_required_shape() -> None:
    config = _make_doc_config()
    state = create_state(config)
    adapter = DocumentProjectAdapter()
    prompt = render_create_game_prompt(
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


def test_create_game_prompt_includes_northstar_context() -> None:
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        northstar_markdown=(
            "# Goal\n\nWrite a short report.\n\n"
            "# Required structure\n\n"
            "The report must include these sections, in order:\n\n"
            "1. Introduction\n"
            "2. Conclusion\n"
        ),
        goal="Write a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
    state = create_state(config)
    adapter = DocumentProjectAdapter()
    state_view = adapter.build_create_game_state_view(state, config)
    prompt = render_create_game_prompt(
        config,
        state,
        adapter.build_create_game_state_view(state, config),
        adapter=adapter,
    )
    assert "- state_view:" in prompt
    assert prompt.count("=== StateView Start ===") == 1
    assert prompt.count("=== StateView End ===") == 1
    assert state_view.content in prompt
    assert "must include these sections" in prompt
    assert "metadata" not in prompt
    assert "input_fingerprint" not in prompt
    assert "projection_type" not in prompt
    assert "northstar_content" not in prompt
    assert "state_view_json:" not in prompt
    assert "GAP ANALYSIS" in prompt
    assert "PRIORITIZE" in prompt
    assert "DECIDE" in prompt
    assert "SELF-CONTAIN" in prompt
    assert "decompose" in prompt
    assert "name the gap being closed" in prompt
    assert "verifiable from the artifact alone" in prompt
    assert "Do not artificially split a coherent gap into multiple games" in prompt
    assert '{"kind": "no_new_game", "reason": "..."}' in prompt
    assert "state_json:" not in prompt
    assert "mandatory_sections_json" not in prompt
    assert "next_missing_required_section" not in prompt


def test_create_game_prompt_includes_northstar_update_needed_instruction() -> None:
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        northstar_markdown="# Goal\n\nWrite a short report.",
        goal="Write a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
    state = create_state(config)
    adapter = DocumentProjectAdapter()
    prompt = render_create_game_prompt(
        config,
        state,
        adapter.build_create_game_state_view(state, config),
        adapter=adapter,
    )

    assert '"kind": "northstar_update_needed"' in prompt
    assert '"rationale"' in prompt
    assert '"proposed_northstar"' in prompt
    assert "cannot satisfy NorthStar without changing NorthStar itself" in prompt
    assert "complete updated NorthStar content" in prompt


def test_create_game_prompt_includes_context_chain_when_provided() -> None:
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        northstar_markdown="# Goal\n\nWrite a report.",
        goal="Write a report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
    state = create_state(config)
    adapter = DocumentProjectAdapter()
    state_view = adapter.build_create_game_state_view(state, config)
    prompt = render_create_game_prompt(
        config,
        state,
        state_view,
        adapter=adapter,
        context_chain=("Implement auth subsystem", "Implement JWT token generation"),
    )
    assert "Parent planning context" in prompt
    assert "[1] Implement auth subsystem" in prompt
    assert "[2] Implement JWT token generation" in prompt
    assert "[current] Plan within this scope" in prompt


def test_create_game_prompt_no_context_block_when_chain_empty() -> None:
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        northstar_markdown="# Goal\n\nWrite a report.",
        goal="Write a report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
    state = create_state(config)
    adapter = DocumentProjectAdapter()
    state_view = adapter.build_create_game_state_view(state, config)
    prompt = render_create_game_prompt(
        config,
        state,
        state_view,
        adapter=adapter,
    )
    assert "Parent planning context" not in prompt
    assert "[current]" not in prompt


def test_coding_create_game_prompt_includes_multi_file_guidance() -> None:
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="coding",
        artifact_id="main-codebase",
        language="python",
        goal="Implement Fibonacci with tests",
        northstar_markdown="# Goal\n\nImplement Fibonacci with tests",
        output_path=Path(".baps-workspace/output/project"),
        max_iterations=2,
    )
    state = create_state(config)
    adapter = CodingProjectAdapter()
    state_view = adapter.build_create_game_state_view(state, config)
    prompt = render_create_game_prompt(
        config=config,
        state=state,
        state_view=state_view,
        adapter=adapter,
    )
    assert "write_files" in prompt
    assert "Group logically related files" in prompt
    assert "Prefer production files under src/" in prompt


def test_coding_create_game_prompt_includes_previous_verification_evidence() -> None:
    from baps.adapters.project_adapter import VerificationResult

    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="coding",
        artifact_id="main-codebase",
        language="python",
        goal="Implement Fibonacci with tests",
        northstar_markdown="# Goal\n\nImplement Fibonacci with tests",
        output_path=Path(".baps-workspace/output/project"),
        max_iterations=2,
    )
    state = create_state(config)
    adapter = CodingProjectAdapter()
    state_view = adapter.build_create_game_state_view(state, config)
    verification = VerificationResult(
        command="uv run pytest",
        cwd="/tmp/project",
        exit_code=2,
        stdout="ModuleNotFoundError: No module named 'src'",
        stderr="",
        passed=False,
    )
    prompt = render_create_game_prompt(
        config=config,
        state=state,
        state_view=state_view,
        verification_result=verification,
        adapter=adapter,
    )
    assert "previous_verification_result_json" in prompt
    assert "Use this as evidence from the previous exported state only." in prompt
    assert "If evidence shows import/layout errors, prefer a repair game" in prompt


def test_document_create_game_prompt_has_no_verification_block_by_default() -> None:
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write report",
        northstar_markdown="# Goal\n\nWrite report",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
    state = create_state(config)
    adapter = DocumentProjectAdapter()
    state_view = adapter.build_create_game_state_view(state, config)
    prompt = render_create_game_prompt(
        config=config,
        state=state,
        state_view=state_view,
        adapter=adapter,
    )
    assert "previous_verification_result_json" not in prompt

    # ---------------------------------------------------------------------------
    # Blue prompt tests
    # ---------------------------------------------------------------------------


def test_blue_prompt_includes_state_view_and_gamespec() -> None:
    import baps.adapters.project_adapter as project_adapter_module

    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
    )
    state = create_state(_make_doc_config())
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    prompt = project_adapter_module.render_blue_prompt_core(
        state_view=state_view,
        game_spec=spec,
        attempt_number=1,
        previous_feedback=None,
    )
    assert "- state_view:" in prompt
    assert "=== StateView Start ===" in prompt
    assert "--- State Artifacts ---" in prompt
    assert "attempt_number: 1" in prompt
    assert "previous_feedback_json: null" in prompt
    assert "objective:" in prompt
    assert "target_artifact_id:" in prompt
    assert "allowed_delta_type:" in prompt
    assert "success_condition:" in prompt
    assert "Produce exactly one delta JSON object allowed by GameSpec.allowed_delta_type." in prompt
    assert "Use StateView as the current artifact context." in prompt
    assert "Do not duplicate existing artifact content." in prompt
    assert "Do not rewrite unrelated existing state." in prompt
    assert "Do not emit placeholder or filler content." in prompt
    assert "If previous_feedback_json contains validation errors, repair those exact errors in this attempt." in prompt
    assert "Do not repeat outputs that fail previously reported validation constraints." in prompt
    assert "When attempt_number > 1, treat previous_feedback_json as mandatory correction requirements." in prompt
    assert "Document delta rules:" not in prompt
    assert "append_section" not in prompt
    assert "Introduction" not in prompt
    assert "Conclusion" not in prompt
    assert "blue_view_json:" not in prompt
    assert "state_json:" not in prompt


def test_blue_prompt_and_source_do_not_hardcode_project_policy_literals() -> None:
    import baps.adapters.project_adapter as project_adapter_module

    spec = GameSpec(
        objective="Add Overview section",
        target_artifact_id="doc-a",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Overview section exists.",
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="doc-a", sections=()),),
    )
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    prompt = project_adapter_module.render_blue_prompt_core(
        state_view=state_view, game_spec=spec, attempt_number=1, previous_feedback=None
    )
    assert '"artifact_id": "<game_spec.target_artifact_id>"' not in prompt
    assert '"title": "<section title>"' not in prompt
    assert "Do not duplicate existing artifact content." in prompt
    assert "Do not emit placeholder or filler content." in prompt
    src = inspect.getsource(project_adapter_module.render_blue_prompt_core)
    assert '"artifact_id": "main-document"' not in src
    assert '"title": "Introduction"' not in src


def test_document_blue_prompt_contains_document_specific_shape_rules() -> None:
    spec = GameSpec(
        objective="Add Overview section",
        target_artifact_id="doc-a",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Overview section exists.",
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="doc-a", sections=()),),
    )
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    prompt = DocumentProjectAdapter().render_blue_prompt(state_view, spec, 1, None)
    assert "Document delta rules:" in prompt
    assert "section.title and section.body must be non-empty strings." in prompt
    assert '"artifact_id": "<game_spec.target_artifact_id>"' in prompt
    assert '"operation": "append_section"' in prompt
    assert 'Invalid example, do not output: "body": ""' in prompt


def test_document_blue_prompt_includes_modify_section_shape() -> None:
    config = _make_doc_config()
    state = create_state(config)
    adapter = DocumentProjectAdapter()
    state_view = adapter.build_state_view(
        state,
        state_module.GameSpec(
            objective="Test",
            target_artifact_id="main-document",
            allowed_delta_type="DeltaDocumentState",
            success_condition="ok",
        ),
    )
    prompt = adapter.render_blue_prompt(
        state_view=state_view,
        game_spec=state_module.GameSpec(
            objective="Test",
            target_artifact_id="main-document",
            allowed_delta_type="DeltaDocumentState",
            success_condition="ok",
        ),
        attempt_number=1,
        previous_feedback=None,
    )
    assert "modify_section" in prompt
    assert "section_title" in prompt
    assert "new_body" in prompt


def test_blue_prompt_includes_context_chain_from_game_spec() -> None:
    from baps.adapters.project_adapter import render_blue_prompt_core
    from baps.northstar.northstar_projection import ProjectionType, StateView

    game_spec = GameSpec(
        objective="Write jwt_utils.py",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="jwt_utils.py exists",
        context_chain=("Auth subsystem missing", "JWT generation missing"),
    )
    state_view = StateView(
        id="sv-1",
        projection_type=ProjectionType.NORTH_STAR,
        content="=== StateView Start ===\ncontent\n=== StateView End ===",
        input_fingerprint="fp-1",
    )
    prompt = render_blue_prompt_core(state_view, game_spec, 1, None)
    assert "Planning context (coarsest → finest scope):" in prompt
    assert "[1] Auth subsystem missing" in prompt
    assert "[2] JWT generation missing" in prompt


def test_blue_prompt_no_context_block_when_chain_empty() -> None:
    from baps.adapters.project_adapter import render_blue_prompt_core
    from baps.northstar.northstar_projection import ProjectionType, StateView

    game_spec = GameSpec(
        objective="Write something",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="file exists",
    )
    state_view = StateView(
        id="sv-1",
        projection_type=ProjectionType.NORTH_STAR,
        content="=== StateView Start ===\ncontent\n=== StateView End ===",
        input_fingerprint="fp-1",
    )
    prompt = render_blue_prompt_core(state_view, game_spec, 1, None)
    assert "Planning context" not in prompt


def test_coding_blue_prompt_supplement_prefers_src_and_pytest_layout() -> None:
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(id="main-codebase", files=()),),
    )
    spec = GameSpec(
        objective="Implement Fibonacci with tests",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="Working code and tests exist",
    )
    view = CodingProjectAdapter().build_state_view(state, spec)
    prompt = CodingProjectAdapter().render_blue_prompt(
        view,
        spec,
        attempt_number=1,
        previous_feedback=None,
    )
    assert "Prefer production code under src/." in prompt
    assert "Prefer tests under tests/." in prompt
    assert "tests/test_*.py" in prompt

    # ---------------------------------------------------------------------------
    # Red prompt tests
    # ---------------------------------------------------------------------------


def test_red_prompt_includes_success_condition_met_and_findings_fields() -> None:
    import baps.game.engine as game_module

    captured: dict[str, object] = {}
    original = render_red_prompt

    def _capture(*args, **kwargs):
        result = original(*args, **kwargs)
        captured["prompt"] = result
        return result

    spec, state = _make_document_spec_and_state()
    with patch.object(game_module, "render_red_prompt", _capture):
        play_game(state, spec, model_client=_make_blue_client("Introduction"))
    prompt = str(captured["prompt"])
    assert "success_condition_met" in prompt
    assert "findings" in prompt


def test_red_prompt_includes_success_condition(monkeypatch) -> None:
    captured: dict[str, object] = {}
    original = render_red_prompt

    def _capture(*args, **kwargs):
        result = original(*args, **kwargs)
        captured["prompt"] = result
        return result

    monkeypatch.setattr("baps.game.engine.render_red_prompt", _capture)
    success_condition = "Unique success_condition string for red prompt contract test."
    spec, state = _make_document_spec_and_state(success_condition)
    play_game(state, spec, model_client=_make_blue_client("Introduction"))
    assert "prompt" in captured
    assert success_condition in str(captured["prompt"])


def test_red_prompt_intro_only_guides_revise_for_intro_and_conclusion_success_condition() -> None:
    spec = GameSpec(
        objective="Write a short report.",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Document must include both an Introduction section and a Conclusion section.",
    )
    state = create_state(_make_doc_config())
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=state_module.AppendSectionDelta(section=state_module.Section(title="Introduction", body="Intro only")),
    )
    prompt = render_red_prompt(state_view, spec, delta)
    assert "success_condition:" in prompt
    assert "Document must include both an Introduction section and a Conclusion section." in prompt
    assert "Use revise only when the candidate is promising but needs improvement" in prompt
    assert "Do NOT reject or revise merely because state differs from the original state." in prompt


def test_coding_red_prompt_includes_verification_evidence_when_provided() -> None:
    from baps.adapters.project_adapter import VerificationResult

    spec = GameSpec(
        objective="Write tests/test_fibonacci.py",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="Tests pass",
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(
                    state_module.CodeFile(
                        path="src/fibonacci.py",
                        content="def fibonacci(n):\n    return n\n",
                    ),
                ),
            ),
        ),
    )
    state_view = CodingProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaCodingState(
        artifact_id="main-codebase",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(
                path="tests/test_fibonacci.py",
                content="def test_smoke():\n    assert True\n",
            )
        ),
    )
    verification = VerificationResult(
        command="uv run pytest",
        cwd="/tmp/project",
        exit_code=0,
        stdout="1 passed",
        stderr="",
        passed=True,
    )
    adapter = CodingProjectAdapter()
    supplement = adapter.render_red_prompt_supplement(state_view, spec, delta, verification)
    prompt = render_red_prompt(
        state_view,
        spec,
        delta,
        verification_result=verification,
        prompt_supplement=supplement,
    )
    assert "verification_result_json:" in prompt
    assert '"exit_code": 0' in prompt
    assert '"passed": true' in prompt
    assert "If verification passed, treat that as strong evidence toward accept." in prompt
    assert "If pytest discovered tests, do not claim test files are empty." in prompt


def test_document_prompts_do_not_include_verification_evidence_by_default() -> None:
    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Any success condition",
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="main-document", sections=()),),
    )
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=state_module.AppendSectionDelta(section=state_module.Section(title="Intro", body="Body")),
    )
    red = RedFinding(disposition="accept", rationale="ok")
    red_prompt = render_red_prompt(state_view, spec, delta)
    referee_prompt = render_referee_prompt(state_view, spec, delta, red)
    assert "verification_result_json:" not in red_prompt
    assert "verification_result_json:" not in referee_prompt


def test_document_red_referee_prompts_do_not_include_coding_guidance() -> None:
    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Any success condition",
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="main-document", sections=()),),
    )
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=state_module.AppendSectionDelta(section=state_module.Section(title="Intro", body="Body")),
    )
    red = RedFinding(disposition="accept", rationale="ok")
    red_prompt = render_red_prompt(state_view, spec, delta)
    referee_prompt = render_referee_prompt(state_view, spec, delta, red)
    for prompt in (red_prompt, referee_prompt):
        assert "target_artifact_id is the artifact id, not a file path." not in prompt
        assert "Pytest tests containing assert statements are not empty." not in prompt
        assert "Do not reject tests as empty if assertions are present." not in prompt


def test_coding_red_referee_prompts_include_coding_guidance() -> None:
    spec = GameSpec(
        objective="Write tests",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests exist",
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(id="main-codebase", files=()),),
    )
    adapter = CodingProjectAdapter()
    state_view = adapter.build_state_view(state, spec)
    delta = state_module.DeltaCodingState(
        artifact_id="main-codebase",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(path="tests/test_fibonacci.py", content="assert True")
        ),
    )
    red = RedFinding(disposition="accept", rationale="ok")
    red_supplement = adapter.render_red_prompt_supplement(state_view, spec, delta, verification_result=None)
    referee_supplement = adapter.render_referee_prompt_supplement(state_view, spec, delta, verification_result=None)
    red_prompt = render_red_prompt(state_view, spec, delta, prompt_supplement=red_supplement)
    referee_prompt = render_referee_prompt(state_view, spec, delta, red, prompt_supplement=referee_supplement)
    for prompt in (red_prompt, referee_prompt):
        assert "target_artifact_id is the artifact id, not a file path." in prompt
        assert "Pytest tests containing assert statements are not empty." in prompt
        assert "Do not reject tests as empty if assertions are present." in prompt
        assert (
            "If success_condition only requires non-empty tests, basic asserted tests satisfy that condition." in prompt
        )


def test_red_and_referee_prompts_do_not_treat_state_mutation_alone_as_failure() -> None:
    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Any success condition.",
    )
    state = create_state(_make_doc_config())
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=state_module.AppendSectionDelta(section=state_module.Section(title="Introduction", body="Body")),
    )
    red_prompt = render_red_prompt(state_view, spec, delta)
    referee_prompt = render_referee_prompt(
        state_view,
        spec,
        delta,
        RedFinding(disposition="accept", rationale="ok"),
    )
    assert "Do NOT reject or revise merely because state differs from the original state." in red_prompt
    assert "Do NOT choose revise merely because state changed." in referee_prompt
    assert "candidate DeltaDocumentState" not in red_prompt
    assert "pytest discovered tests" not in red_prompt
    assert "pytest discovered tests" not in referee_prompt
    assert "Evaluate the candidate DeltaState" in red_prompt


def test_run_core_prompt_source_has_no_coding_specific_red_referee_guidance() -> None:
    run_source = Path("src/baps/core/run.py").read_text(encoding="utf-8")
    assert "target_artifact_id is the artifact id, not a file path." not in run_source
    assert "Pytest tests containing assert statements are not empty." not in run_source
    assert "Do not reject tests as empty if assertions are present." not in run_source

    # ---------------------------------------------------------------------------
    # Referee prompt tests
    # ---------------------------------------------------------------------------


def test_referee_prompt_includes_red_override_and_improvement_hints_fields() -> None:
    import baps.game.engine as game_module

    captured: dict[str, object] = {}
    original = render_referee_prompt

    def _capture(*args, **kwargs):
        result = original(*args, **kwargs)
        captured["prompt"] = result
        return result

    spec, state = _make_document_spec_and_state()
    with patch.object(game_module, "render_referee_prompt", _capture):
        play_game(state, spec, model_client=_make_blue_client("Introduction"))
    prompt = str(captured["prompt"])
    assert "red_override" in prompt
    assert "improvement_hints" in prompt


def test_referee_prompt_includes_success_condition_and_red_rationale(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    original = render_referee_prompt

    def _capture(*args, **kwargs):
        result = original(*args, **kwargs)
        captured["prompt"] = result
        return result

    monkeypatch.setattr("baps.game.engine.render_referee_prompt", _capture)
    success_condition = "Unique success_condition string for referee prompt contract test."
    spec, state = _make_document_spec_and_state(success_condition)
    red_rationale = "Unique red rationale for referee prompt test."
    play_game(
        state,
        spec,
        model_client=_make_blue_client("Introduction"),
        red_model_client=FakeModelClient([f'{{"disposition":"accept","rationale":"{red_rationale}"}}']),
    )
    prompt = str(captured["prompt"])
    assert success_condition in prompt
    assert red_rationale in prompt


def test_referee_prompt_intro_and_conclusion_guides_accept_policy() -> None:
    spec = GameSpec(
        objective="Write a short report.",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Document must include both an Introduction section and a Conclusion section.",
    )
    state = create_state(_make_doc_config())
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=state_module.AppendSectionDelta(
            section=state_module.Section(
                title="Introduction and Conclusion",
                body="Introduction... Conclusion...",
            )
        ),
    )
    red = RedFinding(disposition="accept", rationale="satisfies success condition")
    prompt = render_referee_prompt(state_view, spec, delta, red)
    assert (
        "accept: objective/success_condition are satisfied enough for this game AND Red has no unresolved material findings."
        in prompt
    )
    assert (
        "revise: objective/success_condition are only partially satisfied OR Red has unresolved improvements that should be addressed."
        in prompt
    )
    assert "reject: candidate is invalid, harmful, incoherent, or wrong direction." in prompt
    assert "Do NOT choose revise merely because state changed." in prompt


def test_referee_prompt_declares_game_local_authority_and_not_final_integration() -> None:
    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Any success condition.",
    )
    state = create_state(_make_doc_config())
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=state_module.AppendSectionDelta(section=state_module.Section(title="Introduction", body="Body")),
    )
    red = RedFinding(disposition="accept", rationale="ok")
    prompt = render_referee_prompt(state_view, spec, delta, red)
    assert "You are the game-local authority for this PlayGame decision." in prompt
    assert "You do NOT decide final State integration; integration is decided later by Integrator." in prompt


def test_referee_prompt_uses_red_material_findings_in_decision_policy() -> None:
    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Any success condition.",
    )
    state = create_state(_make_doc_config())
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=state_module.AppendSectionDelta(section=state_module.Section(title="Introduction", body="Body")),
    )
    red = RedFinding(disposition="revise", rationale="missing conclusion")
    prompt = render_referee_prompt(state_view, spec, delta, red)
    assert "Red has no unresolved material findings" in prompt
    assert "Red has unresolved improvements that should be addressed." in prompt


def test_coding_referee_prompt_includes_failing_verification_evidence() -> None:
    from baps.adapters.project_adapter import VerificationResult

    spec = GameSpec(
        objective="Write tests/test_fibonacci.py",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="Tests pass",
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(id="main-codebase", files=()),),
    )
    state_view = CodingProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaCodingState(
        artifact_id="main-codebase",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(
                path="tests/test_fibonacci.py",
                content="def test_smoke():\n    assert False\n",
            )
        ),
    )
    red = RedFinding(disposition="revise", rationale="needs fix")
    verification = VerificationResult(
        command="uv run pytest",
        cwd="/tmp/project",
        exit_code=1,
        stdout="1 failed",
        stderr="traceback",
        passed=False,
    )
    prompt = render_referee_prompt(state_view, spec, delta, red, verification_result=verification)
    assert "verification_result_json:" in prompt
    assert '"exit_code": 1' in prompt
    assert '"stdout": "1 failed"' in prompt
    assert '"stderr": "traceback"' in prompt
    assert "If verification failed, reason from exit_code/stdout/stderr evidence." in prompt


def test_red_prompt_state_view_json_excludes_metadata_and_file_content() -> None:
    spec = GameSpec(
        objective="Write tests",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests exist",
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(state_module.CodeFile(path="src/main.py", content="SECRET_RED_FILE_CONTENT"),),
            ),
        ),
    )
    state_view = CodingProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaCodingState(
        artifact_id="main-codebase",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(path="tests/test_main.py", content="assert True")
        ),
    )
    prompt = render_red_prompt(state_view, spec, delta)
    assert "state_view_json:" in prompt
    assert state_view.id in prompt
    assert state_view.input_fingerprint in prompt
    assert "SECRET_RED_FILE_CONTENT" not in prompt
    assert '"metadata"' not in prompt
    assert '"projection_type"' not in prompt


def test_referee_prompt_state_view_json_excludes_metadata_and_file_content() -> None:
    spec = GameSpec(
        objective="Write tests",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests exist",
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(state_module.CodeFile(path="src/main.py", content="SECRET_REFEREE_FILE_CONTENT"),),
            ),
        ),
    )
    state_view = CodingProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaCodingState(
        artifact_id="main-codebase",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(path="tests/test_main.py", content="assert True")
        ),
    )
    red = RedFinding(disposition="accept", rationale="ok")
    prompt = render_referee_prompt(state_view, spec, delta, red)
    assert "state_view_json:" in prompt
    assert state_view.id in prompt
    assert state_view.input_fingerprint in prompt
    assert "SECRET_REFEREE_FILE_CONTENT" not in prompt
    assert '"metadata"' not in prompt
    assert '"projection_type"' not in prompt


def test_red_referee_prompts_forbid_goalpost_drift_language() -> None:
    spec = GameSpec(
        objective="Write tests/test_example.py with non-empty pytest tests.",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="Artifact contains tests/test_example.py with non-empty pytest tests.",
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(id="main-codebase", files=()),),
    )
    state_view = CodingProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaCodingState(
        artifact_id="main-codebase",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(
                path="tests/test_example.py",
                content="def test_smoke():\n    assert True\n",
            )
        ),
    )
    red = RedFinding(disposition="accept", rationale="ok")
    red_prompt = render_red_prompt(state_view, spec, delta)
    referee_prompt = render_referee_prompt(state_view, spec, delta, red)
    for prompt in (red_prompt, referee_prompt):
        assert "Treat GameSpec.success_condition as authoritative acceptance contract." in prompt
        assert "Do not invent stronger requirements than objective/success_condition." in prompt
        assert (
            "Do not add stricter standards such as 'more comprehensive', 'better coverage', "
            "'stronger tests', or 'more complete' unless those words (or equivalent requirements) "
            "are explicit in GameSpec."
        ) in prompt
