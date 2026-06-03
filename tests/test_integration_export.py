import ast
import subprocess
from pathlib import Path

import baps.state.state as state_module
from baps.adapters.coding_adapter import CodingProjectAdapter
from baps.adapters.document_adapter import DocumentProjectAdapter
from baps.game.engine import commit_export_with_adapter


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
    exported = (tmp_path / "project" / "tests" / "test_fibonacci.py").read_text(encoding="utf-8")
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
    exported = (tmp_path / "project" / "src" / "fibonacci.py").read_text(encoding="utf-8")
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
    exported = (tmp_path / "project" / "tests" / "test_fibonacci.py").read_text(encoding="utf-8")
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


def test_document_adapter_verify_export_passes_for_matching_export(
    tmp_path: Path,
) -> None:

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


def test_coding_adapter_verify_export_runs_pytest_and_captures_success(monkeypatch, tmp_path: Path) -> None:
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


def test_coding_adapter_verify_export_captures_failure(monkeypatch, tmp_path: Path) -> None:
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


def test_coding_adapter_verify_export_fails_for_missing_state_file(
    tmp_path: Path,
) -> None:

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(state_module.CodeFile(path="src/fibonacci.py", content="def fibonacci(n): return n\n"),),
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


def test_coding_adapter_verify_export_skips_pytest_when_files_missing(monkeypatch, tmp_path: Path) -> None:
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
                files=(state_module.CodeFile(path="src/fibonacci.py", content="def fibonacci(n): return n\n"),),
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


def test_coding_adapter_commit_export_skips_init_when_git_dir_exists(monkeypatch, tmp_path: Path) -> None:
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


def test_coding_adapter_commit_export_returns_false_when_git_unavailable(monkeypatch, tmp_path: Path) -> None:
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


def test_coding_adapter_commit_export_returns_false_when_commit_fails(monkeypatch, tmp_path: Path) -> None:
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


def testcommit_export_with_adapter_calls_adapter_method(monkeypatch, tmp_path: Path) -> None:

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
    result = commit_export_with_adapter(_CommittingAdapter(), output_dir, game_spec)
    assert result is True
    assert committed_args == [(output_dir, game_spec)]


def testcommit_export_with_adapter_skips_adapter_without_method(tmp_path: Path) -> None:
    class _NoCommitAdapter:
        project_type = "coding"

    game_spec = state_module.GameSpec(
        objective="Add feature",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests pass",
    )
    result = commit_export_with_adapter(_NoCommitAdapter(), tmp_path / "project", game_spec)
    assert result is False
