from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SANDBOX_DOCKER_IMAGE = "python:3.12-slim"

SANDBOX_NONE_WARNING = (
    "\nWARNING: sandbox=none — generated code will execute unsandboxed.\n"
    "This is unsafe for adversarial or untrusted model output.\n"
    "Do not use in production.\n"
)


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


def run_pytest_sandboxed(
    cwd: Path,
    sandbox_mode: str,
) -> tuple[str, subprocess.CompletedProcess]:
    """Run pytest in cwd under the configured sandbox.

    Returns (command_string, completed_process).
    Raises ValueError for unknown sandbox_mode.
    """
    if sandbox_mode == "none":
        return _run_pytest_bare(cwd)
    if sandbox_mode == "docker":
        return _run_pytest_docker(cwd)
    raise ValueError(f"unknown sandbox_mode: {sandbox_mode!r}; expected 'docker' or 'none'")


def _run_pytest_bare(cwd: Path) -> tuple[str, subprocess.CompletedProcess]:
    try:
        args = ["uv", "run", "pytest"]
        completed = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
        return "uv run pytest", completed
    except FileNotFoundError:
        args = [sys.executable, "-m", "pytest"]
        completed = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
        return f"{sys.executable} -m pytest", completed


def _run_pytest_docker(cwd: Path) -> tuple[str, subprocess.CompletedProcess]:
    resolved = cwd.resolve()
    docker_args = [
        "docker", "run", "--rm",
        "-v", f"{resolved}:/work:rw",
        "--workdir", "/work",
        _SANDBOX_DOCKER_IMAGE,
        "sh", "-c",
        "pip install pytest -q 2>/dev/null && python -m pytest",
    ]
    command = (
        f"docker run --rm -v {resolved}:/work:rw --workdir /work"
        f" {_SANDBOX_DOCKER_IMAGE} sh -c 'pip install pytest -q && python -m pytest'"
    )
    completed = subprocess.run(docker_args, capture_output=True, text=True, check=False)
    return command, completed
