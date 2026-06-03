"""LanguagePlugin implementation for Rust: test execution and deterministic structural extraction."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Sequence

from baps.adapters.project_adapter import VerificationResult
from baps.tools.sandbox import DOCKER_DAEMON_ERROR, is_docker_unavailable_error

DOCKER_IMAGE = "baps-rust-indexer:latest"
BUILD_CMD = "docker build -t baps-rust-indexer:latest -f docker/rust-indexer/Dockerfile ."


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
        gitignore_before = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else None
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

            command, completed = run_sandboxed(project_path, sandbox_mode, self.test_command, self.docker_image)
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
            cwd=project_path,
            capture_output=True,
            text=True,
            check=False,
        )
        return "cargo test", completed

    def build(self, project_path: Path) -> None:
        """Handle build."""
        result = subprocess.run(
            ["cargo", "build"],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"cargo build failed (exit {result.returncode}):\n{result.stderr}")

    def parse_test_failures(self, stdout: str) -> list[dict[str, str]]:
        """Parse and return test failures."""
        failures = []
        for line in stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("test ") and stripped.endswith("... FAILED"):
                test_id = stripped[len("test ") : -len("... FAILED")].strip()
                failures.append({"test_id": test_id, "reason": ""})
        return failures

    def has_tests(self, file_paths: Sequence[str]) -> bool:
        """Return whether the object has tests."""
        return any(p.endswith(".rs") for p in file_paths)

    def supported_filters(self) -> list[str]:
        """Return supported values for extract filters."""
        return ["api", "tests", "full"]

    def extract_api(self, file, filter=None) -> str:
        """Return public API surface: signatures and first doc lines, no bodies."""
        items = self._run_indexer(file)
        pub_items = [it for it in items if it["pub"] and it["kind"] in ("fn", "struct", "trait", "enum", "type")]
        line_count = len(file.content.splitlines())
        parts = [f"// {file.path} ({line_count} lines)"]
        for it in pub_items:
            parts.append(it["signature"])
            parts.append(f"  /// {it['doc'] or 'MISSING'}")
        return "\n".join(parts)

    def extract_tests(self, file) -> str:
        """Return test function names with doc lines."""
        items = self._run_indexer(file)
        test_items = [it for it in items if it["is_test"]]
        parts = [f"// Tests in {file.path}"]
        for it in test_items:
            parts.append(f"fn {it['name']}")
            parts.append(f"  /// {it['doc'] or 'MISSING'}")
        return "\n".join(parts)

    def extract_entity(self, file, entity_id: str, filter=None) -> str:
        """Return a named entity shaped by filter ('full' or 'api')."""
        items = self._run_indexer(file)
        matches = [it for it in items if it["name"] == entity_id]
        if not matches:
            available = ", ".join(it["name"] for it in items)
            return f"Entity {entity_id!r} not found in {file.path}.\nAvailable: {available}"
        it = matches[0]
        if filter == "api":
            return f"{it['signature']}\n  /// {it['doc'] or 'MISSING'}"
        src_lines = file.content.splitlines()
        return "\n".join(src_lines[it["body_start"] - 1 : it["body_end"]])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_indexer(self, file) -> list[dict]:
        try:
            result = subprocess.run(
                ["docker", "run", "--rm", "-i", DOCKER_IMAGE],
                input=file.content,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr or ""
            if is_docker_unavailable_error(stderr):
                raise RuntimeError(DOCKER_DAEMON_ERROR) from exc
            if "Unable to find image" in stderr or "No such image" in stderr or "pull access denied" in stderr:
                raise RuntimeError(
                    f"RustLanguagePlugin: Docker image '{DOCKER_IMAGE}' not found.\nBuild it with: {BUILD_CMD}"
                ) from exc
            raise
        except FileNotFoundError:
            raise RuntimeError(
                f"RustLanguagePlugin: Docker image '{DOCKER_IMAGE}' not found.\nBuild it with: {BUILD_CMD}"
            )
        return json.loads(result.stdout)["items"]
