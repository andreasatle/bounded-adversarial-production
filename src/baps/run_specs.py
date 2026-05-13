from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator


def _require_non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("must be a non-empty string")
    return value


class RunSpecModel(BaseModel):
    provider: str = "ollama"
    name: str = ""
    base_url: str = ""

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, value: str) -> str:
        return _require_non_empty(value)


class RunSpecGame(BaseModel):
    type: str = "documentation-refinement"
    subject: str
    goal: str
    target_kind: str
    target_ref: str = ""
    max_rounds: int = 1
    red_material: bool = True

    @field_validator("type", "subject", "goal", "target_kind")
    @classmethod
    def _validate_required_strings(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator("max_rounds")
    @classmethod
    def _validate_max_rounds(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_rounds must be >= 1")
        return value


class RunSpecState(BaseModel):
    manifest: str
    sources: list[str] = Field(default_factory=list)

    @field_validator("manifest")
    @classmethod
    def _validate_manifest(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator("sources")
    @classmethod
    def _validate_sources(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("state.sources must be non-empty")
        for source in value:
            _require_non_empty(source)
        return value


class RunSpec(BaseModel):
    name: str = ""
    description: str = ""
    model: RunSpecModel = Field(default_factory=RunSpecModel)
    game: RunSpecGame
    context_files: list[str] = Field(default_factory=list)
    state: RunSpecState | None = None
    game_definition_file: str = ""


def load_run_spec(path: Path) -> RunSpec:
    if not path.exists():
        raise FileNotFoundError(f"run spec file not found: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in run spec file: {path}") from exc
    try:
        return RunSpec.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"invalid RunSpec schema in file: {path}") from exc
