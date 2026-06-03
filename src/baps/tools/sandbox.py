"""Runs test commands either bare (no sandbox) or inside an isolated Docker container."""

from __future__ import annotations

import subprocess
from pathlib import Path

SANDBOX_NONE_WARNING = (
    "\nWARNING: sandbox=none — generated code will execute unsandboxed.\n"
    "This is unsafe for adversarial or untrusted model output.\n"
    "Do not use in production.\n"
)

DOCKER_DAEMON_ERROR = (
    "Docker daemon is not running. Start it with: colima start\n(or 'open -a Docker' if using Docker Desktop)"
)

_DOCKER_UNAVAILABLE_HINTS = (
    "failed to connect to the docker API",
    "Cannot connect to the Docker daemon",
    "dial unix",
)


def is_docker_unavailable_error(stderr: str) -> bool:
    """Return True if stderr indicates the Docker daemon is not running."""
    return any(hint in stderr for hint in _DOCKER_UNAVAILABLE_HINTS)


def is_docker_available() -> bool:
    """Return True if Docker is installed and the daemon is reachable."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            check=False,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def run_sandboxed(
    cwd: Path,
    sandbox_mode: str,
    test_command: str,
    docker_image: str,
) -> tuple[str, subprocess.CompletedProcess]:
    """Run *test_command* in *cwd* under the configured sandbox.

    Returns (command_string, completed_process).
    Raises ValueError for unknown sandbox_mode.
    """
    if sandbox_mode == "none":
        return _run_bare(cwd, test_command)
    if sandbox_mode == "docker":
        return _run_docker(cwd, test_command, docker_image)
    raise ValueError(f"unknown sandbox_mode: {sandbox_mode!r}; expected 'docker' or 'none'")


def _run_bare(cwd: Path, test_command: str) -> tuple[str, subprocess.CompletedProcess]:
    """Run test_command directly in cwd via the shell without any sandboxing."""
    completed = subprocess.run(test_command, cwd=cwd, capture_output=True, text=True, check=False, shell=True)
    return test_command, completed


def _run_docker(cwd: Path, test_command: str, docker_image: str) -> tuple[str, subprocess.CompletedProcess]:
    """Run test_command inside a Docker container with cwd bind-mounted at /work."""
    resolved = cwd.resolve()
    docker_args = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{resolved}:/work:rw",
        "--workdir",
        "/work",
        docker_image,
        "sh",
        "-c",
        test_command,
    ]
    command = f"docker run --rm -v {resolved}:/work:rw --workdir /work {docker_image} sh -c '{test_command}'"
    completed = subprocess.run(docker_args, capture_output=True, text=True, check=False)
    if is_docker_unavailable_error(completed.stderr):
        raise RuntimeError(DOCKER_DAEMON_ERROR)
    return command, completed
