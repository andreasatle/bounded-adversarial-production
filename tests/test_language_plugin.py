"""Tests for language_plugin.py and language_python.py."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# LanguagePlugin protocol and registry
# ---------------------------------------------------------------------------

def test_get_language_plugin_python_returns_python_plugin() -> None:
    from baps.language_plugin import get_language_plugin
    from baps.language_python import PythonLanguagePlugin

    plugin = get_language_plugin("python")
    assert isinstance(plugin, PythonLanguagePlugin)


def test_get_language_plugin_zig_returns_zig_plugin() -> None:
    from baps.language_plugin import get_language_plugin
    from baps.language_zig import ZigLanguagePlugin

    plugin = get_language_plugin("zig")
    assert isinstance(plugin, ZigLanguagePlugin)


def test_get_language_plugin_unknown_raises_value_error() -> None:
    from baps.language_plugin import get_language_plugin

    with pytest.raises(ValueError, match="is not supported"):
        get_language_plugin("fortran")


def test_get_language_plugin_error_message_lists_supported() -> None:
    from baps.language_plugin import get_language_plugin

    with pytest.raises(ValueError, match="python"):
        get_language_plugin("cobol")


def test_get_language_plugin_error_message_lists_zig() -> None:
    from baps.language_plugin import get_language_plugin

    with pytest.raises(ValueError, match="zig"):
        get_language_plugin("cobol")


def test_python_plugin_satisfies_language_plugin_protocol() -> None:
    from baps.language_plugin import LanguagePlugin
    from baps.language_python import PythonLanguagePlugin

    plugin = PythonLanguagePlugin()
    assert isinstance(plugin, LanguagePlugin)


def test_python_plugin_name() -> None:
    from baps.language_python import PythonLanguagePlugin

    assert PythonLanguagePlugin.name == "python"


def test_python_plugin_docker_image() -> None:
    from baps.language_python import PythonLanguagePlugin

    assert PythonLanguagePlugin.docker_image == "python:3.12-slim"


def test_python_plugin_test_command_contains_pytest() -> None:
    from baps.language_python import PythonLanguagePlugin

    assert "pytest" in PythonLanguagePlugin.test_command


def test_python_plugin_test_command_is_str() -> None:
    from baps.language_python import PythonLanguagePlugin

    assert isinstance(PythonLanguagePlugin.test_command, str)
    assert PythonLanguagePlugin.test_command.strip() != ""


# ---------------------------------------------------------------------------
# PythonLanguagePlugin.initialize
# ---------------------------------------------------------------------------

def test_initialize_creates_conftest(tmp_path: Path) -> None:
    from baps.language_python import PythonLanguagePlugin, _CONFTEST_CONTENT

    PythonLanguagePlugin().initialize(tmp_path)
    assert (tmp_path / "conftest.py").read_text(encoding="utf-8") == _CONFTEST_CONTENT


def test_initialize_creates_gitignore(tmp_path: Path) -> None:
    from baps.language_python import PythonLanguagePlugin, _GITIGNORE_CONTENT

    PythonLanguagePlugin().initialize(tmp_path)
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == _GITIGNORE_CONTENT


def test_initialize_returns_true_on_first_call(tmp_path: Path) -> None:
    from baps.language_python import PythonLanguagePlugin

    changed = PythonLanguagePlugin().initialize(tmp_path)
    assert changed is True


def test_initialize_returns_false_when_files_already_correct(tmp_path: Path) -> None:
    from baps.language_python import PythonLanguagePlugin

    plugin = PythonLanguagePlugin()
    plugin.initialize(tmp_path)
    changed = plugin.initialize(tmp_path)
    assert changed is False


def test_initialize_creates_project_path_if_missing(tmp_path: Path) -> None:
    from baps.language_python import PythonLanguagePlugin

    new_dir = tmp_path / "subdir" / "project"
    assert not new_dir.exists()
    PythonLanguagePlugin().initialize(new_dir)
    assert new_dir.is_dir()
    assert (new_dir / "conftest.py").exists()


def test_initialize_returns_true_when_conftest_differs(tmp_path: Path) -> None:
    from baps.language_python import PythonLanguagePlugin

    (tmp_path / "conftest.py").write_text("# old content\n", encoding="utf-8")
    changed = PythonLanguagePlugin().initialize(tmp_path)
    assert changed is True


# ---------------------------------------------------------------------------
# PythonLanguagePlugin.run_tests
# ---------------------------------------------------------------------------

def _make_completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    result: subprocess.CompletedProcess = MagicMock(spec=subprocess.CompletedProcess)
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def test_run_tests_bare_uses_uv(tmp_path: Path) -> None:
    from baps.language_python import PythonLanguagePlugin

    completed = _make_completed(returncode=0, stdout="1 passed")
    with patch("baps.language_python.subprocess.run", return_value=completed) as mock_run:
        result = PythonLanguagePlugin().run_tests(tmp_path, "none")

    assert result.passed is True
    assert result.exit_code == 0
    assert result.command == "uv run pytest"
    assert mock_run.call_args[0][0] == ["uv", "run", "pytest"]


def test_run_tests_bare_falls_back_when_uv_missing(tmp_path: Path) -> None:
    import sys as _sys
    from baps.language_python import PythonLanguagePlugin

    completed = _make_completed(returncode=0, stdout="1 passed")

    def _side_effect(args, **kwargs):
        if args[0] == "uv":
            raise FileNotFoundError
        return completed

    with patch("baps.language_python.subprocess.run", side_effect=_side_effect):
        result = PythonLanguagePlugin().run_tests(tmp_path, "none")

    assert result.passed is True
    assert _sys.executable in result.command


def test_run_tests_bare_sets_cwd(tmp_path: Path) -> None:
    from baps.language_python import PythonLanguagePlugin

    completed = _make_completed(returncode=0)
    with patch("baps.language_python.subprocess.run", return_value=completed) as mock_run:
        result = PythonLanguagePlugin().run_tests(tmp_path, "none")

    assert result.cwd == str(tmp_path)
    assert mock_run.call_args.kwargs.get("cwd") == tmp_path


def test_run_tests_bare_wraps_failure(tmp_path: Path) -> None:
    from baps.language_python import PythonLanguagePlugin

    completed = _make_completed(returncode=1, stdout="1 failed", stderr="err")
    with patch("baps.language_python.subprocess.run", return_value=completed):
        result = PythonLanguagePlugin().run_tests(tmp_path, "none")

    assert result.passed is False
    assert result.exit_code == 1
    assert result.stdout == "1 failed"
    assert result.stderr == "err"


def test_run_tests_docker_uses_plugin_image_and_command(tmp_path: Path) -> None:
    from baps.language_python import PythonLanguagePlugin

    plugin = PythonLanguagePlugin()
    completed = _make_completed(returncode=0, stdout="1 passed")
    with patch("baps.sandbox.subprocess.run", return_value=completed) as mock_run:
        result = plugin.run_tests(tmp_path, "docker")

    assert result.passed is True
    docker_args = mock_run.call_args[0][0]
    assert docker_args[0] == "docker"
    assert plugin.docker_image in docker_args
    assert plugin.test_command in docker_args


def test_run_tests_docker_sets_cwd(tmp_path: Path) -> None:
    from baps.language_python import PythonLanguagePlugin

    completed = _make_completed(returncode=0)
    with patch("baps.sandbox.subprocess.run", return_value=completed):
        result = PythonLanguagePlugin().run_tests(tmp_path, "docker")

    assert result.cwd == str(tmp_path)


# ---------------------------------------------------------------------------
# PythonLanguagePlugin.build
# ---------------------------------------------------------------------------

def test_build_is_noop(tmp_path: Path) -> None:
    from baps.language_python import PythonLanguagePlugin

    before = list(tmp_path.iterdir())
    PythonLanguagePlugin().build(tmp_path)
    after = list(tmp_path.iterdir())
    assert before == after


def test_build_returns_none(tmp_path: Path) -> None:
    from baps.language_python import PythonLanguagePlugin

    result = PythonLanguagePlugin().build(tmp_path)
    assert result is None


# ---------------------------------------------------------------------------
# PythonLanguagePlugin.parse_test_failures
# ---------------------------------------------------------------------------

def test_parse_test_failures_empty_stdout() -> None:
    from baps.language_python import PythonLanguagePlugin

    assert PythonLanguagePlugin().parse_test_failures("") == []


def test_parse_test_failures_no_failures() -> None:
    from baps.language_python import PythonLanguagePlugin

    stdout = "collected 3 items\n\n3 passed in 0.1s\n"
    assert PythonLanguagePlugin().parse_test_failures(stdout) == []


def test_parse_test_failures_single_failure_with_reason() -> None:
    from baps.language_python import PythonLanguagePlugin

    stdout = "FAILED tests/test_foo.py::test_bar - AssertionError: expected 1 got 2\n"
    result = PythonLanguagePlugin().parse_test_failures(stdout)
    assert result == [{"test_id": "tests/test_foo.py::test_bar", "reason": "AssertionError: expected 1 got 2"}]


def test_parse_test_failures_multiple_failures() -> None:
    from baps.language_python import PythonLanguagePlugin

    stdout = (
        "FAILED tests/test_a.py::test_one - AssertionError: wrong\n"
        "FAILED tests/test_b.py::test_two - TypeError: bad type\n"
    )
    result = PythonLanguagePlugin().parse_test_failures(stdout)
    assert len(result) == 2
    assert result[0]["test_id"] == "tests/test_a.py::test_one"
    assert result[1]["test_id"] == "tests/test_b.py::test_two"


def test_parse_test_failures_no_reason_separator() -> None:
    from baps.language_python import PythonLanguagePlugin

    stdout = "FAILED tests/test_foo.py::test_bar\n"
    result = PythonLanguagePlugin().parse_test_failures(stdout)
    assert result == [{"test_id": "tests/test_foo.py::test_bar", "reason": ""}]


# ---------------------------------------------------------------------------
# PythonLanguagePlugin.has_tests
# ---------------------------------------------------------------------------

def test_has_tests_detects_tests_prefix() -> None:
    from baps.language_python import PythonLanguagePlugin

    assert PythonLanguagePlugin().has_tests(["tests/test_foo.py"]) is True


def test_has_tests_detects_test_underscore_prefix() -> None:
    from baps.language_python import PythonLanguagePlugin

    assert PythonLanguagePlugin().has_tests(["test_utils.py"]) is True


def test_has_tests_returns_false_for_src_only() -> None:
    from baps.language_python import PythonLanguagePlugin

    assert PythonLanguagePlugin().has_tests(["src/foo.py", "src/bar.py"]) is False


def test_has_tests_returns_false_for_empty_list() -> None:
    from baps.language_python import PythonLanguagePlugin

    assert PythonLanguagePlugin().has_tests([]) is False


def test_has_tests_mixed_returns_true() -> None:
    from baps.language_python import PythonLanguagePlugin

    assert PythonLanguagePlugin().has_tests(["src/foo.py", "tests/test_foo.py"]) is True


# ---------------------------------------------------------------------------
# CodingProjectAdapter language selection
# ---------------------------------------------------------------------------

def test_coding_adapter_create_initial_state_defaults_to_python() -> None:
    from baps.coding_adapter import CodingProjectAdapter

    state = CodingProjectAdapter().create_initial_state({"artifact_id": "art", "northstar_markdown": "x"})
    artifact = next(a for a in state.artifacts if a.id == "art")
    assert artifact.language == "python"  # type: ignore[union-attr]


def test_coding_adapter_create_initial_state_accepts_zig() -> None:
    from baps.coding_adapter import CodingProjectAdapter

    state = CodingProjectAdapter().create_initial_state(
        {"artifact_id": "art", "language": "zig", "northstar_markdown": "x"}
    )
    artifact = next(a for a in state.artifacts if a.id == "art")
    assert artifact.language == "zig"  # type: ignore[union-attr]


def test_coding_adapter_unknown_language_raises_on_create_initial_state() -> None:
    from baps.coding_adapter import CodingProjectAdapter

    with pytest.raises(ValueError, match="is not supported"):
        CodingProjectAdapter().create_initial_state(
            {"artifact_id": "art", "language": "brainfuck", "northstar_markdown": "x"}
        )


def test_coding_adapter_unknown_language_error_lists_available() -> None:
    from baps.coding_adapter import CodingProjectAdapter

    with pytest.raises(ValueError, match="python"):
        CodingProjectAdapter().create_initial_state(
            {"artifact_id": "art", "language": "cobol", "northstar_markdown": "x"}
        )

    with pytest.raises(ValueError, match="zig"):
        CodingProjectAdapter().create_initial_state(
            {"artifact_id": "art", "language": "cobol", "northstar_markdown": "x"}
        )


# ---------------------------------------------------------------------------
# ZigLanguagePlugin
# ---------------------------------------------------------------------------

def test_zig_plugin_satisfies_language_plugin_protocol() -> None:
    from baps.language_plugin import LanguagePlugin
    from baps.language_zig import ZigLanguagePlugin

    assert isinstance(ZigLanguagePlugin(), LanguagePlugin)


def test_zig_plugin_name() -> None:
    from baps.language_zig import ZigLanguagePlugin

    assert ZigLanguagePlugin.name == "zig"


def test_zig_plugin_docker_image() -> None:
    from baps.language_zig import ZigLanguagePlugin

    assert ZigLanguagePlugin.docker_image == "rawpair/zig:latest"


def test_zig_plugin_test_command() -> None:
    from baps.language_zig import ZigLanguagePlugin

    assert ZigLanguagePlugin.test_command == "zig build test"


def test_zig_plugin_initialize_creates_build_zig(tmp_path: Path) -> None:
    from baps.language_zig import ZigLanguagePlugin

    ZigLanguagePlugin().initialize(tmp_path)
    assert (tmp_path / "build.zig").exists()


def test_zig_plugin_initialize_creates_src_main_zig(tmp_path: Path) -> None:
    from baps.language_zig import ZigLanguagePlugin

    ZigLanguagePlugin().initialize(tmp_path)
    assert (tmp_path / "src" / "main.zig").exists()


def test_zig_plugin_initialize_creates_gitignore(tmp_path: Path) -> None:
    from baps.language_zig import ZigLanguagePlugin, _GITIGNORE_CONTENT

    ZigLanguagePlugin().initialize(tmp_path)
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == _GITIGNORE_CONTENT


def test_zig_plugin_initialize_returns_true_first_call(tmp_path: Path) -> None:
    from baps.language_zig import ZigLanguagePlugin

    assert ZigLanguagePlugin().initialize(tmp_path) is True


def test_zig_plugin_initialize_returns_false_when_unchanged(tmp_path: Path) -> None:
    from baps.language_zig import ZigLanguagePlugin

    plugin = ZigLanguagePlugin()
    plugin.initialize(tmp_path)
    assert plugin.initialize(tmp_path) is False


def test_zig_plugin_initialize_skips_existing_files(tmp_path: Path) -> None:
    from baps.language_zig import ZigLanguagePlugin

    build_zig = tmp_path / "build.zig"
    build_zig.write_text("// custom build\n", encoding="utf-8")
    ZigLanguagePlugin().initialize(tmp_path)
    assert build_zig.read_text(encoding="utf-8") == "// custom build\n"


def test_zig_plugin_has_tests_detects_zig_files() -> None:
    from baps.language_zig import ZigLanguagePlugin

    assert ZigLanguagePlugin().has_tests(["src/main.zig"]) is True


def test_zig_plugin_has_tests_returns_false_for_non_zig() -> None:
    from baps.language_zig import ZigLanguagePlugin

    assert ZigLanguagePlugin().has_tests(["README.md", "src/foo.c"]) is False


def test_zig_plugin_has_tests_returns_false_for_empty() -> None:
    from baps.language_zig import ZigLanguagePlugin

    assert ZigLanguagePlugin().has_tests([]) is False


def test_zig_plugin_parse_test_failures_empty() -> None:
    from baps.language_zig import ZigLanguagePlugin

    assert ZigLanguagePlugin().parse_test_failures("") == []


def test_zig_plugin_parse_test_failures_detects_fail_lines() -> None:
    from baps.language_zig import ZigLanguagePlugin

    stdout = "FAIL test.my_test\nAll 1 tests ran.\n"
    result = ZigLanguagePlugin().parse_test_failures(stdout)
    assert len(result) == 1
    assert "my_test" in result[0]["test_id"]


def test_zig_plugin_run_tests_bare_uses_zig_build_test(tmp_path: Path) -> None:
    from baps.language_zig import ZigLanguagePlugin

    completed = _make_completed(returncode=0, stdout="All tests passed")
    with patch("baps.language_zig.subprocess.run", return_value=completed) as mock_run:
        result = ZigLanguagePlugin().run_tests(tmp_path, "none")

    assert result.passed is True
    assert mock_run.call_args[0][0] == ["zig", "build", "test"]
    assert result.command == "zig build test"


def test_zig_plugin_run_tests_docker_uses_plugin_values(tmp_path: Path) -> None:
    from baps.language_zig import ZigLanguagePlugin

    plugin = ZigLanguagePlugin()
    completed = _make_completed(returncode=0)
    with patch("baps.sandbox.subprocess.run", return_value=completed) as mock_run:
        result = plugin.run_tests(tmp_path, "docker")

    docker_args = mock_run.call_args[0][0]
    assert plugin.docker_image in docker_args
    assert plugin.test_command in docker_args


# ---------------------------------------------------------------------------
# CodingProjectAdapter.verify_export Zig wiring
# ---------------------------------------------------------------------------

def test_coding_adapter_verify_export_zig_uses_zig_docker_image(tmp_path: Path) -> None:
    from baps.coding_adapter import CodingProjectAdapter
    from baps.state import CodingArtifact, CodeFile, State

    artifact = CodingArtifact(id="art", language="zig", files=(
        CodeFile(path="src/main.zig", content="// hello"),
    ))
    state = State(artifacts=(artifact,))
    output_path = tmp_path / "output"
    (output_path / "src").mkdir(parents=True)
    (output_path / "src" / "main.zig").write_text("// hello", encoding="utf-8")

    completed = _make_completed(returncode=0)
    with patch("baps.sandbox.subprocess.run", return_value=completed) as mock_run:
        CodingProjectAdapter().verify_export(output_path, state, "art", sandbox_mode="docker")

    docker_args = mock_run.call_args[0][0]
    assert "rawpair/zig:latest" in docker_args


def test_coding_adapter_verify_export_zig_uses_zig_test_command(tmp_path: Path) -> None:
    from baps.coding_adapter import CodingProjectAdapter
    from baps.state import CodingArtifact, CodeFile, State

    artifact = CodingArtifact(id="art", language="zig", files=(
        CodeFile(path="src/main.zig", content="// hello"),
    ))
    state = State(artifacts=(artifact,))
    output_path = tmp_path / "output"
    (output_path / "src").mkdir(parents=True)
    (output_path / "src" / "main.zig").write_text("// hello", encoding="utf-8")

    completed = _make_completed(returncode=0)
    with patch("baps.sandbox.subprocess.run", return_value=completed) as mock_run:
        CodingProjectAdapter().verify_export(output_path, state, "art", sandbox_mode="docker")

    docker_args = mock_run.call_args[0][0]
    assert "zig build test" in docker_args


def test_coding_adapter_verify_export_zig_does_not_use_python_image(tmp_path: Path) -> None:
    from baps.coding_adapter import CodingProjectAdapter
    from baps.state import CodingArtifact, CodeFile, State

    artifact = CodingArtifact(id="art", language="zig", files=(
        CodeFile(path="src/main.zig", content="// hello"),
    ))
    state = State(artifacts=(artifact,))
    output_path = tmp_path / "output"
    (output_path / "src").mkdir(parents=True)
    (output_path / "src" / "main.zig").write_text("// hello", encoding="utf-8")

    completed = _make_completed(returncode=0)
    with patch("baps.sandbox.subprocess.run", return_value=completed) as mock_run:
        CodingProjectAdapter().verify_export(output_path, state, "art", sandbox_mode="docker")

    docker_args = mock_run.call_args[0][0]
    assert "python:3.12-slim" not in docker_args


# ---------------------------------------------------------------------------
# CodingProjectAdapter.verify_candidate Zig wiring
# ---------------------------------------------------------------------------

def test_coding_adapter_verify_candidate_zig_uses_zig_docker_image(tmp_path: Path) -> None:
    from baps.coding_adapter import CodingProjectAdapter
    from baps.state import CodingArtifact, DeltaCodingState, State

    state = State(artifacts=(CodingArtifact(id="art", language="zig", files=()),))
    delta = DeltaCodingState.model_validate({
        "artifact_id": "art",
        "operation": "write_file",
        "payload": {"file": {"path": "src/main.zig", "content": "// hello"}},
    })

    completed = _make_completed(returncode=0)
    with patch("baps.sandbox.subprocess.run", return_value=completed) as mock_run:
        result = CodingProjectAdapter().verify_candidate(delta, state, "art", sandbox_mode="docker")

    assert result is not None
    docker_args = mock_run.call_args[0][0]
    assert "rawpair/zig:latest" in docker_args


def test_coding_adapter_verify_candidate_zig_uses_zig_test_command(tmp_path: Path) -> None:
    from baps.coding_adapter import CodingProjectAdapter
    from baps.state import CodingArtifact, DeltaCodingState, State

    state = State(artifacts=(CodingArtifact(id="art", language="zig", files=()),))
    delta = DeltaCodingState.model_validate({
        "artifact_id": "art",
        "operation": "write_file",
        "payload": {"file": {"path": "src/main.zig", "content": "// hello"}},
    })

    completed = _make_completed(returncode=0)
    with patch("baps.sandbox.subprocess.run", return_value=completed) as mock_run:
        result = CodingProjectAdapter().verify_candidate(delta, state, "art", sandbox_mode="docker")

    assert result is not None
    docker_args = mock_run.call_args[0][0]
    assert "zig build test" in docker_args


def test_coding_adapter_verify_candidate_zig_does_not_use_python_image(tmp_path: Path) -> None:
    from baps.coding_adapter import CodingProjectAdapter
    from baps.state import CodingArtifact, DeltaCodingState, State

    state = State(artifacts=(CodingArtifact(id="art", language="zig", files=()),))
    delta = DeltaCodingState.model_validate({
        "artifact_id": "art",
        "operation": "write_file",
        "payload": {"file": {"path": "src/main.zig", "content": "// hello"}},
    })

    completed = _make_completed(returncode=0)
    with patch("baps.sandbox.subprocess.run", return_value=completed) as mock_run:
        result = CodingProjectAdapter().verify_candidate(delta, state, "art", sandbox_mode="docker")

    assert result is not None
    docker_args = mock_run.call_args[0][0]
    assert "python:3.12-slim" not in docker_args
