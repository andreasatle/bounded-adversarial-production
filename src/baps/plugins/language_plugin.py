"""Defines the LanguagePlugin protocol and the plugin registry for language-specific project support."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable

from baps.adapters.project_adapter import VerificationResult
from baps.state.state import CodeFile


@runtime_checkable
class LanguagePlugin(Protocol):
    """Contract for deterministic language-specific setup, verification, and structural extraction.

    Model-based summarization is handled by SummarizationContext + SUMMARIZE role,
    not by this plugin protocol.
    """

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

    def supported_filters(self) -> list[str]:
        """Return filter values supported by this plugin's extract_* methods."""
        raise NotImplementedError

    def extract_api(self, file: CodeFile) -> str:
        """Return deterministic API surface of *file*: signatures and doc first lines, no bodies."""
        raise NotImplementedError

    def extract_tests(self, file: CodeFile) -> str:
        """Return deterministic test entity listing from *file*."""
        raise NotImplementedError

    def extract_entity(self, file: CodeFile, entity_id: str, filter: str | None) -> str:
        """Return a deterministic top-level entity projection from *file* shaped by *filter*.

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
