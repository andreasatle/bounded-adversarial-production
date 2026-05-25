"""Tests for sandbox execution boundary (src/baps/sandbox.py)."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch


_TEST_COMMAND = "my_test_runner --verbose"
_DOCKER_IMAGE = "example:1.0"


def _make_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    result: subprocess.CompletedProcess = MagicMock(spec=subprocess.CompletedProcess)
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


# --- Warning constant ---

def test_sandbox_none_warning_contains_expected_text() -> None:
    from baps.sandbox import SANDBOX_NONE_WARNING

    assert "sandbox=none" in SANDBOX_NONE_WARNING
    assert "unsafe" in SANDBOX_NONE_WARNING.lower() or "unsandboxed" in SANDBOX_NONE_WARNING.lower()
    assert "production" in SANDBOX_NONE_WARNING.lower()


# --- _run_bare ---

def test_run_bare_runs_test_command(tmp_path: Path) -> None:
    from baps.sandbox import _run_bare

    completed = _make_completed(returncode=0, stdout="1 passed")
    with patch("baps.sandbox.subprocess.run", return_value=completed) as mock_run:
        command, result = _run_bare(tmp_path, _TEST_COMMAND)

    assert command == _TEST_COMMAND
    assert result.returncode == 0
    assert mock_run.call_args[0][0] == _TEST_COMMAND
    assert mock_run.call_args.kwargs.get("shell") is True
    assert mock_run.call_args.kwargs.get("cwd") == tmp_path


def test_run_bare_returns_test_command_as_command_string(tmp_path: Path) -> None:
    from baps.sandbox import _run_bare

    completed = _make_completed(returncode=1)
    with patch("baps.sandbox.subprocess.run", return_value=completed):
        command, _ = _run_bare(tmp_path, _TEST_COMMAND)

    assert command == _TEST_COMMAND


# --- _run_docker ---

def test_run_docker_constructs_correct_command(tmp_path: Path) -> None:
    from baps.sandbox import _run_docker

    completed = _make_completed(returncode=0, stdout="1 passed")
    with patch("baps.sandbox.subprocess.run", return_value=completed) as mock_run:
        command, result = _run_docker(tmp_path, _TEST_COMMAND, _DOCKER_IMAGE)

    docker_args = mock_run.call_args[0][0]
    assert docker_args[0] == "docker"
    assert docker_args[1] == "run"
    assert "--rm" in docker_args
    assert _DOCKER_IMAGE in docker_args
    assert _TEST_COMMAND in docker_args
    assert result.returncode == 0


def test_run_docker_passes_test_command_to_sh(tmp_path: Path) -> None:
    from baps.sandbox import _run_docker

    completed = _make_completed(returncode=0)
    with patch("baps.sandbox.subprocess.run", return_value=completed) as mock_run:
        _run_docker(tmp_path, _TEST_COMMAND, _DOCKER_IMAGE)

    docker_args = mock_run.call_args[0][0]
    sh_index = docker_args.index("sh")
    assert docker_args[sh_index + 1] == "-c"
    assert docker_args[sh_index + 2] == _TEST_COMMAND


def test_run_docker_returns_command_string(tmp_path: Path) -> None:
    from baps.sandbox import _run_docker

    completed = _make_completed(returncode=0)
    with patch("baps.sandbox.subprocess.run", return_value=completed):
        command, _ = _run_docker(tmp_path, _TEST_COMMAND, _DOCKER_IMAGE)

    assert isinstance(command, str)
    assert "docker" in command
    assert _DOCKER_IMAGE in command
    assert _TEST_COMMAND in command


def test_run_docker_rm_flag_ensures_cleanup(tmp_path: Path) -> None:
    """--rm prevents persistent containers accumulating on the host."""
    from baps.sandbox import _run_docker

    completed = _make_completed(returncode=0)
    with patch("baps.sandbox.subprocess.run", return_value=completed) as mock_run:
        _run_docker(tmp_path, _TEST_COMMAND, _DOCKER_IMAGE)

    docker_args = mock_run.call_args[0][0]
    assert "--rm" in docker_args


def test_run_docker_bind_mount_scoped_to_cwd_only(tmp_path: Path) -> None:
    """The bind mount must be exactly the target directory — not the root or parent."""
    from baps.sandbox import _run_docker

    completed = _make_completed(returncode=0)
    with patch("baps.sandbox.subprocess.run", return_value=completed) as mock_run:
        _run_docker(tmp_path, _TEST_COMMAND, _DOCKER_IMAGE)

    docker_args = mock_run.call_args[0][0]
    v_index = docker_args.index("-v")
    mount_spec = docker_args[v_index + 1]
    host_path, container_path_and_mode = mount_spec.split(":", 1)

    assert host_path == str(tmp_path.resolve())
    assert container_path_and_mode == "/work:rw"
    remaining = docker_args[v_index + 2:]
    assert "-v" not in remaining


def test_run_docker_does_not_mount_host_root(tmp_path: Path) -> None:
    """Docker args must not bind-mount the host root or sensitive system directories."""
    from baps.sandbox import _run_docker

    completed = _make_completed(returncode=0)
    with patch("baps.sandbox.subprocess.run", return_value=completed) as mock_run:
        _run_docker(tmp_path, _TEST_COMMAND, _DOCKER_IMAGE)

    docker_args = mock_run.call_args[0][0]
    for i, arg in enumerate(docker_args):
        if arg == "-v" and i + 1 < len(docker_args):
            mount_spec = docker_args[i + 1]
            host_part = mount_spec.split(":")[0]
            assert host_part != "/"
            assert not host_part.startswith("/etc")
            assert not host_part.startswith("/usr")
            assert not host_part.startswith("/home")


def test_run_docker_does_not_use_privileged_flag(tmp_path: Path) -> None:
    """Privileged mode grants full host access — must never be used."""
    from baps.sandbox import _run_docker

    completed = _make_completed(returncode=0)
    with patch("baps.sandbox.subprocess.run", return_value=completed) as mock_run:
        _run_docker(tmp_path, _TEST_COMMAND, _DOCKER_IMAGE)

    docker_args = mock_run.call_args[0][0]
    assert "--privileged" not in docker_args


def test_run_docker_uses_resolved_path_not_symlink(tmp_path: Path) -> None:
    """Symlinks in cwd are resolved so the mount target is always the canonical path."""
    from baps.sandbox import _run_docker

    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link_dir = tmp_path / "link"
    link_dir.symlink_to(real_dir)

    completed = _make_completed(returncode=0)
    with patch("baps.sandbox.subprocess.run", return_value=completed) as mock_run:
        _run_docker(link_dir, _TEST_COMMAND, _DOCKER_IMAGE)

    docker_args = mock_run.call_args[0][0]
    v_index = docker_args.index("-v")
    mount_spec = docker_args[v_index + 1]
    host_path = mount_spec.split(":")[0]

    assert host_path == str(real_dir.resolve())
    assert "link" not in host_path


# --- run_sandboxed ---

def test_run_sandboxed_none_mode_calls_bare(tmp_path: Path) -> None:
    from baps.sandbox import run_sandboxed

    completed = _make_completed(returncode=0)
    with patch("baps.sandbox.subprocess.run", return_value=completed) as mock_run:
        command, result = run_sandboxed(tmp_path, "none", _TEST_COMMAND, _DOCKER_IMAGE)

    assert command == _TEST_COMMAND
    assert result.returncode == 0
    assert mock_run.call_args.kwargs.get("shell") is True


def test_run_sandboxed_docker_mode_calls_docker(tmp_path: Path) -> None:
    from baps.sandbox import run_sandboxed

    completed = _make_completed(returncode=0)
    with patch("baps.sandbox.subprocess.run", return_value=completed) as mock_run:
        command, result = run_sandboxed(tmp_path, "docker", _TEST_COMMAND, _DOCKER_IMAGE)

    docker_args = mock_run.call_args[0][0]
    assert docker_args[0] == "docker"
    assert _DOCKER_IMAGE in docker_args
    assert _TEST_COMMAND in docker_args


def test_run_sandboxed_unknown_mode_raises(tmp_path: Path) -> None:
    from baps.sandbox import run_sandboxed
    import pytest

    with pytest.raises(ValueError, match="unknown sandbox_mode"):
        run_sandboxed(tmp_path, "qemu", _TEST_COMMAND, _DOCKER_IMAGE)


# --- Python plugin supplies correct values to sandbox ---

def test_python_plugin_docker_image_is_passed_to_docker(tmp_path: Path) -> None:
    from baps.sandbox import _run_docker
    from baps.language_python import PythonLanguagePlugin

    plugin = PythonLanguagePlugin()
    completed = _make_completed(returncode=0)
    with patch("baps.sandbox.subprocess.run", return_value=completed) as mock_run:
        _run_docker(tmp_path, plugin.test_command, plugin.docker_image)

    docker_args = mock_run.call_args[0][0]
    assert plugin.docker_image in docker_args
    assert plugin.test_command in docker_args


# --- is_docker_available ---

def test_is_docker_available_returns_true_when_docker_info_succeeds() -> None:
    from baps.sandbox import is_docker_available

    completed = _make_completed(returncode=0)
    with patch("baps.sandbox.subprocess.run", return_value=completed):
        assert is_docker_available() is True


def test_is_docker_available_returns_false_when_docker_not_found() -> None:
    from baps.sandbox import is_docker_available

    with patch("baps.sandbox.subprocess.run", side_effect=FileNotFoundError):
        assert is_docker_available() is False


def test_is_docker_available_returns_false_when_docker_info_fails() -> None:
    from baps.sandbox import is_docker_available

    completed = _make_completed(returncode=1)
    with patch("baps.sandbox.subprocess.run", return_value=completed):
        assert is_docker_available() is False


def test_is_docker_available_returns_false_on_timeout() -> None:
    from baps.sandbox import is_docker_available

    with patch("baps.sandbox.subprocess.run", side_effect=subprocess.TimeoutExpired("docker", 5)):
        assert is_docker_available() is False
