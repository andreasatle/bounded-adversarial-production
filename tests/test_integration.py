import ast
import inspect
import subprocess
from pathlib import Path

import pytest

from baps.models.models import FakeModelClient, ToolCall
from baps.core.run import create_state, main
from baps.core.game import create_game, play_game
from baps.state.state import (
    GameSpec,
    StateUpdateProposal,
)
from baps.northstar.northstar_projection import ProjectionType, StateView
from baps.core.parsers import NoNewGameError
from baps.adapters.project_adapter import VerificationResult
from baps.core.game import _derive_state_update_from_delta, _commit_export_with_adapter
from baps.adapters.document_adapter import DocumentProjectAdapter
from baps.adapters.coding_adapter import CodingProjectAdapter
import baps.state.state as state_module


def test_create_state_output_flows_into_create_game(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "flow-ws"
    import baps.core.run as run_module

    captured: dict[str, object] = {}
    original_create_game = create_game

    def _capturing_create_game(config, state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        captured.setdefault("state", state)
        return original_create_game(
            config,
            state,
            adapter=adapter,
            verification_result=verification_result,
        )

    monkeypatch.setattr("baps.core.orchestration.create_game", _capturing_create_game)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
        "--artifact-id", "main-document", "--goal", "Write a report.", "--output", "output/report.md", ],
    )

    run_module.main()

    forwarded_state = captured.get("state")
    assert forwarded_state is not None
    assert forwarded_state.model_dump(mode="json") == {
        "artifacts": [{"id": "main-document", "kind": "document", "sections": []}],
    }


def test_derive_state_update_from_delta_converts_append_section() -> None:

    delta = state_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=state_module.AppendSectionDelta(
            section=state_module.Section(title="Introduction", body="Body text")
        ),
    )
    proposal = _derive_state_update_from_delta(
        delta, adapter=DocumentProjectAdapter()
    )
    assert proposal.target.artifact_id == "main-document"
    assert proposal.payload.operation == "append_section"
    assert proposal.payload.section.title == "Introduction"
    assert proposal.payload.section.body == "Body text"


def test_main_integration_uses_state_service_apply_delta(monkeypatch, tmp_path: Path) -> None:
    import baps.core.run as run_module

    called = {"value": False}
    original_apply = run_module.StateService.apply_delta

    def _capture_apply(self, delta):
        called["value"] = True
        return original_apply(self, delta)

    monkeypatch.setattr(run_module.StateService, "apply_delta", _capture_apply)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(tmp_path / "ws-service"),
            "--project-type",
            "document",
        "--artifact-id", "main-document", "--goal", "Write a report.", "--output", "output/report.md", ],
    )
    run_module.main()
    assert called["value"] is True


def test_main_persists_updated_state_with_appended_section(monkeypatch, tmp_path: Path) -> None:
    import baps.core.run as run_module

    workspace = tmp_path / "ws-persist"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
        "--artifact-id", "main-document", "--goal", "Write a report.", "--output", "output/report.md", ],
    )
    run_module.main()

    persisted = run_module.JsonStateStore(workspace / "state" / "state.json").load()
    doc = next(a for a in persisted.artifacts if a.id == "main-document")
    assert isinstance(doc, state_module.DocumentArtifact)
    assert len(doc.sections) == 2
    assert doc.sections[0].title == "Introduction"
    assert doc.sections[0].body == "Advance goal"


def test_main_unsupported_delta_operation_fails_explicitly(monkeypatch, capsys, caplog, tmp_path: Path) -> None:
    import baps.core.run as run_module
    import logging

    monkeypatch.setattr(
        "baps.core.orchestration.play_game",
        lambda _state, _spec, adapter=None, verification_result=None, **_kwargs: state_module.DeltaCodingState(
            artifact_id="main-document",
            operation="write_file",
            payload=state_module.WriteFileDelta(
                file=state_module.CodeFile(path="foo.py", content="x")
            ),
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(tmp_path / "ws-unsupported-op"),
            "--project-type",
            "document",
        "--artifact-id", "main-document", "--goal", "Write a report.", "--output", "output/report.md", ],
    )
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
        run_module.main()
    assert exc.value.code == 2
    assert "DocumentArtifact does not support delta type" in caplog.text


def test_document_export_markdown_contains_sections_in_order(tmp_path: Path) -> None:

    adapter = DocumentProjectAdapter()
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.DocumentArtifact(
                id="main-document",
                sections=(
                    state_module.Section(title="Introduction", body="Intro body"),
                    state_module.Section(title="Conclusion", body="Conclusion body"),
                ),
            ),
        ),
    )
    output_path = tmp_path / "nested" / "out" / "report.md"
    changed = adapter.export_state(state, output_path, "main-document")
    assert changed is True
    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8") == (
        "## Introduction\n\nIntro body\n\n## Conclusion\n\nConclusion body"
    )


def test_document_export_creates_parent_directories(tmp_path: Path) -> None:

    adapter = DocumentProjectAdapter()
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="main-document", sections=()),),
    )
    output_path = tmp_path / "a" / "b" / "c" / "report.md"
    adapter.export_state(state, output_path, "main-document")
    assert output_path.parent.exists()


