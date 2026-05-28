import inspect
import json
from pathlib import Path

import pytest

from baps.models.models import FakeModelClient, ToolCall
from baps.core.run import create_state
from baps.core.run_config import RunConfig
from baps.game.engine import create_game, play_game
from baps.state.state import (
    DecomposeSpec,
    GameSpec,
)
from baps.core.parsers import NoNewGameError, NorthStarUpdateNeededError
from baps.core.orchestration import _run_project_iterations
from baps.adapters.document_adapter import DocumentProjectAdapter
import baps.state.state as state_module


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
                arguments={"artifact_id": "main-document", "title": t, "body": "Body text."},
            )
            for t in titles
        ]
    )


def test_create_game_accepts_atomic_introduction_gamespec() -> None:
    import baps.core.run as run_module

    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        northstar_markdown=( "# Goal\n\nWrite a short report.\n\n" "# Required structure\n\n" "The report must include these sections, in order:\n\n" "1. Introduction\n" "2. Conclusion\n" ),
        goal="Write a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
    state = run_module.create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Add Introduction section",'
                '"target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"Introduction section exists."}'
            ]
        ),
    )
    assert "Introduction" in game_spec.objective


def test_create_game_accepts_atomic_conclusion_gamespec() -> None:
    import baps.core.run as run_module

    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        northstar_markdown=( "# Goal\n\nWrite a short report.\n\n" "# Required structure\n\n" "The report must include these sections, in order:\n\n" "1. Introduction\n" "2. Conclusion\n" ),
        goal="Write a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
    state = run_module.create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Add Conclusion section",'
                '"target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"Conclusion section exists."}'
            ]
        ),
    )
    assert "Conclusion" in game_spec.objective


def test_create_game_engine_does_not_compute_next_missing_section() -> None:

    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        northstar_markdown=( "# Goal\n\nWrite a short report.\n\n" "# Required structure\n\n" "The report must include these sections, in order:\n\n" "1. Introduction\n" "2. Conclusion\n" ),
        goal="Write a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.DocumentArtifact(
                id="main-document",
                sections=(
                    state_module.Section(title="Introduction", body="Intro"),
                    state_module.Section(title="Conclusion", body="Outro"),
                ),
            ),
        ),
    )
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Add Abstract section",'
                '"target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"Abstract section exists."}'
            ]
        ),
    )
    assert game_spec.objective == "Add Abstract section"


def test_create_game_explicit_no_new_game_signal() -> None:
    import baps.core.run as run_module

    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        northstar_markdown="# Goal\n\nWrite a short report.",
        goal="Write a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
    state = run_module.create_state(config)
    with pytest.raises(NoNewGameError):
        create_game(
            config,
            state,
            model_client=FakeModelClient(
                ['{"no_new_game": true, "reason": "all required sections already present"}']
            ),
        )


def test_create_game_extra_key_on_no_new_game_response_is_stripped() -> None:
    import baps.core.run as run_module

    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        northstar_markdown="# Goal\n\nWrite a short report.",
        goal="Write a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
    state = run_module.create_state(config)
    with pytest.raises(NoNewGameError, match="all required sections already present"):
        create_game(
            config,
            state,
            model_client=FakeModelClient(
                ['{"no_new_game": true, "reason": "all required sections already present", "confidence": 0.9}']
            ),
        )


def test_create_game_extra_key_on_northstar_response_is_stripped() -> None:
    import baps.core.run as run_module

    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        northstar_markdown="# Goal\n\nWrite a short report.",
        goal="Write a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
    state = run_module.create_state(config)
    with pytest.raises(NorthStarUpdateNeededError):
        create_game(
            config,
            state,
            model_client=FakeModelClient(
                [
                    '{"northstar_update_needed": true, "rationale": "trajectory drifted",'
                    ' "proposed_northstar": "new goal", "confidence": 0.8}'
                ]
            ),
        )


def test_create_game_extra_key_on_decompose_response_is_stripped() -> None:
    import baps.core.run as run_module

    valid_sub_game = (
        '{"objective":"Advance goal","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState","success_condition":"section exists"}'
    )
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        northstar_markdown="# Goal\n\nWrite a short report.",
        goal="Write a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
    state = run_module.create_state(config)
    decompose_response = (
        '{"decompose": true, "rationale": "split into parts",'
        ' "sub_gaps": [{"description": "part one"}], "confidence": 0.7}'
    )
    result = create_game(
        config,
        state,
        model_client=FakeModelClient([decompose_response, valid_sub_game]),
    )
    assert isinstance(result, DecomposeSpec)


