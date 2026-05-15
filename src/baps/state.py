from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, field_validator


def _require_non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("must be a non-empty string")
    return value


class StateArtifact(BaseModel):
    id: str
    kind: str

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_kind = field_validator("kind")(_require_non_empty)


class NorthStar(BaseModel):
    artifacts: tuple[StateArtifact, ...]


class State(BaseModel):
    northstar: NorthStar
    artifacts: tuple[StateArtifact, ...] = ()


class StateArtifactAdapter(Protocol):
    kind: str

    def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
        ...


class StateArtifactRegistry:
    def __init__(self):
        self._adapters: dict[str, StateArtifactAdapter] = {}

    def register(self, adapter: StateArtifactAdapter) -> None:
        kind = adapter.kind
        if not kind.strip():
            raise ValueError("adapter kind must be a non-empty string")
        if kind in self._adapters:
            raise ValueError(f"adapter kind already registered: {kind}")
        self._adapters[kind] = adapter

    def resolve(self, kind: str) -> StateArtifactAdapter:
        adapter = self._adapters.get(kind)
        if adapter is None:
            raise ValueError(f"unknown artifact kind: {kind}")
        return adapter


class DocumentArtifactAdapter:
    kind = "document"

    def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
        return artifact


class GitRepositoryArtifactAdapter:
    kind = "git_repository"

    def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
        return artifact