def test_document_export_output_changed_false_when_unchanged(tmp_path: Path) -> None:

    adapter = DocumentProjectAdapter()
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.DocumentArtifact(
                id="main-document",
                sections=(state_module.Section(title="Intro", body="Body"),),
            ),
        ),
    )
    output_path = tmp_path / "out" / "report.md"
    first = adapter.export_state(state, output_path, "main-document")
    second = adapter.export_state(state, output_path, "main-document")
    assert first is True
    assert second is False


def test_document_export_lives_behind_adapter_not_main_orchestration() -> None:
    import baps.core.run as run_module
    import baps.adapters.document_adapter as doc_adapter_module

    main_src = inspect.getsource(run_module.main)
    assert "output_path.write_text" not in main_src
    assert "run_baps_loop(" not in main_src
    # write_text lives in export_document_artifact, not directly in export_state
    free_fn_src = inspect.getsource(doc_adapter_module.export_document_artifact)
    assert "write_text" in free_fn_src


def test_main_uses_project_type_adapter_dispatch_for_document(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.core.run as run_module

    class _RecordingAdapter:
        project_type = "document"
        supported_delta_type = "DeltaDocumentState"

        def __init__(self) -> None:
            self.calls: list[str] = []
            self._delegate = DocumentProjectAdapter()

        def create_initial_state(self, config):
            self.calls.append("create_initial_state")
            return self._delegate.create_initial_state(config)

        def build_create_game_state_view(self, state, config):
            self.calls.append("build_create_game_state_view")
            return self._delegate.build_create_game_state_view(state, config)

        def render_create_game_prompt_supplement(
            self, state, config, state_view, verification_result
        ):
            self.calls.append("render_create_game_prompt_supplement")
            return self._delegate.render_create_game_prompt_supplement(
                state, config, state_view, verification_result
            )

        def build_state_view(self, state, game_spec):
            self.calls.append("build_state_view")
            return self._delegate.build_state_view(state, game_spec)

        def render_blue_prompt(self, state_view, game_spec, attempt_number, previous_feedback):
            self.calls.append("render_blue_prompt")
            return self._delegate.render_blue_prompt(
                state_view, game_spec, attempt_number, previous_feedback
            )

        def build_blue_output_format(self):
            self.calls.append("build_blue_output_format")
            return self._delegate.build_blue_output_format()

        def build_blue_tools(self):
            self.calls.append("build_blue_tools")
            return self._delegate.build_blue_tools()

        def tool_call_to_delta(self, tool_call):
            self.calls.append("tool_call_to_delta")
            return self._delegate.tool_call_to_delta(tool_call)

        def delta_to_state_update(self, delta_state):
            self.calls.append("delta_to_state_update")
            return self._delegate.delta_to_state_update(delta_state)

        def export_state(self, state, output_path, artifact_id):
            self.calls.append("export_state")
            return self._delegate.export_state(state, output_path, artifact_id)

    adapter = _RecordingAdapter()
    monkeypatch.setattr(run_module, "_resolve_project_type_adapter", lambda _ptype: adapter)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(tmp_path / "ws-adapter-dispatch"),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
            "--goal", "Write a report.", "--output", "output/report.md",
            "--max-iterations",
            "1",
        ],
    )
    run_module.main()
    assert "create_initial_state" in adapter.calls
    assert "build_create_game_state_view" in adapter.calls
    assert "render_create_game_prompt_supplement" in adapter.calls
    assert "build_state_view" in adapter.calls
    assert "render_blue_prompt" in adapter.calls
    assert "build_blue_output_format" in adapter.calls
    assert "build_blue_tools" in adapter.calls
    assert "tool_call_to_delta" in adapter.calls
    assert "export_state" in adapter.calls


def test_adapter_registry_includes_document_and_coding() -> None:
    import baps.core.run as run_module

    adapters = run_module._build_project_type_adapters()
    assert "document" in adapters
    assert "coding" in adapters


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


def test_coding_adapter_export_writes_files(tmp_path: Path) -> None:

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
                    state_module.CodeFile(
                        path="tests/test_fibonacci.py",
                        content="def test_smoke():\n    assert True\n",
                    ),
                ),
            ),
        ),
    )
    adapter = CodingProjectAdapter()
    changed = adapter.export_state(
        state=state,
        output_path=tmp_path / "project",
        artifact_id="main-codebase",
    )
    assert changed is True
    assert (tmp_path / "project" / "src" / "fibonacci.py").exists()
    assert (tmp_path / "project" / "tests" / "test_fibonacci.py").exists()


def test_coding_adapter_export_writes_src_and_tests_layout(tmp_path: Path) -> None:

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
                    state_module.CodeFile(
                        path="tests/test_fibonacci.py",
                        content=(
                            "from src.fibonacci import fibonacci\n\n"
                            "def test_fibonacci_smoke():\n"
                            "    assert fibonacci(5) == 5\n"
                        ),
                    ),
                ),
            ),
        ),
    )
    adapter = CodingProjectAdapter()
    changed = adapter.export_state(
        state=state,
        output_path=tmp_path / "project",
        artifact_id="main-codebase",
    )
    assert changed is True
    assert (tmp_path / "project" / "src" / "fibonacci.py").exists()
    assert (tmp_path / "project" / "tests" / "test_fibonacci.py").exists()