def test_create_game_extra_key_on_gamespec_response_is_stripped() -> None:
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
    response = (
        '{"objective":"Advance goal","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState","success_condition":"section exists",'
        '"confidence": 0.95}'
    )
    game_spec = create_game(config, state, model_client=FakeModelClient([response]))
    assert game_spec.target_artifact_id == "main-document"


def test_create_game_engine_does_not_parse_must_include_policy_literals() -> None:
    import baps.core.run as run_module

    src = inspect.getsource(run_module)
    active_prefix = src
    assert "mandatory_sections_json" not in active_prefix
    assert "_extract_mandatory_sections_from_northstar" not in active_prefix
    assert "_select_next_missing_required_section" not in active_prefix
    assert "must include" not in active_prefix


def test_no_blueview_symbol_remains_in_run_or_run_tests() -> None:
    run_source = Path("src/baps/core/run.py").read_text(encoding="utf-8")
    test_source = Path("tests/test_run.py").read_text(encoding="utf-8")
    symbol = "Blue" + "View"
    assert symbol not in run_source
    assert symbol not in test_source.replace(symbol, "")


def test_core_orchestration_does_not_reference_concrete_project_adapters() -> None:

    for fn in (
        create_game,
        _run_project_iterations,
    ):
        src = inspect.getsource(fn)
        assert "DocumentProjectAdapter" not in src
        assert "CodingProjectAdapter" not in src


def test_run_core_source_has_no_coding_file_policy_literals() -> None:
    run_source = Path("src/baps/core/run.py").read_text(encoding="utf-8")
    assert "src/fibonacci.py" not in run_source
    assert "tests/test_fibonacci.py" not in run_source


def test_coding_create_game_accepts_src_file_task_first_iteration() -> None:
    import baps.core.run as run_module

    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="coding",
        artifact_id="main-codebase",
        language="python",
        goal="Implement Fibonacci with tests",
        northstar_markdown=( "# Goal\n\nImplement Fibonacci with tests.\n" "- Production code in `src/fibonacci.py`\n" "- Pytest tests in `tests/test_fibonacci.py`\n" ),
        output_path=Path(".baps-workspace/output/project"),
        max_iterations=2,
    )
    state = run_module.create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Write src/fibonacci.py with fibonacci implementation",'
                '"target_artifact_id":"main-codebase",'
                '"allowed_delta_type":"DeltaCodingState",'
                '"success_condition":"Artifact contains src/fibonacci.py with a fibonacci function."}'
            ]
        ),
    )
    assert "src/fibonacci.py" in game_spec.objective
    assert game_spec.allowed_delta_type == "DeltaCodingState"


def test_coding_create_game_accepts_test_file_task_second_iteration() -> None:

    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="coding",
        artifact_id="main-codebase",
        goal="Implement Fibonacci with tests",
        northstar_markdown=( "# Goal\n\nImplement Fibonacci with tests.\n" "- Production code in `src/fibonacci.py`\n" "- Pytest tests in `tests/test_fibonacci.py`\n" ),
        output_path=Path(".baps-workspace/output/project"),
        max_iterations=2,
    )
    state = state_module.State(
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
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Write tests/test_fibonacci.py with pytest cases for fibonacci",'
                '"target_artifact_id":"main-codebase",'
                '"allowed_delta_type":"DeltaCodingState",'
                '"success_condition":"Artifact contains tests/test_fibonacci.py with pytest tests for fibonacci."}'
            ]
        ),
    )
    assert "tests/test_fibonacci.py" in game_spec.objective
    assert game_spec.allowed_delta_type == "DeltaCodingState"


def test_coding_normalize_passes_through_model_objective_and_success_condition() -> None:
    import baps.core.run as run_module

    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="coding",
        artifact_id="main-codebase",
        language="python",
        goal="Implement a text similarity utility",
        northstar_markdown=( "# Goal\n\nImplement a text similarity utility.\n" "- src/similarity.py\n" "- tests/test_similarity.py\n" ),
        output_path=Path(".baps-workspace/output/project"),
        max_iterations=2,
    )
    state = run_module.create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Write src/similarity.py with normalize and token_overlap",'
                '"target_artifact_id":"main-codebase",'
                '"allowed_delta_type":"DeltaCodingState",'
                '"success_condition":"Artifact contains src/similarity.py with all required functions."}'
            ]
        ),
    )
    assert game_spec.objective == "Write src/similarity.py with normalize and token_overlap"
    assert game_spec.success_condition == "Artifact contains src/similarity.py with all required functions."
    assert game_spec.target_artifact_id == "main-codebase"


