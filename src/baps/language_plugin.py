from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable

from baps.project_adapter import VerificationResult


@runtime_checkable
class LanguagePlugin(Protocol):
    """Contract for language-specific project setup and test execution."""

    name: str
    test_command: str
    docker_image: str

    def initialize(self, project_path: Path) -> bool:
        """Set up project boilerplate (e.g. conftest, .gitignore). Returns True if any files changed."""
        ...

    def run_tests(self, project_path: Path, sandbox_mode: str) -> VerificationResult:
        """Run the test suite and return exit code + output."""
        ...

    def build(self, project_path: Path) -> None:
        """Compile or build the project. No-op for interpreted languages."""
        ...

    def parse_test_failures(self, stdout: str) -> list[dict[str, str]]:
        """Extract structured failure records from test runner stdout."""
        ...

    def has_tests(self, file_paths: Sequence[str]) -> bool:
        """Return True if any of the given paths look like test files for this language."""
        ...


def get_language_plugin(name: str) -> LanguagePlugin:
    """Return the plugin for *name*, raising ValueError if not registered."""
    from baps.language_python import PythonLanguagePlugin

    _registry: dict[str, LanguagePlugin] = {
        "python": PythonLanguagePlugin(),
    }
    if name not in _registry:
        raise ValueError(
            f"unknown language plugin {name!r}; supported: {sorted(_registry)}"
        )
    return _registry[name]
