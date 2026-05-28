from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Sequence

from baps.adapters.project_adapter import VerificationResult


_CONFTEST_CONTENT = (
    "import sys, os\n"
    'sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))\n'
)

_GITIGNORE_CONTENT = (
    "__pycache__/\n"
    "*.pyc\n"
    "*.pyo\n"
    ".pytest_cache/\n"
    "*.egg-info/\n"
    "dist/\n"
    "build/\n"
    ".venv/\n"
    "uv.lock\n"
)


def _parse_pytest_failures(stdout: str) -> list[dict[str, str]]:
    failures = []
    for line in stdout.splitlines():
        if line.startswith("FAILED "):
            rest = line[len("FAILED "):]
            if " - " in rest:
                test_id, reason = rest.split(" - ", 1)
            else:
                test_id, reason = rest, ""
            failures.append({"test_id": test_id.strip(), "reason": reason.strip()})
    return failures


class PythonLanguagePlugin:
    name = "python"
    docker_image = "python:3.12-slim"
    test_command = "pip install pytest -q 2>/dev/null && python -m pytest"

    def initialize(self, project_path: Path) -> bool:
        project_path.mkdir(parents=True, exist_ok=True)
        changed = False

        conftest_path = project_path / "conftest.py"
        conftest_before = (
            conftest_path.read_text(encoding="utf-8") if conftest_path.exists() else None
        )
        if conftest_before != _CONFTEST_CONTENT:
            conftest_path.write_text(_CONFTEST_CONTENT, encoding="utf-8")
            changed = True

        gitignore_path = project_path / ".gitignore"
        gitignore_before = (
            gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else None
        )
        if gitignore_before != _GITIGNORE_CONTENT:
            gitignore_path.write_text(_GITIGNORE_CONTENT, encoding="utf-8")
            changed = True

        return changed

    def run_tests(self, project_path: Path, sandbox_mode: str) -> VerificationResult:
        if sandbox_mode == "none":
            command, completed = self._run_bare(project_path)
        else:
            from baps.tools.sandbox import run_sandboxed
            command, completed = run_sandboxed(
                project_path, sandbox_mode, self.test_command, self.docker_image
            )
        return VerificationResult(
            command=command,
            cwd=str(project_path),
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            passed=completed.returncode == 0,
        )

    def _run_bare(self, project_path: Path) -> tuple[str, subprocess.CompletedProcess]:
        # Use uv when available; fall back to the current interpreter.
        # test_command is for Docker (needs pip install); bare execution relies
        # on the dev environment having pytest already installed.
        try:
            completed = subprocess.run(
                ["uv", "run", "pytest"],
                cwd=project_path, capture_output=True, text=True, check=False,
            )
            return "uv run pytest", completed
        except FileNotFoundError:
            completed = subprocess.run(
                [sys.executable, "-m", "pytest"],
                cwd=project_path, capture_output=True, text=True, check=False,
            )
            return f"{sys.executable} -m pytest", completed

    def build(self, project_path: Path) -> None:
        pass

    def parse_test_failures(self, stdout: str) -> list[dict[str, str]]:
        return _parse_pytest_failures(stdout)

    def has_tests(self, file_paths: Sequence[str]) -> bool:
        return any(
            p.startswith("tests/") or p.startswith("test_")
            for p in file_paths
        )