def test_coding_export_normalizes_escaped_newline_content(tmp_path: Path) -> None:

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(
                    state_module.CodeFile(
                        path="tests/test_fibonacci.py",
                        content="import pytest\\n\\ndef test_ok():\\n    assert 1 == 1\\n",
                    ),
                ),
            ),
        ),
    )
    adapter = CodingProjectAdapter()
    adapter.export_state(state, tmp_path / "project", "main-codebase")
    exported = (tmp_path / "project" / "tests" / "test_fibonacci.py").read_text(
        encoding="utf-8"
    )
    assert "\\n" not in exported
    assert "import pytest\n\ndef test_ok():" in exported


def test_coding_export_normalizes_escaped_quotes_content(tmp_path: Path) -> None:

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(
                    state_module.CodeFile(
                        path="src/fibonacci.py",
                        content='def msg():\\n    return \\"ok\\"\\n',
                    ),
                ),
            ),
        ),
    )
    adapter = CodingProjectAdapter()
    adapter.export_state(state, tmp_path / "project", "main-codebase")
    exported = (tmp_path / "project" / "src" / "fibonacci.py").read_text(
        encoding="utf-8"
    )
    assert '\\"' not in exported
    assert 'return "ok"' in exported


def test_coding_export_normalizes_multiline_pytest_and_parses(tmp_path: Path) -> None:

    escaped_pytest = (
        "import pytest\\n"
        "from src.fibonacci import fibonacci\\n\\n"
        "def test_fibonacci_base_cases():\\n"
        "    assert fibonacci(0) == 0\\n"
        "    assert fibonacci(1) == 1\\n\\n"
        "def test_fibonacci_negative_input():\\n"
        "    with pytest.raises(ValueError):\\n"
        "        fibonacci(-1)\\n"
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(state_module.CodeFile(path="tests/test_fibonacci.py", content=escaped_pytest),),
            ),
        ),
    )
    adapter = CodingProjectAdapter()
    adapter.export_state(state, tmp_path / "project", "main-codebase")
    exported = (tmp_path / "project" / "tests" / "test_fibonacci.py").read_text(
        encoding="utf-8"
    )
    ast.parse(exported)
    assert "def test_fibonacci_base_cases():" in exported
    assert "\\n" not in exported


def test_coding_adapter_verify_export_discovers_and_runs_pytest_tests(
    tmp_path: Path,
) -> None:

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(
                    state_module.CodeFile(
                        path="src/fibonacci.py",
                        content=(
                            "def fibonacci(n):\n"
                            "    if n < 0:\n"
                            "        raise ValueError('n must be >= 0')\n"
                            "    if n < 2:\n"
                            "        return n\n"
                            "    a, b = 0, 1\n"
                            "    for _ in range(2, n + 1):\n"
                            "        a, b = b, a + b\n"
                            "    return b\n"
                        ),
                    ),
                    state_module.CodeFile(
                        path="tests/test_fibonacci.py",
                        content=(
                            "from pathlib import Path\n"
                            "import sys\n\n"
                            "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n\n"
                            "from src.fibonacci import fibonacci\n\n"
                            "def test_fibonacci_values():\n"
                            "    assert fibonacci(0) == 0\n"
                            "    assert fibonacci(1) == 1\n"
                            "    assert fibonacci(7) == 13\n"
                        ),
                    ),
                ),
            ),
        ),
    )
    adapter = CodingProjectAdapter()
    output_dir = tmp_path / "project"
    _ = adapter.export_state(state, output_dir, "main-codebase")
    result = adapter.verify_export(output_dir, state, "main-codebase", sandbox_mode="none")
    assert result is not None
    assert result.passed is True
    assert result.exit_code == 0
    assert "pytest" in result.command


def test_coding_export_creates_nested_parent_directories(tmp_path: Path) -> None:

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(
                    state_module.CodeFile(
                        path="pkg/subpkg/fibonacci.py",
                        content="def fibonacci(n):\n    return n\n",
                    ),
                ),
            ),
        ),
    )
    adapter = CodingProjectAdapter()
    _ = adapter.export_state(
        state=state,
        output_path=tmp_path / "project",
        artifact_id="main-codebase",
    )
    assert (tmp_path / "project" / "pkg" / "subpkg" / "fibonacci.py").exists()


def test_coding_export_output_changed_false_when_unchanged(tmp_path: Path) -> None:

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
    adapter = CodingProjectAdapter()
    output_dir = tmp_path / "project"
    first = adapter.export_state(state, output_dir, "main-codebase")
    second = adapter.export_state(state, output_dir, "main-codebase")
    assert first is True
    assert second is False


def test_document_adapter_verify_export_passes_for_matching_export(tmp_path: Path) -> None:

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.DocumentArtifact(
                id="main-document",
                sections=(
                    state_module.Section(title="Introduction", body="Hello"),
                    state_module.Section(title="Conclusion", body="World"),
                ),
            ),
        ),
    )
    adapter = DocumentProjectAdapter()
    output_path = tmp_path / "report.md"
    output_path.write_text("## Introduction\n\nHello\n\n## Conclusion\n\nWorld", encoding="utf-8")
    result = adapter.verify_export(output_path, state, "main-document")
    assert result is not None
    assert result.passed is True
    assert result.exit_code == 0


def test_document_adapter_verify_export_fails_when_section_content_missing(
    tmp_path: Path,
) -> None:

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.DocumentArtifact(
                id="main-document",
                sections=(state_module.Section(title="Introduction", body="Hello"),),
            ),
        ),
    )
    adapter = DocumentProjectAdapter()
    output_path = tmp_path / "report.md"
    output_path.write_text("## Different\n\nBody", encoding="utf-8")
    result = adapter.verify_export(output_path, state, "main-document")
    assert result is not None
    assert result.passed is False
    assert result.exit_code == 1
    assert "missing section title: Introduction" in result.stderr


