from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field

from baps.core.workspace import load_workspace_settings, resolve_output_path
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
    sandbox: Literal["docker", "none"] = "docker"
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


_DEFAULT_WORKSPACE = ".baps-workspace"
_KNOWN_SPEC_KEYS = frozenset({
    "workspace",
    "project_type",
    "artifact_id",
    "language",
    "northstar_markdown",
    "northstar_path",
    "goal",
    "output",
    "max_iterations",
    "max_sub_gaps",
    "source_path",
    "source_include",
    "sandbox",
    "backend",
    "model",
    "roles",
})


def _require_non_empty(value: str, field_name: str) -> str:
    if value.strip() == "":
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _load_spec(spec_path: Path) -> dict[str, object]:
    if not spec_path.exists():
        raise ValueError(f"spec file not found: {spec_path}")

    loaded = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError("spec file must contain a YAML mapping/object at top level")
    return loaded


def resolve_run_config(args: argparse.Namespace) -> RunConfig:
    from baps.core.debug import _debug_print_read_config
    from baps.core.clients import _VALID_BACKENDS, _parse_spec_roles

    spec_data: dict[str, object] = {}
    if args.spec:
        spec_path = Path(args.spec)
        spec_data = _load_spec(spec_path)
    else:
        spec_path = None

    workspace_raw = (
        args.workspace
        if args.workspace is not None
        else spec_data.get("workspace", _DEFAULT_WORKSPACE)
    )

    workspace_settings: dict[str, object] = {}
    if getattr(args, "command", None) == "start":
        workspace_settings = load_workspace_settings(Path(str(workspace_raw)))

    def _resolve(cli_val: object, spec_key: str, default: object = None) -> object:
        if cli_val is not None:
            return cli_val
        if spec_key in spec_data:
            return spec_data[spec_key]
        if spec_key in workspace_settings:
            return workspace_settings[spec_key]
        return default

    project_type_raw = _resolve(args.project_type, "project_type")
    artifact_id_raw = _resolve(args.artifact_id, "artifact_id")
    if "required_sections" in spec_data:
        raise ValueError(
            "required_sections is no longer supported; declare required structure in northstar_markdown"
        )
    if spec_data:
        unknown_keys = sorted(set(spec_data.keys()) - _KNOWN_SPEC_KEYS - {"required_sections"})
        if unknown_keys:
            raise ValueError(f"spec file contains unknown keys: {unknown_keys}")
    northstar_markdown_raw = _resolve(None, "northstar_markdown")
    northstar_path_raw = spec_data.get("northstar_path")
    if northstar_markdown_raw is None and northstar_path_raw is not None:
        northstar_path = Path(str(northstar_path_raw))
        if not northstar_path.is_absolute():
            northstar_path = Path.cwd() / northstar_path
        if not northstar_path.exists():
            raise ValueError(f"northstar_path file not found: {northstar_path}")
        northstar_markdown_raw = northstar_path.read_text(encoding="utf-8")
    goal_raw = _resolve(args.goal, "goal")
    output_raw = _resolve(args.output, "output")
    max_iterations_raw = (
        args.max_iterations
        if args.max_iterations is not None
        else spec_data.get("max_iterations", 2)
    )

    workspace_str = _require_non_empty(str(workspace_raw), "workspace")
    if project_type_raw is None:
        raise ValueError("project_type must be non-empty")
    project_type = _require_non_empty(str(project_type_raw), "project_type")
    if project_type in {"document", "coding"} and artifact_id_raw is None:
        raise ValueError("artifact_id must be non-empty")
    artifact_id = (
        _require_non_empty(str(artifact_id_raw), "artifact_id")
        if artifact_id_raw is not None
        else ""
    )
    if goal_raw is None:
        raise ValueError("goal is required: provide --goal, or set 'goal' in the spec/workspace config")
    goal = _require_non_empty(str(goal_raw), "goal")
    northstar_markdown = _require_non_empty(
        str(northstar_markdown_raw) if northstar_markdown_raw is not None else goal,
        "northstar_markdown",
    )
    workspace = Path(workspace_str)

    if output_raw is None:
        raise ValueError("output is required: provide --output, or set 'output' in the spec/workspace config")
    output_str = _require_non_empty(str(output_raw), "output")
    output_path = resolve_output_path(workspace, output_str)

    try:
        max_iterations = int(max_iterations_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_iterations must be an integer >= 1") from exc

    if max_iterations < 1:
        raise ValueError("max_iterations must be >= 1")

    source_path_raw = _resolve(None, "source_path")
    source_path = str(source_path_raw) if source_path_raw is not None else None
    source_include_raw = spec_data.get("source_include")
    source_include = list(source_include_raw) if isinstance(source_include_raw, list) else None

    language_raw = _resolve(getattr(args, "language", None), "language")
    language = str(language_raw) if language_raw is not None else ""

    sandbox_raw = _resolve(getattr(args, "sandbox", None), "sandbox", "docker")
    sandbox_value = str(sandbox_raw)
    if sandbox_value not in ("docker", "none"):
        raise ValueError(f"sandbox must be 'docker' or 'none', got: {sandbox_value!r}")
    sandbox = cast(Literal["docker", "none"], sandbox_value)

    spec_backend_raw = spec_data.get("backend")
    spec_backend: Backend | None = None
    if spec_backend_raw is not None:
        spec_backend_value = str(spec_backend_raw).strip().lower()
        if spec_backend_value not in _VALID_BACKENDS:
            raise ValueError(
                f"spec 'backend' must be one of {sorted(_VALID_BACKENDS)}, got {spec_backend_value!r}"
            )
        spec_backend = Backend(spec_backend_value)

    spec_model_raw = spec_data.get("model")
    spec_model: str | None = str(spec_model_raw).strip() if spec_model_raw is not None else None

    roles_raw = spec_data.get("roles")
    spec_roles = _parse_spec_roles(roles_raw) if roles_raw is not None else {}

    max_sub_gaps_raw = _resolve(None, "max_sub_gaps", 5)
    try:
        max_sub_gaps = int(max_sub_gaps_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_sub_gaps must be an integer >= 1") from exc
    if max_sub_gaps < 1:
        raise ValueError("max_sub_gaps must be >= 1")

    run_config = RunConfig(
        workspace=workspace,
        project_type=project_type,
        artifact_id=artifact_id,
        language=language,
        northstar_markdown=northstar_markdown,
        goal=goal,
        output_path=output_path,
        max_iterations=max_iterations,
        max_sub_gaps=max_sub_gaps,
        spec_path=spec_path,
        source_path=source_path,
        source_include=source_include,
        sandbox=sandbox,
        spec_backend=spec_backend,
        spec_model=spec_model,
        spec_roles=spec_roles,
    )
    _debug_print_read_config(args=args, spec_data=spec_data, config=run_config)
    return run_config


def resolve_reset_targets(args: argparse.Namespace) -> tuple[Path, Path | None]:
    spec_data: dict[str, object] = {}
    if args.spec:
        spec_data = _load_spec(Path(args.spec))

    workspace_raw = (
        args.workspace
        if args.workspace is not None
        else spec_data.get("workspace", _DEFAULT_WORKSPACE)
    )
    workspace = Path(str(workspace_raw))
    workspace_settings = load_workspace_settings(workspace)

    output_raw = (
        args.output
        if args.output is not None
        else spec_data.get("output") or workspace_settings.get("output")
    )
    if not output_raw or not str(output_raw).strip():
        return workspace, None
    return workspace, resolve_output_path(workspace, str(output_raw))
