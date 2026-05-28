from pathlib import Path

from baps.adapters.project_adapter import VerificationResult
from baps.state.state import GameSpec
from baps.adapters.coding_adapter import CodingProjectAdapter
from baps.adapters.document_adapter import DocumentProjectAdapter
import baps.state.state as state_module
def test_coding_create_state_creates_coding_artifact() -> None:
    import baps.core.run as run_module

    state = run_module.create_state(
        {
            "workspace": Path(".baps-workspace"),
            "project_type": "coding",
            "artifact_id": "main-codebase",
            "language": "python",
            "goal": "Implement Fibonacci",
            "northstar_markdown": "# Goal\n\nImplement Fibonacci",
            "output_path": Path(".baps-workspace/output/project"),
            "max_iterations": 2,
            "spec_path": None,
        }
    )
    assert len(state.artifacts) == 1
    artifact = state.artifacts[0]
    assert isinstance(artifact, state_module.CodingArtifact)
    assert artifact.id == "main-codebase"
    assert artifact.files == ()


def test_coding_adapter_maps_file_write_delta_to_state_update() -> None:

    adapter = CodingProjectAdapter()
    delta = state_module.DeltaCodingState(
        artifact_id="main-codebase",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(
                path="src/fibonacci.py",
                content="def fibonacci(n):\n    return n\n",
            )
        ),
    )
    proposal = adapter.delta_to_state_update(delta)
    assert proposal.payload.operation == "write_file"
    assert proposal.payload.file.path == "src/fibonacci.py"
def test_document_adapter_render_create_game_prompt_supplement_includes_delta_guidance() -> None:

    adapter = DocumentProjectAdapter()
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="main-document", sections=()),),
    )
    from baps.northstar.northstar_projection import ProjectionType, StateView
    state_view = StateView(
        id="sv:test",
        projection_type=ProjectionType.NORTH_STAR,
        content="state view content",
        input_fingerprint="x",
        metadata={},
    )
    result = adapter.render_create_game_prompt_supplement(
        state=state,
        config={"artifact_id": "main-document", "northstar_markdown": "goal"},
        state_view=state_view,
        verification_result=None,
    )
    assert "append_section" in result
    assert "modify_section" in result


def test_document_adapter_render_create_game_prompt_supplement_includes_guidance_on_failure() -> None:

    adapter = DocumentProjectAdapter()
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="main-document", sections=()),),
    )
    from baps.northstar.northstar_projection import ProjectionType, StateView
    state_view = StateView(
        id="sv:test",
        projection_type=ProjectionType.NORTH_STAR,
        content="state view content",
        input_fingerprint="x",
        metadata={},
    )
    verification_result = VerificationResult(
        command="document_export_consistency_check",
        cwd="/tmp",
        exit_code=1,
        stdout="",
        stderr="missing section title: Introduction",
        passed=False,
    )
    result = adapter.render_create_game_prompt_supplement(
        state=state,
        config={"artifact_id": "main-document", "northstar_markdown": "goal"},
        state_view=state_view,
        verification_result=verification_result,
    )
    assert "Document CreateGame verification evidence" in result
    assert "missing sections" in result


def test_coding_adapter_maps_write_files_batch_delta_to_state_update() -> None:

    adapter = CodingProjectAdapter()
    delta = state_module.DeltaCodingBatchState(
        artifact_id="main-codebase",
        operation="write_files",
        payload=state_module.WriteFilesDelta(
            files=(
                state_module.CodeFile(path="src/a.py", content="a"),
                state_module.CodeFile(path="src/b.py", content="b"),
            )
        ),
    )
    proposal = adapter.delta_to_state_update(delta)
    assert proposal.payload.operation == "write_files"
    assert len(proposal.payload.files) == 2
    assert proposal.payload.files[0].path == "src/a.py"


def test_coding_adapter_tool_call_write_files_returns_batch_delta() -> None:
    from baps.models.models import ToolCall

    adapter = CodingProjectAdapter()
    tool_call = ToolCall(
        name="write_files",
        arguments={
            "artifact_id": "main-codebase",
            "files": [
                {"path": "src/a.py", "content": "a"},
                {"path": "src/b.py", "content": "b"},
            ],
        },
    )
    delta = adapter.tool_call_to_delta(tool_call)
    assert isinstance(delta, state_module.DeltaCodingBatchState)
    assert len(delta.payload.files) == 2


def test_document_adapter_maps_modify_section_delta_to_state_update() -> None:

    adapter = DocumentProjectAdapter()
    delta = state_module.DeltaModifyDocumentState(
        artifact_id="main-document",
        operation="modify_section",
        payload=state_module.ModifySectionDelta(
            section_title="Intro",
            new_body="Updated intro.",
        ),
    )
    proposal = adapter.delta_to_state_update(delta)
    assert proposal.payload.operation == "modify_section"
    assert proposal.payload.section_title == "Intro"
    assert proposal.payload.new_body == "Updated intro."


def test_document_adapter_tool_call_modify_section_returns_correct_delta() -> None:
    from baps.models.models import ToolCall

    adapter = DocumentProjectAdapter()
    tool_call = ToolCall(
        name="modify_section",
        arguments={
            "artifact_id": "main-document",
            "section_title": "Intro",
            "new_body": "New body.",
        },
    )
    delta = adapter.tool_call_to_delta(tool_call)
    assert isinstance(delta, state_module.DeltaModifyDocumentState)
    assert delta.payload.section_title == "Intro"