def test_coding_adapter_verify_export_runs_pytest_and_captures_success(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.tools.sandbox as sandbox_module

    captured: dict[str, object] = {}

    def _fake_run(args, cwd, capture_output, text, check):
        captured["args"] = args
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="2 passed\n", stderr="")

    monkeypatch.setattr(sandbox_module.subprocess, "run", _fake_run)
    adapter = CodingProjectAdapter()
    output_dir = tmp_path / "project"
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(id="main-codebase", files=()),),
    )
    result = adapter.verify_export(output_dir, state, "main-codebase", sandbox_mode="none")
    assert result is not None
    assert captured["args"] == ["uv", "run", "pytest"]
    assert captured["cwd"] == output_dir
    assert result.command == "uv run pytest"
    assert result.cwd == str(output_dir)
    assert result.exit_code == 0
    assert result.stdout == "2 passed\n"
    assert result.stderr == ""
    assert result.passed is True


def test_coding_adapter_verify_export_captures_failure(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.tools.sandbox as sandbox_module

    def _fake_run(args, cwd, capture_output, text, check):
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="1 failed\n", stderr="traceback\n")

    monkeypatch.setattr(sandbox_module.subprocess, "run", _fake_run)
    adapter = CodingProjectAdapter()
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(id="main-codebase", files=()),),
    )
    result = adapter.verify_export(tmp_path / "project", state, "main-codebase", sandbox_mode="none")
    assert result is not None
    assert result.exit_code == 1
    assert result.passed is False
    assert result.stdout == "1 failed\n"
    assert result.stderr == "traceback\n"


def test_coding_adapter_verify_export_fails_for_missing_state_file(tmp_path: Path) -> None:

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(
                    state_module.CodeFile(path="src/fibonacci.py", content="def fibonacci(n): return n\n"),
                ),
            ),
        ),
    )
    adapter = CodingProjectAdapter()
    output_dir = tmp_path / "project"
    output_dir.mkdir()
    result = adapter.verify_export(output_dir, state, "main-codebase")
    assert result is not None
    assert result.passed is False
    assert result.exit_code == 1
    assert result.command == "file_presence_check"
    assert "src/fibonacci.py" in result.stderr
    assert "exported files missing from output" in result.stderr


def test_coding_adapter_verify_export_skips_pytest_when_files_missing(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.adapters.coding_adapter as coding_module

    pytest_called = {"n": 0}

    def _fake_run(*_args, **_kwargs):
        pytest_called["n"] += 1
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(coding_module.subprocess, "run", _fake_run)
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(
                    state_module.CodeFile(path="src/fibonacci.py", content="def fibonacci(n): return n\n"),
                ),
            ),
        ),
    )
    adapter = CodingProjectAdapter()
    output_dir = tmp_path / "project"
    output_dir.mkdir()
    result = adapter.verify_export(output_dir, state, "main-codebase")
    assert result is not None
    assert result.passed is False
    assert pytest_called["n"] == 0


def test_coding_adapter_commit_export_inits_and_commits(monkeypatch, tmp_path: Path) -> None:
    import baps.adapters.coding_adapter as coding_module

    calls: list[list[str]] = []

    def _fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(coding_module.subprocess, "run", _fake_run)
    output_dir = tmp_path / "project"
    output_dir.mkdir()
    game_spec = state_module.GameSpec(
        objective="Add fibonacci function",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests pass",
    )
    adapter = CodingProjectAdapter()
    committed = adapter.commit_export(output_dir, game_spec)
    assert committed is True
    assert any(args[:2] == ["git", "init"] for args in calls)
    assert any(args[:3] == ["git", "commit", "-m"] for args in calls)
    commit_call = next(args for args in calls if args[:2] == ["git", "commit"])
    assert commit_call[3] == "baps: Add fibonacci function"


