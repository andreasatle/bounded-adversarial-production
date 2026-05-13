from __future__ import annotations

import json
from pathlib import Path

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
    def load_text(self, declaration: StateSourceDeclaration) -> str:
        raise NotImplementedError


class MarkdownFileStateSourceAdapter(StateSourceAdapter):
    def load_text(self, declaration: StateSourceDeclaration) -> str:
        if declaration.kind != "markdown_doc":
            raise ValueError("unsupported state source kind for markdown adapter")
        path = Path(declaration.ref)
        if not path.exists():
            raise FileNotFoundError(f"state source file not found: {declaration.ref}")
        return path.read_text(encoding="utf-8")
