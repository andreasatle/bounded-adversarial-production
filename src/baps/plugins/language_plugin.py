from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable

from baps.adapters.project_adapter import VerificationResult
from baps.state.state import CodeFile


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

    def summarize_file(self, file: CodeFile, objective: str | None) -> str:
        """Return a summary of *file* relative to *objective*.

        When objective is None: structural API surface (signatures, doc comments,
        test names, line count — no bodies).
        When objective is provided: objective-aware summary of what the file does
        relative to that goal.
        """
        raise NotImplementedError

    def supported_filters(self) -> list[str]:
        """Return filter values supported by this plugin's extract_* methods."""
        raise NotImplementedError

    def extract_api(self, file: CodeFile) -> str:
        """Return the API surface of *file*: signatures and docstring first lines, no bodies."""
        raise NotImplementedError

    def extract_tests(self, file: CodeFile) -> str:
        """Return test function names from *file* grouped under 'Tests:'."""
        raise NotImplementedError

    def extract_entity(self, file: CodeFile, entity_id: str, filter: str | None) -> str:
        """Return a top-level entity (function or class) from *file* shaped by *filter*.

        filter=None or 'full': complete source body.
        filter='api': signature and docstring first line only.
        Unknown filter: return helpful error string listing supported filters.
        """
        raise NotImplementedError


def get_language_plugin(name: str) -> LanguagePlugin:
    """Return the plugin for *name*, raising ValueError if not registered."""
    from baps.plugins.language_python import PythonLanguagePlugin
    from baps.plugins.language_rust import RustLanguagePlugin
    from baps.plugins.language_zig import ZigLanguagePlugin

    _registry: dict[str, LanguagePlugin] = {
        "python": PythonLanguagePlugin(),
        "rust": RustLanguagePlugin(),
        "zig": ZigLanguagePlugin(),
    }
    if name not in _registry:
        available = ", ".join(sorted(_registry))
        raise ValueError(
            f"Language {name!r} is not supported. Available languages: {available}"
        )
    return _registry[name]