def test_coding_adapter_commit_export_skips_init_when_git_dir_exists(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.adapters.coding_adapter as coding_module

    calls: list[list[str]] = []

    def _fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(coding_module.subprocess, "run", _fake_run)
    output_dir = tmp_path / "project"
    output_dir.mkdir()
    (output_dir / ".git").mkdir()
    game_spec = state_module.GameSpec(
        objective="Fix tests",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests pass",
    )
    adapter = CodingProjectAdapter()
    adapter.commit_export(output_dir, game_spec)
    assert not any(args[:2] == ["git", "init"] for args in calls)


def test_coding_adapter_commit_export_returns_false_when_git_unavailable(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.adapters.coding_adapter as coding_module

    def _fake_run(args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(coding_module.subprocess, "run", _fake_run)
    output_dir = tmp_path / "project"
    output_dir.mkdir()
    game_spec = state_module.GameSpec(
        objective="Add feature",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests pass",
    )
    adapter = CodingProjectAdapter()
    committed = adapter.commit_export(output_dir, game_spec)
    assert committed is False


def test_coding_adapter_commit_export_returns_false_when_commit_fails(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.adapters.coding_adapter as coding_module

    def _fake_run(args, **kwargs):
        returncode = 1 if args[:2] == ["git", "commit"] else 0
        return subprocess.CompletedProcess(args=args, returncode=returncode, stdout="", stderr="")

    monkeypatch.setattr(coding_module.subprocess, "run", _fake_run)
    output_dir = tmp_path / "project"
    output_dir.mkdir()
    (output_dir / ".git").mkdir()
    game_spec = state_module.GameSpec(
        objective="Fix tests",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests pass",
    )
    adapter = CodingProjectAdapter()
    committed = adapter.commit_export(output_dir, game_spec)
    assert committed is False


def test_commit_export_with_adapter_calls_adapter_method(monkeypatch, tmp_path: Path) -> None:

    committed_args: list = []

    class _CommittingAdapter:
        project_type = "coding"

        def commit_export(self, output_path, game_spec):
            committed_args.append((output_path, game_spec))
            return True

    game_spec = state_module.GameSpec(
        objective="Add feature",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests pass",
    )
    output_dir = tmp_path / "project"
    output_dir.mkdir()
    result = _commit_export_with_adapter(_CommittingAdapter(), output_dir, game_spec)
    assert result is True
    assert committed_args == [(output_dir, game_spec)]


def test_commit_export_with_adapter_skips_adapter_without_method(tmp_path: Path) -> None:

    class _NoCommitAdapter:
        project_type = "coding"

    game_spec = state_module.GameSpec(
        objective="Add feature",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests pass",
    )
    result = _commit_export_with_adapter(
        _NoCommitAdapter(), tmp_path / "project", game_spec
    )
    assert result is False


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


def test_coding_run_no_files_keeps_output_exported_false(monkeypatch, tmp_path: Path, capsys) -> None:
    import baps.core.run as run_module

    workspace = tmp_path / "coding-empty-export"
    monkeypatch.setattr(
        "baps.core.orchestration.create_game",
        lambda *_args, **_kwargs: GameSpec(
            objective="No-op coding objective",
            target_artifact_id="main-codebase",
            allowed_delta_type="DeltaCodingState",
            success_condition="No file changes required",
        ),
    )
    monkeypatch.setattr("baps.core.orchestration.play_game", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "coding",
            "--artifact-id",
            "main-codebase",
            "--goal",
            "No-op coding objective",
            "--output",
            "output/project",
            "--max-iterations",
            "1",
            "--language",
            "python",
        ],
    )
    run_module.main()
    out = capsys.readouterr().out
    assert "output_exported=False" in out
    assert "output_changed=False" in out
    assert "verification_run=False" in out


def test_coding_run_summary_includes_verification_status(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    import baps.core.run as run_module

    workspace = tmp_path / "coding-verify-summary"

    monkeypatch.setattr(
        "baps.core.orchestration.create_game",
        lambda *_args, **_kwargs: GameSpec(
            objective="Write one file",
            target_artifact_id="main-codebase",
            allowed_delta_type="DeltaCodingState",
            success_condition="File exists",
        ),
    )
    monkeypatch.setattr(
        "baps.core.orchestration.play_game",
        lambda *_args, **_kwargs: state_module.DeltaCodingState(
            artifact_id="main-codebase",
            operation="write_file",
            payload=state_module.WriteFileDelta(
                file=state_module.CodeFile(
                    path="src/fibonacci.py",
                    content="def fibonacci(n):\n    return n\n",
                )
            ),
        ),
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "coding",
            "--artifact-id",
            "main-codebase",
            "--goal",
            "Implement Fibonacci with tests.",
            "--output",
            "output/project",
            "--max-iterations",
            "1",
            "--sandbox",
            "none",
            "--language",
            "python",
        ],
    )
    run_module.main()
    out = capsys.readouterr().out
    assert "verification_run=True" in out
    assert "verification_passed=" in out
    assert "verification_exit_code=" in out
    assert "verification_command=" in out
    assert "verification_cwd=" in out


def test_document_run_runs_verification(monkeypatch, tmp_path: Path, capsys) -> None:
    import baps.core.run as run_module

    workspace = tmp_path / "document-no-verify"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
            "--goal", "Write a report.", "--output", "output/report.md",
            "--max-iterations",
            "1",
        ],
    )
    run_module.main()
    out = capsys.readouterr().out
    assert "verification_run=True" in out
    assert "verification_passed=True" in out
    assert "verification_command=document_export_consistency_check" in out


def test_coding_init_and_run_exports_fibonacci_files(monkeypatch, tmp_path: Path) -> None:
    import baps.core.run as run_module

    workspace = tmp_path / "coding-workspace"
    output_dir = workspace / "output" / "project"

    monkeypatch.setattr(
        "baps.core.orchestration.create_game",
        lambda *_args, **_kwargs: GameSpec(
            objective="Write fibonacci implementation file",
            target_artifact_id="main-codebase",
            allowed_delta_type="DeltaCodingState",
            success_condition="src/fibonacci.py and tests/test_fibonacci.py exist",
        ),
    )

    call_counter = {"count": 0}

    def _play_game(_state, _game_spec, adapter=None, verification_result=None, **_kwargs):
        call_counter["count"] += 1
        if call_counter["count"] == 1:
            return state_module.DeltaCodingState(
                artifact_id="main-codebase",
                operation="write_file",
                payload=state_module.WriteFileDelta(
                    file=state_module.CodeFile(
                        path="src/fibonacci.py",
                        content=(
                            "def fibonacci(n):\n"
                            "    if n < 0:\n"
                            "        raise ValueError('n must be >= 0')\n"
                            "    if n < 2:\n"
                            "        return n\n"
                            "    a, b = 0, 1\n"
                            "    for _ in range(2, n + 1):\n"
                            "        a, b = b, a + b\n"
                            "    return b\n"
                        ),
                    )
                ),
            )
        if call_counter["count"] == 2:
            return state_module.DeltaCodingState(
                artifact_id="main-codebase",
                operation="write_file",
                payload=state_module.WriteFileDelta(
                    file=state_module.CodeFile(
                        path="tests/test_fibonacci.py",
                        content=(
                            "from src.fibonacci import fibonacci\n\n"
                            "def test_fibonacci_base_cases():\n"
                            "    assert fibonacci(0) == 0\n"
                            "    assert fibonacci(1) == 1\n\n"
                            "def test_fibonacci_sequence():\n"
                            "    assert fibonacci(7) == 13\n"
                        ),
                    )
                ),
            )
        return None

    monkeypatch.setattr("baps.core.orchestration.play_game", _play_game)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "coding",
            "--artifact-id",
            "main-codebase",
            "--goal",
            "Implement Fibonacci with tests.",
            "--output",
            str(output_dir),
            "--max-iterations",
            "2",
            "--sandbox",
            "none",
            "--language",
            "python",
        ],
    )

    run_module.main()
    assert (output_dir / "src" / "fibonacci.py").exists()
    assert (output_dir / "tests" / "test_fibonacci.py").exists()