def test_coding_adapter_maps_delete_file_delta_to_state_update() -> None:

    adapter = CodingProjectAdapter()
    delta = state_module.DeltaDeleteCodingState(
        artifact_id="main-codebase",
        operation="delete_file",
        payload=state_module.DeleteFileDelta(path="src/old.py"),
    )
    proposal = adapter.delta_to_state_update(delta)
    assert proposal.payload.operation == "delete_file"
    assert proposal.payload.path == "src/old.py"


def test_coding_adapter_tool_call_delete_file_returns_correct_delta() -> None:
    from baps.models.models import ToolCall

    adapter = CodingProjectAdapter()
    tool_call = ToolCall(
        name="delete_file",
        arguments={"artifact_id": "main-codebase", "path": "src/old.py"},
    )
    delta = adapter.tool_call_to_delta(tool_call)
    assert isinstance(delta, state_module.DeltaDeleteCodingState)
    assert delta.payload.path == "src/old.py"


def test_document_adapter_maps_delete_section_delta_to_state_update() -> None:

    adapter = DocumentProjectAdapter()
    delta = state_module.DeltaDeleteDocumentState(
        artifact_id="main-document",
        operation="delete_section",
        payload=state_module.DeleteSectionDelta(section_title="Obsolete"),
    )
    proposal = adapter.delta_to_state_update(delta)
    assert proposal.payload.operation == "delete_section"
    assert proposal.payload.section_title == "Obsolete"


def test_document_adapter_tool_call_delete_section_returns_correct_delta() -> None:
    from baps.models.models import ToolCall

    adapter = DocumentProjectAdapter()
    tool_call = ToolCall(
        name="delete_section",
        arguments={"artifact_id": "main-document", "section_title": "Obsolete"},
    )
    delta = adapter.tool_call_to_delta(tool_call)
    assert isinstance(delta, state_module.DeltaDeleteDocumentState)
    assert delta.payload.section_title == "Obsolete"


def test_coding_blue_prompt_includes_prior_export_failures() -> None:
    from baps.adapters.coding_adapter import render_coding_blue_prompt
    from baps.plugins.language_python import PythonLanguagePlugin
    from baps.northstar.northstar_projection import ProjectionType, StateView

    state_view = StateView(
        id="sv:test",
        projection_type=ProjectionType.NORTH_STAR,
        content="=== StateView Start ===\n=== StateView End ===",
        input_fingerprint="abc",
        metadata={},
    )
    game_spec = GameSpec(
        objective="Fix failing tests",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests pass",
    )
    previous_feedback = {
        "prior_export_verification": {
            "exit_code": 1,
            "passed": False,
            "stdout": "FAILED tests/test_foo.py::test_bar - AssertionError: wrong\n",
            "stderr": "",
        }
    }
    prompt = render_coding_blue_prompt(
        state_view=state_view,
        game_spec=game_spec,
        attempt_number=1,
        previous_feedback=previous_feedback,
        plugin=PythonLanguagePlugin(),
    )
    assert "tests/test_foo.py::test_bar" in prompt
    assert "AssertionError: wrong" in prompt
    assert "Fix these specific test failures" in prompt


def test_coding_blue_prompt_no_verification_section_when_feedback_is_none() -> None:
    from baps.adapters.coding_adapter import render_coding_blue_prompt
    from baps.plugins.language_python import PythonLanguagePlugin
    from baps.northstar.northstar_projection import ProjectionType, StateView

    state_view = StateView(
        id="sv:test",
        projection_type=ProjectionType.NORTH_STAR,
        content="=== StateView Start ===\n=== StateView End ===",
        input_fingerprint="abc",
        metadata={},
    )
    game_spec = GameSpec(
        objective="Write code",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="code written",
    )
    prompt = render_coding_blue_prompt(
        state_view=state_view,
        game_spec=game_spec,
        attempt_number=1,
        previous_feedback=None,
        plugin=PythonLanguagePlugin(),
    )
    assert "Prior export verification" not in prompt
    assert "Fix these specific test failures" not in prompt

def test_coding_blue_prompt_includes_candidate_verification_failures() -> None:
    from baps.adapters.coding_adapter import render_coding_blue_prompt
    from baps.plugins.language_python import PythonLanguagePlugin
    from baps.northstar.northstar_projection import ProjectionType, StateView

    state_view = StateView(
        id="sv:test",
        projection_type=ProjectionType.NORTH_STAR,
        content="=== StateView Start ===\n=== StateView End ===",
        input_fingerprint="abc",
        metadata={},
    )
    game_spec = GameSpec(
        objective="Fix failing tests",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests pass",
    )
    previous_feedback = {
        "candidate_verification": {
            "exit_code": 1,
            "passed": False,
            "stdout": "FAILED tests/test_calc.py::test_add - AssertionError: assert 99 == 3\n",
            "stderr": "",
        }
    }
    prompt = render_coding_blue_prompt(
        state_view=state_view,
        game_spec=game_spec,
        attempt_number=2,
        previous_feedback=previous_feedback,
        plugin=PythonLanguagePlugin(),
    )
    assert "tests/test_calc.py::test_add" in prompt
    assert "Candidate verification failed" in prompt
    assert "Repair these test failures" in prompt