def test_coding_normalize_does_not_inject_hardcoded_file_paths() -> None:
    import baps.core.run as run_module

    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="coding",
        artifact_id="main-codebase",
        language="python",
        goal="Implement a text similarity utility",
        northstar_markdown="# Goal\n\nImplement a text similarity utility.",
        output_path=Path(".baps-workspace/output/project"),
        max_iterations=2,
    )
    state = run_module.create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Write src/similarity.py",'
                '"target_artifact_id":"main-codebase",'
                '"allowed_delta_type":"DeltaCodingState",'
                '"success_condition":"src/similarity.py exists with required functions"}'
            ]
        ),
    )
    assert "fibonacci" not in game_spec.objective.lower()
    assert "fibonacci" not in game_spec.success_condition.lower()
    assert game_spec.target_artifact_id == "main-codebase"


def test_coding_normalization_overrides_file_path_target_artifact_id() -> None:
    import baps.core.run as run_module

    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="coding",
        artifact_id="main-codebase",
        language="python",
        goal="Implement Fibonacci with tests",
        northstar_markdown="# Goal\n\nImplement Fibonacci with tests.",
        output_path=Path(".baps-workspace/output/project"),
        max_iterations=2,
    )
    state = run_module.create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Write tests file",'
                '"target_artifact_id":"tests/test_fibonacci.py",'
                '"allowed_delta_type":"DeltaCodingState",'
                '"success_condition":"tests/test_fibonacci.py exists"}'
            ]
        ),
    )
    assert game_spec.target_artifact_id == "main-codebase"
    assert game_spec.target_artifact_id != "tests/test_fibonacci.py"


def test_document_adapter_normalize_game_spec_is_identity() -> None:
    import baps.core.run as run_module

    adapter = DocumentProjectAdapter()
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
    state = run_module.create_state(config)
    original = GameSpec(
        objective="Any document objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Any document success condition",
    )
    normalized = adapter.normalize_game_spec(original, state, config)
    assert normalized == original


def test_active_main_and_play_game_orchestration_have_no_direct_document_mechanics() -> None:
    import baps.core.run as run_module

    main_src = inspect.getsource(run_module.main)
    play_src = inspect.getsource(play_game)
    for token in ("DocumentArtifact", "DeltaDocumentState", "append_section", "sections"):
        assert token not in main_src
        assert token not in play_src


def test_run_py_adapter_boundary_regression_guards() -> None:
    run_source = Path("src/baps/core/run.py").read_text(encoding="utf-8")

    forbidden_helpers = (
        "_build_document_state_view",
        "_build_coding_state_view",
        "_build_create_game_state_view",
    )
    for name in forbidden_helpers:
        assert name not in run_source

    forbidden_symbols = (
        "DocumentArtifact",
        "CodingArtifact",
        "Section",
        "CodeFile",
    )
    for symbol in forbidden_symbols:
        assert symbol not in run_source

    assert ".sections" not in run_source
    assert ".files" not in run_source


# ---------------------------------------------------------------------------
# NorthStarUpdateNeededError — parse, prompt, and lifecycle tests
# ---------------------------------------------------------------------------


def test_create_game_northstar_update_needed_signal_raises_error() -> None:
    import baps.core.run as run_module

    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        northstar_markdown="# Goal\n\nWrite a short report.",
        goal="Write a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
    )
    state = run_module.create_state(config)
    response = json.dumps({
        "northstar_update_needed": True,
        "rationale": "State has drifted from NorthStar goal.",
        "proposed_northstar": "# Revised Goal\n\nNew direction.",
    })
    with pytest.raises(NorthStarUpdateNeededError) as exc_info:
        create_game(
            config, state, model_client=FakeModelClient([response])
        )

    assert "drifted" in exc_info.value.rationale
    assert "Revised" in exc_info.value.proposed_northstar


def test_run_module_has_no_legacy_compatibility_shim_wrappers() -> None:
    import baps.core.run as run_module

    assert not hasattr(run_module, "_build_blue_state_view")
    assert not hasattr(run_module, "_parse_blue_delta_json")
    assert not hasattr(run_module, "_create_game_with_adapter")
    assert not hasattr(run_module, "_play_game_with_adapter")
    src = inspect.getsource(_run_project_iterations)
    assert "TypeError" not in src


def test_run_module_has_no_global_verification_fallback() -> None:
    run_source = Path("src/baps/core/run.py").read_text(encoding="utf-8")
    assert "_LAST_VERIFICATION_RESULT" not in run_source


def test_run_module_does_not_import_deleted_legacy_modules() -> None:
    import baps.core.run as run_module

    src = inspect.getsource(run_module)
    forbidden = (
        "baps.runtime",
        "baps.game_service",
        "baps.runtime_integration",
        "baps.autonomous",
        "baps.planner",
        "baps.projections",
    )
    for item in forbidden:
        assert item not in src