def test_play_game_uses_adapter_provided_state_view_prompt_and_parser() -> None:
    from baps.models.models import ToolDefinition

    class _PlayAdapter:
        project_type = "document"
        supported_delta_type = "DeltaDocumentState"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def create_initial_state(self, _config):
            raise NotImplementedError

        def build_state_view(self, _state, _game_spec):
            self.calls.append("build_state_view")
            return StateView(
                id="state-view:test",
                projection_type=ProjectionType.NORTH_STAR,
                content="{}",
                input_fingerprint="x",
                metadata={},
            )

        def render_blue_prompt(
            self, _state_view, _game_spec, _attempt_number, _previous_feedback
        ):
            self.calls.append("render_blue_prompt")
            return "blue-prompt"

        def build_blue_output_format(self):
            return None

        def build_blue_tools(self):
            self.calls.append("build_blue_tools")
            return [ToolDefinition(name="append_section", description="Append", parameters={})]

        def tool_call_to_delta(self, _tool_call):
            self.calls.append("tool_call_to_delta")
            return state_module.DeltaDocumentState(
                artifact_id="main-document",
                operation="append_section",
                payload=state_module.AppendSectionDelta(
                    section=state_module.Section(title="Intro", body="Body")
                ),
            )

        def delta_to_state_update(self, _delta_state):
            raise NotImplementedError

    adapter = _PlayAdapter()
    spec = GameSpec(
        objective="Add section",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="section exists",
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="main-document", sections=()),),
    )
    delta = play_game(
        state,
        spec,
        adapter=adapter,
        model_client=FakeModelClient(
            tool_responses=[ToolCall("append_section", {"artifact_id": "main-document", "title": "Intro", "body": "Body"})]
        ),
        red_model_client=FakeModelClient(['{"disposition":"accept","rationale":"ok"}']),
        referee_model_client=FakeModelClient(['{"disposition":"accept","rationale":"ok"}']),
    )
    assert isinstance(delta, state_module.DeltaDocumentState)
    assert adapter.calls == ["build_state_view", "render_blue_prompt", "build_blue_tools", "tool_call_to_delta"]


def test_integration_uses_adapter_delta_to_update_mapper() -> None:

    class _MapperAdapter:
        project_type = "document"
        supported_delta_type = "DeltaDocumentState"

        def create_initial_state(self, _config):
            raise NotImplementedError

        def build_state_view(self, _state, _game_spec):
            raise NotImplementedError

        def render_blue_prompt(
            self, _state_view, _game_spec, _attempt_number, _previous_feedback
        ):
            raise NotImplementedError

        def parse_blue_delta(self, _text):
            raise NotImplementedError

        def delta_to_state_update(self, delta_state):
                return StateUpdateProposal(
                    id="mapped",
                    target=state_module.StateUpdateTarget(artifact_id=delta_state.artifact_id),
                    summary="mapped",
                    payload={
                        "operation": "replace_artifact",
                    "artifact": {"id": delta_state.artifact_id, "kind": "document"},
                },
            )

    delta = state_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=state_module.AppendSectionDelta(
            section=state_module.Section(title="T", body="B")
        ),
    )
    proposal = _derive_state_update_from_delta(delta, adapter=_MapperAdapter())
    assert proposal.id == "mapped"


