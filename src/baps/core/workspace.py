from __future__ import annotations

import json
from pathlib import Path

if False:  # pragma: no cover
    from baps.core.run_config import RunConfig

_WORKSPACE_CONFIG_FILE = "baps-config.json"
_WORKSPACE_CONFIG_FIELDS = ("project_type", "artifact_id", "northstar_markdown", "goal", "output")


def resolve_output_path(workspace: Path, output_value: str) -> Path:
    output_candidate = Path(output_value)
    if output_candidate.is_absolute():
        return output_candidate.resolve()
    return (workspace / output_candidate).resolve()


def state_path_for_workspace(workspace: Path) -> Path:
    return workspace / "state" / "state.json"


def workspace_config_path(workspace: Path) -> Path:
    return workspace / _WORKSPACE_CONFIG_FILE


def save_workspace_settings(run_config: "RunConfig", workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    output_path = run_config.output_path
    try:
        output_str = str(output_path.relative_to(workspace))
    except ValueError:
        output_str = str(output_path)
    saved = {
        "project_type": run_config.project_type,
        "artifact_id": run_config.artifact_id,
        "northstar_markdown": run_config.northstar_markdown,
        "goal": run_config.goal,
        "output": output_str,
    }
    workspace_config_path(workspace).write_text(
        json.dumps(saved, indent=2, sort_keys=True), encoding="utf-8"
    )


def load_workspace_settings(workspace: Path) -> dict[str, object]:
    path = workspace_config_path(workspace)
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {k: v for k, v in loaded.items() if k in _WORKSPACE_CONFIG_FIELDS}


def wipe_workspace_state(workspace: Path, output_path: Path | None = None) -> None:
    state_path = state_path_for_workspace(workspace)
    if state_path.exists():
        state_path.unlink()
    config_path = workspace_config_path(workspace)
    if config_path.exists():
        config_path.unlink()
    if output_path is not None and output_path.exists():
        if output_path.is_dir():
            import shutil

            shutil.rmtree(output_path)
        else:
            output_path.unlink()


def write_run_result(workspace: Path, result_data: dict[str, object]) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "run-result.json").write_text(
        json.dumps(result_data, indent=2), encoding="utf-8"
    )
