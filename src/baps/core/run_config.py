from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from baps.models.models import Backend


class RoleConfig(BaseModel):
    """Typed role-specific model routing config."""

    model_config = ConfigDict(frozen=True)

    backend: Backend | None = None
    model: str | None = None
    fallback: RoleConfig | None = None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in type(self).model_fields


class RunConfig(BaseModel):
    """Typed configuration for a single baps run.

    All fields correspond exactly to the keys that resolve_run_config previously
    stored in a plain dict. The __getitem__ / get / __contains__ methods allow
    adapter implementations and any legacy call-sites that still use dict-style
    access to work without modification.
    """

    model_config = ConfigDict(frozen=True)

    workspace: Path
    project_type: str
    artifact_id: str
    language: str = ""
    northstar_markdown: str
    goal: str
    output_path: Path
    max_iterations: int
    max_sub_gaps: int = 5
    max_depth: int = 3
    spec_path: Path | None = None
    source_path: str | None = None
    source_include: list[str] | None = None
    sandbox: str = "docker"
    spec_backend: Backend | None = None
    spec_model: str | None = None
    spec_roles: dict[str, RoleConfig] = Field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in type(self).model_fields
