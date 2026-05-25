from __future__ import annotations

from pathlib import Path
from typing import Sequence

from baps.project_adapter import VerificationResult


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
        from baps.sandbox import run_pytest_sandboxed

        command, completed = run_pytest_sandboxed(project_path, sandbox_mode)
        return VerificationResult(
            command=command,
            cwd=str(project_path),
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            passed=completed.returncode == 0,
        )

    def build(self, project_path: Path) -> None:
        pass

    def parse_test_failures(self, stdout: str) -> list[dict[str, str]]:
        return _parse_pytest_failures(stdout)

    def has_tests(self, file_paths: Sequence[str]) -> bool:
        return any(
            p.startswith("tests/") or p.startswith("test_")
            for p in file_paths
        )
