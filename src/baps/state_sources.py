from __future__ import annotations

import json
from pathlib import Path
import subprocess

from pydantic import BaseModel, Field, ValidationError, field_validator


def _require_non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("must be a non-empty string")
    return value


class StateSourceDeclaration(BaseModel):
    id: str
    kind: str
    ref: str
    authority: str = "context"
    metadata: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_kind = field_validator("kind")(_require_non_empty)
    _validate_ref = field_validator("ref")(_require_non_empty)
    _validate_authority = field_validator("authority")(_require_non_empty)


class StateManifest(BaseModel):
    project_id: str
    sources: list[StateSourceDeclaration]

    _validate_project_id = field_validator("project_id")(_require_non_empty)

    @field_validator("sources")
    @classmethod
    def _validate_sources(cls, value: list[StateSourceDeclaration]) -> list[StateSourceDeclaration]:
        if not value:
            raise ValueError("sources must be non-empty")
        ids = [source.id for source in value]
        if len(ids) != len(set(ids)):
            raise ValueError("source ids must be unique")
        return value


def load_state_manifest(path: Path) -> StateManifest:
    if not path.exists():
        raise FileNotFoundError(f"state manifest file not found: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in state manifest file: {path}") from exc
    try:
        return StateManifest.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"invalid StateManifest schema in file: {path}") from exc


class StateSourceAdapter:
    def supports(self, kind: str) -> bool:
        raise NotImplementedError

    def load_text(self, declaration: StateSourceDeclaration) -> str:
        raise NotImplementedError


class MarkdownFileStateSourceAdapter(StateSourceAdapter):
    def supports(self, kind: str) -> bool:
        return kind == "markdown_doc"

    def load_text(self, declaration: StateSourceDeclaration) -> str:
        if not self.supports(declaration.kind):
            raise ValueError("unsupported state source kind for markdown adapter")
        path = Path(declaration.ref)
        if not path.exists():
            raise FileNotFoundError(f"state source file not found: {declaration.ref}")
        return path.read_text(encoding="utf-8")


class JsonlEventLogStateSourceAdapter(StateSourceAdapter):
    def supports(self, kind: str) -> bool:
        return kind == "jsonl_event_log"

    def load_text(self, declaration: StateSourceDeclaration) -> str:
        if not self.supports(declaration.kind):
            raise ValueError("unsupported state source kind for jsonl event log adapter")
        path = Path(declaration.ref)
        if not path.exists():
            raise FileNotFoundError(f"state source file not found: {declaration.ref}")
        return path.read_text(encoding="utf-8")


class DirectoryStateSourceAdapter(StateSourceAdapter):
    def supports(self, kind: str) -> bool:
        return kind == "directory"

    def load_text(self, declaration: StateSourceDeclaration) -> str:
        if not self.supports(declaration.kind):
            raise ValueError("unsupported state source kind for directory adapter")
        path = Path(declaration.ref)
        if not path.exists():
            raise FileNotFoundError(f"state source directory not found: {declaration.ref}")
        if not path.is_dir():
            raise ValueError(f"state source path is not a directory: {declaration.ref}")

        lines = [f"DIRECTORY: {declaration.ref}"]
        children = sorted(path.iterdir(), key=lambda child: child.name)
        for child in children:
            kind = "directory" if child.is_dir() else "file"
            lines.append(f"- {child.name} [{kind}]")
        return "\n".join(lines)


class GitRepoStateSourceAdapter(StateSourceAdapter):
    def supports(self, kind: str) -> bool:
        return kind == "git_repo"

    def load_text(self, declaration: StateSourceDeclaration) -> str:
        if not self.supports(declaration.kind):
            raise ValueError("unsupported state source kind for git repo adapter")
        path = Path(declaration.ref)
        if not path.exists():
            raise FileNotFoundError(f"state source path not found: {declaration.ref}")
        if not path.is_dir():
            raise ValueError(f"state source path is not a directory: {declaration.ref}")

        def _run_git(args: list[str]) -> str:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(path),
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                error = (proc.stderr or proc.stdout).strip()
                raise ValueError(f"git command failed ({' '.join(args)}): {error}")
            return proc.stdout

        branch = _run_git(["branch", "--show-current"]).strip()
        status = _run_git(["status", "--short"]).rstrip("\n")
        commits = _run_git(["log", "--oneline", "-n", "10"]).rstrip("\n")

        return (
            f"GIT REPOSITORY: {declaration.ref}\n"
            "BRANCH:\n"
            f"{branch}\n\n"
            "STATUS:\n"
            f"{status}\n\n"
            "RECENT COMMITS:\n"
            f"{commits}"
        )


class RoutingStateSourceAdapter(StateSourceAdapter):
    def __init__(self, adapters: list[StateSourceAdapter]):
        self.adapters = adapters

    def supports(self, kind: str) -> bool:
        return any(adapter.supports(kind) for adapter in self.adapters)

    def load_text(self, declaration: StateSourceDeclaration) -> str:
        for adapter in self.adapters:
            if adapter.supports(declaration.kind):
                return adapter.load_text(declaration)
        raise ValueError(f"unsupported state source kind: {declaration.kind}")


def resolve_state_context(
    manifest: StateManifest,
    source_ids: list[str],
    adapter: StateSourceAdapter,
) -> str:
    if not source_ids:
        return ""

    by_id = {source.id: source for source in manifest.sources}
    parts: list[str] = []
    for source_id in source_ids:
        source = by_id.get(source_id)
        if source is None:
            raise ValueError(f"state source id not found in manifest: {source_id}")
        content = adapter.load_text(source)
        parts.append(
            f"===== STATE SOURCE: {source.id} ({source.kind}, authority={source.authority}) =====\n{content}"
        )
    return "\n\n".join(parts)