def test_coding_iteration_two_does_not_receive_stale_verification_result(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.core.run as run_module

    workspace = tmp_path / "coding-no-stale-verification"
    verification_seen: list[object] = []
    call_counter = {"count": 0}

    def _create_game(_config, _state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        del verification_result
        call_counter["count"] += 1
        if call_counter["count"] == 1:
            return GameSpec(
                objective="Write src/fibonacci.py containing implementation",
                target_artifact_id="main-codebase",
                allowed_delta_type="DeltaCodingState",
                success_condition="src/fibonacci.py exists",
            )
        if call_counter["count"] == 2:
            return GameSpec(
                objective="Write tests/test_fibonacci.py containing tests",
                target_artifact_id="main-codebase",
                allowed_delta_type="DeltaCodingState",
                success_condition="tests/test_fibonacci.py exists",
            )
        raise NoNewGameError("done")

    def _play_game(_state, spec, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        verification_seen.append(verification_result)
        if "src/fibonacci.py" in spec.objective:
            return state_module.DeltaCodingState(
                artifact_id="main-codebase",
                operation="write_file",
                payload=state_module.WriteFileDelta(
                    file=state_module.CodeFile(
                        path="src/fibonacci.py",
                        content="def fibonacci(n):\n    return n\n",
                    )
                ),
            )
        if "tests/test_fibonacci.py" in spec.objective:
            return state_module.DeltaCodingState(
                artifact_id="main-codebase",
                operation="write_file",
                payload=state_module.WriteFileDelta(
                    file=state_module.CodeFile(
                        path="tests/test_fibonacci.py",
                        content="def test_smoke():\n    assert True\n",
                    )
                ),
            )
        return None

    monkeypatch.setattr("baps.core.orchestration.create_game", _create_game)
    monkeypatch.setattr("baps.core.orchestration.play_game", _play_game)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "coding",
            "--artifact-id",
            "main-codebase",
            "--goal",
            "Implement Fibonacci with tests.",
            "--output",
            "output/project",
            "--max-iterations",
            "2",
            "--sandbox",
            "none",
            "--language",
            "python",
        ],
    )
    run_module.main()
    assert verification_seen[0] is None  # first iteration: no prior export yet
    assert isinstance(verification_seen[1], VerificationResult)  # second iteration: receives prior export result


def test_coding_create_game_receives_previous_verification_result_second_iteration(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.core.run as run_module

    workspace = tmp_path / "coding-create-game-verification-input"
    seen: list[VerificationResult | None] = []
    create_count = {"n": 0}

    def _create_game(_config, _state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        del adapter
        seen.append(verification_result)
        create_count["n"] += 1
        if create_count["n"] == 1:
            return GameSpec(
                objective="Write src/fibonacci.py containing implementation",
                target_artifact_id="main-codebase",
                allowed_delta_type="DeltaCodingState",
                success_condition="src/fibonacci.py exists",
            )
        if create_count["n"] == 2:
            return GameSpec(
                objective="Write tests/test_fibonacci.py containing tests",
                target_artifact_id="main-codebase",
                allowed_delta_type="DeltaCodingState",
                success_condition="tests/test_fibonacci.py exists",
            )
        raise NoNewGameError("done")

    def _play_game(_state, spec, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        del adapter, verification_result
        if "src/fibonacci.py" in spec.objective:
            return state_module.DeltaCodingState(
                artifact_id="main-codebase",
                operation="write_file",
                payload=state_module.WriteFileDelta(
                    file=state_module.CodeFile(
                        path="src/fibonacci.py",
                        content="def fibonacci(n):\n    return n\n",
                    )
                ),
            )
        return state_module.DeltaCodingState(
            artifact_id="main-codebase",
            operation="write_file",
            payload=state_module.WriteFileDelta(
                file=state_module.CodeFile(
                    path="tests/test_fibonacci.py",
                    content="def test_smoke():\n    assert True\n",
                )
            ),
        )

    verify_calls = {"n": 0}

    def _verify_export(_adapter, _output_path, _state, _artifact_id, **_kwargs):
        verify_calls["n"] += 1
        if verify_calls["n"] == 1:
            return VerificationResult(
                command="uv run pytest",
                cwd=str(workspace / "output" / "project"),
                exit_code=2,
                stdout="ModuleNotFoundError: No module named 'src'",
                stderr="",
                passed=False,
            )
        return VerificationResult(
            command="uv run pytest",
            cwd=str(workspace / "output" / "project"),
            exit_code=0,
            stdout="1 passed",
            stderr="",
            passed=True,
        )

    monkeypatch.setattr("baps.core.orchestration.create_game", _create_game)
    monkeypatch.setattr("baps.core.orchestration.play_game", _play_game)
    monkeypatch.setattr("baps.core.orchestration._verify_export_with_adapter", _verify_export)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "coding",
            "--artifact-id",
            "main-codebase",
            "--goal",
            "Implement Fibonacci with tests.",
            "--output",
            "output/project",
            "--max-iterations",
            "2",
            "--language",
            "python",
        ],
    )
    run_module.main()

    assert len(seen) >= 2
    assert seen[0] is None
    assert seen[1] is not None
    assert seen[1].exit_code == 2


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


def test_play_game_pre_seeds_verification_result_as_previous_feedback(monkeypatch) -> None:

    captured_feedback: list[object] = []

    class _CapturingAdapter:
        project_type = "coding"
        supported_delta_type = "DeltaCodingState"

        def build_state_view(self, state, game_spec):
            from baps.northstar.northstar_projection import ProjectionType, StateView
            return StateView(
                id="sv", projection_type=ProjectionType.NORTH_STAR,
                content="view", input_fingerprint="fp", metadata={}
            )

        def render_blue_prompt(self, state_view, game_spec, attempt_number, previous_feedback):
            captured_feedback.append(previous_feedback)
            return "blue prompt"

        def build_blue_output_format(self):
            return None

        def build_blue_tools(self):
            return []

        def parse_blue_delta(self, text):
            raise ValueError("no delta — max_attempts=1 so this exhausts attempts")

        def render_red_prompt_supplement(self, *a, **kw):
            return ""

        def render_referee_prompt_supplement(self, *a, **kw):
            return ""

        def delta_to_state_update(self, delta):
            raise ValueError("unused")

    vr = VerificationResult(
        command="uv run pytest", cwd="/tmp", exit_code=1,
        stdout="FAILED tests/test_foo.py::test_x - AssertionError\n",
        stderr="", passed=False,
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(id="main-codebase", files=()),),
    )
    game_spec = GameSpec(
        objective="Fix tests",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests pass",
    )

    # tool_responses=[None] makes generate_with_tools return None → falls through to generate().
    # parse_blue_delta raises ValueError → attempt exhausted → returns None.
    result = play_game(
        state, game_spec,
        adapter=_CapturingAdapter(),
        model_client=FakeModelClient(tool_responses=[None], responses=["not valid json"]),
        red_model_client=FakeModelClient(responses=[]),
        referee_model_client=FakeModelClient(responses=[]),
        verification_result=vr,
        max_attempts=1,
    )

    assert result is None
    assert len(captured_feedback) >= 1
    fb = captured_feedback[0]
    assert fb is not None
    assert "prior_export_verification" in fb
    assert fb["prior_export_verification"]["exit_code"] == 1
    assert fb["prior_export_verification"]["passed"] is False


# ---------------------------------------------------------------------------
# Phase 2: Candidate verification within PlayGame
# ---------------------------------------------------------------------------

def test_apply_delta_to_files_write_file() -> None:
    from baps.adapters.coding_adapter import _apply_delta_to_files

    existing = (
        state_module.CodeFile(path="src/a.py", content="old"),
    )
    delta = state_module.DeltaCodingState(
        artifact_id="art",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(path="src/a.py", content="new")
        ),
    )
    result = _apply_delta_to_files(existing, delta)
    assert len(result) == 1
    assert result[0].content == "new"


