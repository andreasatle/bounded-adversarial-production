from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from baps.models.models import Backend


class RoleConfig(BaseModel):
    """Typed role-specific model routing config."""

    model_config = ConfigDict(frozen=True)

    backend: Backend | None = None
    model: str | None = None
    fallback: RoleConfig | None = None

    def __getitem__(self, key: str) -> object:
        return getattr(self, key)

    def get(self, key: str, default: object | None = None) -> object | None:
        return getattr(self, key, default)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in type(self).model_fields


class RunConfig(BaseModel):
    """Typed configuration for a single baps run.

    All fields correspond to known runtime config inputs used by the main
    execution path.
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

    def __getitem__(self, key: str) -> object:
        return getattr(self, key)

    def get(self, key: str, default: object | None = None) -> object | None:
        return getattr(self, key, default)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in type(self).model_fields

    def to_adapter_config(self) -> dict[str, object]:
        return {
            "workspace": str(self.workspace),
            "project_type": self.project_type,
            "artifact_id": self.artifact_id,
            "language": self.language,
            "northstar_markdown": self.northstar_markdown,
            "goal": self.goal,
            "output_path": str(self.output_path),
            "max_iterations": self.max_iterations,
            "max_sub_gaps": self.max_sub_gaps,
            "max_depth": self.max_depth,
            "source_path": self.source_path,
            "source_include": self.source_include,
            "sandbox": self.sandbox,
        }
