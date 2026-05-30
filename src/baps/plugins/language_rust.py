"""LanguagePlugin implementation for Rust: test execution, API extraction, and file summarization."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

from baps.adapters.project_adapter import VerificationResult


_CARGO_TOML_CONTENT = """\
[package]
name = "project"
version = "0.1.0"
edition = "2021"

[dependencies]
"""

_LIB_RS_CONTENT = """\
#[cfg(test)]
mod tests {
    #[test]
    fn placeholder() {
        // TODO: implement
    }
}
"""

_GITIGNORE_CONTENT = "/target\n"


class RustLanguagePlugin:
    """Represent the RustLanguagePlugin type."""
    name = "rust"
    docker_image = "rust:latest"
    test_command = "cargo test"

    def initialize(self, project_path: Path) -> bool:
        """Handle initialize."""
        project_path.mkdir(parents=True, exist_ok=True)
        changed = False

        cargo_toml = project_path / "Cargo.toml"
        if not cargo_toml.exists():
            cargo_toml.write_text(_CARGO_TOML_CONTENT, encoding="utf-8")
            changed = True

        src_dir = project_path / "src"
        src_dir.mkdir(exist_ok=True)
        lib_rs = src_dir / "lib.rs"
        if not lib_rs.exists():
            lib_rs.write_text(_LIB_RS_CONTENT, encoding="utf-8")
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
        """Handle run tests."""
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
        """Handle run bare."""
        completed = subprocess.run(
            ["cargo", "test"],
            cwd=project_path, capture_output=True, text=True, check=False,
        )
        return "cargo test", completed

    def build(self, project_path: Path) -> None:
        """Handle build."""
        result = subprocess.run(
            ["cargo", "build"],
            cwd=project_path, capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"cargo build failed (exit {result.returncode}):\n{result.stderr}"
            )

    def parse_test_failures(self, stdout: str) -> list[dict[str, str]]:
        """Parse and return test failures."""
        failures = []
        for line in stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("test ") and stripped.endswith("... FAILED"):
                test_id = stripped[len("test "):-len("... FAILED")].strip()
                failures.append({"test_id": test_id, "reason": ""})
        return failures

    def has_tests(self, file_paths: Sequence[str]) -> bool:
        """Return whether the object has tests."""
        return any(p.endswith(".rs") for p in file_paths)

    def summarize_file(self, file, objective):
        """Handle summarize file."""
        raise NotImplementedError

    def supported_filters(self) -> list[str]:
        """Return supported values for ed filters."""
        return ["api", "tests", "full"]

    def extract_api(self, file, filter=None) -> str:
        """Extract and return api."""
        raise NotImplementedError

    def extract_tests(self, file) -> str:
        """Extract and return tests."""
        raise NotImplementedError

    def extract_entity(self, file, entity_id: str, filter=None) -> str:
        """Extract and return entity."""
        raise NotImplementedError
