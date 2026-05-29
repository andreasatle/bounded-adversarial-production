from __future__ import annotations

import re
from pathlib import Path

from baps.plugins.language_plugin import LanguagePlugin
from baps.state.state import CodingArtifact, State

_UNSAFE_PATH_CHARS_RE = re.compile(r'[;&|`$<>!\x00]')

_BLUE_CONTENT_FORBIDDEN_MARKERS: tuple[str, ...] = (
    "Note:",
    "Correction:",
    "Correcting",
    "Re-writing",
    "Rewriting",
    "self-contained issue",
    "Re-reading context",
)


def _validate_file_path(path: str) -> None:
    """Reject file paths that could escape the output directory or inject into shell commands."""
    if not path or not path.strip():
        raise ValueError("file path must be non-empty")
    p = Path(path)
    if p.is_absolute():
        raise ValueError(f"file path must be relative, not absolute: {path!r}")
    if ".." in p.parts:
        raise ValueError(f"file path must not contain '..' components: {path!r}")
    if _UNSAFE_PATH_CHARS_RE.search(path):
        raise ValueError(f"file path contains unsafe characters: {path!r}")


def _build_language_registry() -> dict[str, LanguagePlugin]:
    from baps.plugins.language_python import PythonLanguagePlugin
    from baps.plugins.language_rust import RustLanguagePlugin
    from baps.plugins.language_zig import ZigLanguagePlugin

    return {
        "python": PythonLanguagePlugin(),
        "rust": RustLanguagePlugin(),
        "zig": ZigLanguagePlugin(),
    }


def _plugin_for(language: str) -> LanguagePlugin:
    registry = _build_language_registry()
    if language not in registry:
        available = ", ".join(sorted(registry))
        raise ValueError(
            f"Language {language!r} is not supported. Available languages: {available}"
        )
    return registry[language]


def _config_language(config: dict[str, object]) -> str:
    language = config.get("language")
    if not language:
        registry = _build_language_registry()
        available = ", ".join(sorted(registry))
        raise ValueError(
            f"coding project spec requires a 'language' field. Available languages: {available}"
        )
    return str(language)


def coding_artifact_from_state(state: State, artifact_id: str) -> CodingArtifact:
    artifact = next((a for a in state.artifacts if a.id == artifact_id), None)
    if artifact is None:
        raise ValueError(f"target coding artifact not found in state: {artifact_id}")
    if not isinstance(artifact, CodingArtifact):
        raise ValueError(f"target artifact must be CodingArtifact: {artifact_id}")
    return artifact