def test_apply_delta_to_files_write_files_adds_and_replaces() -> None:
    from baps.adapters.coding_adapter import _apply_delta_to_files

    existing = (
        state_module.CodeFile(path="src/a.py", content="old_a"),
    )
    delta = state_module.DeltaCodingBatchState(
        artifact_id="art",
        operation="write_files",
        payload=state_module.WriteFilesDelta(files=[
            state_module.CodeFile(path="src/a.py", content="new_a"),
            state_module.CodeFile(path="src/b.py", content="b_content"),
        ]),
    )
    result = _apply_delta_to_files(existing, delta)
    paths = {f.path for f in result}
    assert paths == {"src/a.py", "src/b.py"}
    a = next(f for f in result if f.path == "src/a.py")
    assert a.content == "new_a"


def test_apply_delta_to_files_delete_file() -> None:
    from baps.adapters.coding_adapter import _apply_delta_to_files

    existing = (
        state_module.CodeFile(path="src/a.py", content="a"),
        state_module.CodeFile(path="src/b.py", content="b"),
    )
    delta = state_module.DeltaDeleteCodingState(
        artifact_id="art",
        operation="delete_file",
        payload=state_module.DeleteFileDelta(path="src/a.py"),
    )
    result = _apply_delta_to_files(existing, delta)
    assert len(result) == 1
    assert result[0].path == "src/b.py"


def test_verify_candidate_returns_none_when_no_test_files() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(
            id="art",
            files=(state_module.CodeFile(path="src/foo.py", content="x = 1"),),
        ),),
    )
    delta = state_module.DeltaCodingState(
        artifact_id="art",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(path="src/bar.py", content="y = 2")
        ),
    )
    result = CodingProjectAdapter().verify_candidate(delta, state, "art")
    assert result is None


def test_verify_candidate_passes_when_tests_pass(tmp_path) -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(
            id="art",
            files=(state_module.CodeFile(path="src/calc.py", content="def add(a, b):\n    return a + b\n"),),
        ),),
    )
    delta = state_module.DeltaCodingState(
        artifact_id="art",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(
                path="tests/test_calc.py",
                content=(
                    "import sys, os\n"
                    "sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))\n"
                    "from calc import add\n"
                    "def test_add():\n"
                    "    assert add(1, 2) == 3\n"
                ),
            )
        ),
    )
    result = CodingProjectAdapter().verify_candidate(delta, state, "art", sandbox_mode="none")
    assert result is not None
    assert result.passed is True
    assert result.exit_code == 0


def test_verify_candidate_fails_when_tests_fail() -> None:
    from baps.adapters.coding_adapter import CodingProjectAdapter

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(
            id="art",
            files=(state_module.CodeFile(path="src/calc.py", content="def add(a, b):\n    return 99\n"),),
        ),),
    )
    delta = state_module.DeltaCodingState(
        artifact_id="art",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(
                path="tests/test_calc.py",
                content=(
                    "import sys, os\n"
                    "sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))\n"
                    "from calc import add\n"
                    "def test_add():\n"
                    "    assert add(1, 2) == 3\n"
                ),
            )
        ),
    )
    result = CodingProjectAdapter().verify_candidate(delta, state, "art", sandbox_mode="none")
    assert result is not None
    assert result.passed is False
    assert result.exit_code == 1


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


# ---------------------------------------------------------------------------
# Blackboard auditability: CREATE_GAME / PLAY_GAME / INTEGRATION events
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
