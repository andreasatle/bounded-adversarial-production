from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any

import yaml

from baps.clients import (
    SpecRole,
    _VALID_BACKENDS,
    _build_client,
    _build_client_for_role,
    _build_fallback_chain_for_role,
    _build_fallback_client_for_role,
    _build_model_client,
    _build_planner_model_client,
    _build_role_client,
    _parse_spec_roles,
    _resolve_backend_model,
)
from baps.debug import (
    _debug_print_blue_input,
    _debug_print_create_state,
    _debug_print_read_config,
)
from baps.game import (
    _VERIFICATION_SUMMARY_CAP,
    _commit_export_with_adapter,
    _derive_state_update_from_delta,
    create_game,
    play_game,
)
from baps.parsers import (
    NoNewGameError,
    NorthStarUpdateNeededError,
    _parse_create_game_output,
    _parse_red_finding_json,
    _parse_referee_decision_json,
)
from baps.prompts import (
    _render_create_game_prompt,
    _render_red_prompt,
    _render_referee_prompt,
)
from baps.northstar_projection import ProjectionType, StateView
from baps.project_adapter import (
    ProjectTypeAdapter,
    VerificationResult,
    build_default_project_type_adapters,
    resolve_adapter_for_allowed_delta_type,
    resolve_project_type_adapter,
)
from baps.state import (
    DecomposeSpec,
    GameSpec,
    PlayGameRuntime,
    RedFinding,
    RefereeDecision,
    State,
    StateUpdateProposal,
    StopReason,
    SubGapSpec,
    apply_referee_decision_to_runtime,
    build_default_state_artifact_registry,
)
from baps.state_service import StateService
from baps.state_store import JsonStateStore
from baps.orchestration import _run_project_iterations

logger = logging.getLogger(__name__)

_DEFAULT_WORKSPACE = ".baps-workspace"
_WORKSPACE_CONFIG_FILE = "baps-config.json"




def _require_non_empty(value: str, field_name: str) -> str:
    if value.strip() == "":
        raise ValueError(f"{field_name} must be non-empty")
    return value



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


def _load_spec(spec_path: Path) -> dict[str, Any]:
    if not spec_path.exists():
        raise ValueError(f"spec file not found: {spec_path}")

    loaded = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError("spec file must contain a YAML mapping/object at top level")
    return loaded


def _resolve_output_path(workspace: Path, output_value: str) -> Path:
    output_candidate = Path(output_value)
    if output_candidate.is_absolute():
        return output_candidate.resolve()
    return (workspace / output_candidate).resolve()


def resolve_run_config(args: argparse.Namespace) -> dict[str, Any]:
    spec_data: dict[str, Any] = {}
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

    workspace_config: dict[str, Any] = {}
    if getattr(args, "command", None) == "start":
        workspace_config = _load_workspace_config(Path(str(workspace_raw)))

    def _resolve(cli_val: object, spec_key: str, default: object = None) -> object:
        if cli_val is not None:
            return cli_val
        if spec_key in spec_data:
            return spec_data[spec_key]
        if spec_key in workspace_config:
            return workspace_config[spec_key]
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
    output_path = _resolve_output_path(workspace, output_str)

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
    sandbox = str(sandbox_raw)
    if sandbox not in ("docker", "none"):
        raise ValueError(f"sandbox must be 'docker' or 'none', got: {sandbox!r}")

    spec_backend_raw = spec_data.get("backend")
    spec_backend: str | None = None
    if spec_backend_raw is not None:
        spec_backend = str(spec_backend_raw).strip().lower()
        if spec_backend not in _VALID_BACKENDS:
            raise ValueError(
                f"spec 'backend' must be one of {sorted(_VALID_BACKENDS)}, got {spec_backend!r}"
            )

    spec_model_raw = spec_data.get("model")
    spec_model: str | None = str(spec_model_raw).strip() if spec_model_raw is not None else None

    roles_raw = spec_data.get("roles")
    spec_roles: dict[str, dict[str, str]] = (
        _parse_spec_roles(roles_raw) if roles_raw is not None else {}
    )

    max_sub_gaps_raw = _resolve(None, "max_sub_gaps", 5)
    try:
        max_sub_gaps = int(max_sub_gaps_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_sub_gaps must be an integer >= 1") from exc
    if max_sub_gaps < 1:
        raise ValueError("max_sub_gaps must be >= 1")

    config = {
        "workspace": workspace,
        "project_type": project_type,
        "artifact_id": artifact_id,
        "language": language,
        "northstar_markdown": northstar_markdown,
        "goal": goal,
        "output_path": output_path,
        "max_iterations": max_iterations,
        "max_sub_gaps": max_sub_gaps,
        "spec_path": spec_path,
        "source_path": source_path,
        "source_include": source_include,
        "sandbox": sandbox,
        "spec_backend": spec_backend,
        "spec_model": spec_model,
        "spec_roles": spec_roles,
    }
    _debug_print_read_config(args=args, spec_data=spec_data, config=config)
    return config


def create_state(config: dict[str, Any]) -> State:
    adapter = _resolve_project_type_adapter(config["project_type"])
    state = adapter.create_initial_state(config)
    _debug_print_create_state(config=config, state=state)
    return state


def _build_project_type_adapters() -> dict[str, ProjectTypeAdapter]:
    return build_default_project_type_adapters()


def _resolve_project_type_adapter(project_type: str) -> ProjectTypeAdapter:
    return resolve_project_type_adapter(project_type)


def _resolve_adapter_for_allowed_delta_type(allowed_delta_type: str) -> ProjectTypeAdapter:
    return resolve_adapter_for_allowed_delta_type(allowed_delta_type)


def _state_path_for_workspace(workspace: Path) -> Path:
    return workspace / "state" / "state.json"


def _workspace_config_path(workspace: Path) -> Path:
    return workspace / _WORKSPACE_CONFIG_FILE


_WORKSPACE_CONFIG_FIELDS = ("project_type", "artifact_id", "northstar_markdown", "goal", "output")


def _save_workspace_config(config: dict[str, Any], workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    output_path: Path = config["output_path"]
    try:
        output_str = str(output_path.relative_to(workspace))
    except ValueError:
        output_str = str(output_path)
    saved = {
        "project_type": config["project_type"],
        "artifact_id": config["artifact_id"],
        "northstar_markdown": config["northstar_markdown"],
        "goal": config["goal"],
        "output": output_str,
    }
    _workspace_config_path(workspace).write_text(
        json.dumps(saved, indent=2, sort_keys=True), encoding="utf-8"
    )


def _load_workspace_config(workspace: Path) -> dict[str, Any]:
    path = _workspace_config_path(workspace)
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {k: v for k, v in loaded.items() if k in _WORKSPACE_CONFIG_FIELDS}


def _wipe_state(workspace: Path, output_path: Path | None = None) -> None:
    """Delete persisted state, workspace config, and optionally the output file."""
    state_path = _state_path_for_workspace(workspace)
    if state_path.exists():
        state_path.unlink()
    config_path = _workspace_config_path(workspace)
    if config_path.exists():
        config_path.unlink()
    if output_path is not None and output_path.exists():
        if output_path.is_dir():
            import shutil
            shutil.rmtree(output_path)
        else:
            output_path.unlink()


def _resolve_reset_config(args: argparse.Namespace) -> tuple[Path, Path | None]:
    """Resolve workspace and optional output path for the reset command.

    reset only needs to know where state lives and what output file to wipe.
    All other fields (goal, project_type, etc.) are irrelevant.
    """
    spec_data: dict[str, Any] = {}
    if args.spec:
        spec_data = _load_spec(Path(args.spec))

    workspace_raw = (
        args.workspace
        if args.workspace is not None
        else spec_data.get("workspace", _DEFAULT_WORKSPACE)
    )
    workspace = Path(str(workspace_raw))
    workspace_config = _load_workspace_config(workspace)

    output_raw = (
        args.output
        if args.output is not None
        else spec_data.get("output") or workspace_config.get("output")
    )
    if not output_raw or not str(output_raw).strip():
        return workspace, None
    return workspace, _resolve_output_path(workspace, str(output_raw))


def _initialize_project(
    config: dict[str, Any],
) -> tuple[StateService, State]:
    workspace = config["workspace"]
    initial_state = create_state(config)
    state_store = JsonStateStore(_state_path_for_workspace(workspace))
    state_store.save(initial_state)
    _save_workspace_config(config, workspace)
    service = StateService(
        store=state_store,
        registry=build_default_state_artifact_registry(),
    )
    return service, initial_state


def _load_project_service(workspace: Path) -> StateService:
    return StateService(
        store=JsonStateStore(_state_path_for_workspace(workspace)),
        registry=build_default_state_artifact_registry(),
    )


def _active_model_info(config: dict[str, Any] | None = None) -> dict[str, str]:
    try:
        cfg = config or {}
        backend, model = _resolve_backend_model(SpecRole.BLUE, cfg)
        return {"backend": backend, "model": model}
    except ValueError:
        return {"backend": "unknown", "model": "unknown"}


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    _log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(level=_log_level, format="%(asctime)s %(levelname)-5s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    parser = argparse.ArgumentParser(
        description="baps — bounded adversarial production system.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run baps-run reset --spec examples/coding-project.yaml\n"
            "  uv run baps-run start --spec examples/coding-project.yaml\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def _add_common_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--spec", default=None, help="YAML spec path.")
        p.add_argument(
            "--workspace", default=None,
            help="Workspace directory for runtime outputs.",
        )
        p.add_argument(
            "--project-type", default=None,
            help="Project type (currently supported: document, coding, audit).",
        )
        p.add_argument(
            "--artifact-id", default=None,
            help="Artifact id for project state.",
        )
        p.add_argument(
            "--goal", default=None,
            help="Runtime goal text. Required if not set in spec or workspace config.",
        )
        p.add_argument(
            "--output", default=None,
            help="Output path (relative paths are resolved under workspace).",
        )
        p.add_argument(
            "--max-iterations", type=int, default=None,
            help="Maximum loop iterations (must be >= 1).",
        )
        p.add_argument(
            "--sandbox", default=None, choices=("docker", "none"),
            help="Sandbox mode for code execution: 'docker' (default) or 'none' (unsafe, prints warning).",
        )
        p.add_argument(
            "--language", default=None,
            help="Language plugin for coding projects (e.g. python, zig). Required for coding project type.",
        )

    start_parser = subparsers.add_parser(
        "start",
        help=(
            "Initialize if needed, then run the game loop. "
            "Continues from existing state when present; "
            "initializes from scratch when the workspace is empty."
        ),
    )
    _add_common_args(start_parser)

    reset_parser = subparsers.add_parser(
        "reset",
        help=(
            "Wipe workspace state and output file, then exit. "
            "No model calls are made. "
            "Run 'start' afterwards to begin from a clean slate."
        ),
    )
    reset_parser.add_argument("--spec", default=None, help="YAML spec path.")
    reset_parser.add_argument("--workspace", default=None, help="Workspace directory.")
    reset_parser.add_argument(
        "--output", default=None,
        help="Output file to wipe (relative paths resolved under workspace).",
    )

    args = parser.parse_args()

    if args.command == "reset":
        try:
            workspace, output_path = _resolve_reset_config(args)
        except ValueError as exc:
            logger.error("%s", exc)
            raise SystemExit(2) from exc
        _wipe_state(workspace, output_path)
        print(f"workspace={workspace}")
        print("command=reset")
        print("wiped=True")
        return

    try:
        config = resolve_run_config(args)
    except ValueError as exc:
        logger.error("%s", exc)
        raise SystemExit(2) from exc

    command = args.command
    workspace = config["workspace"]
    project_type = config["project_type"]
    goal = config["goal"]
    output_path = config["output_path"]
    max_iterations = config["max_iterations"]
    try:
        adapter = _resolve_project_type_adapter(project_type)
    except ValueError as exc:
        logger.error("%s", exc)
        raise SystemExit(2) from exc
    update_applied = False
    state_changed = False
    output_exported = False
    output_changed = False
    northstar_proposal_written = False
    verification_run = False
    verification_passed = False
    verification_exit_code: int | None = None
    verification_command: str | None = None
    verification_cwd: str | None = None
    iterations_completed = 0
    stop_reason: StopReason = StopReason.NOT_RUN

    try:
        state_path = _state_path_for_workspace(workspace)
        if state_path.exists():
            state_service = _load_project_service(workspace)
            current_state = state_service.load_state()
        else:
            state_service, current_state = _initialize_project(config)

        results = _run_project_iterations(
            config=config,
            adapter=adapter,
            state_service=state_service,
            initial_state=current_state,
        )
        update_applied = bool(results["update_applied"])
        state_changed = bool(results["state_changed"])
        output_exported = bool(results["output_exported"])
        output_changed = bool(results["output_changed"])
        northstar_proposal_written = bool(results["northstar_proposal_written"])
        verification_result = results["verification_result"]
        verification_run = verification_result is not None
        if verification_result is not None:
            verification_passed = verification_result.passed
            verification_exit_code = verification_result.exit_code
            verification_command = verification_result.command
            verification_cwd = verification_result.cwd
        iterations_completed = int(results["iterations_completed"])
        stop_reason = results["stop_reason"]
    except (ValueError, RuntimeError) as exc:
        logger.error("%s", exc)
        stop_reason = StopReason.ERROR
        model_info = _active_model_info(config)
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "run-result.json").write_text(
            json.dumps({
                "stop_reason": stop_reason,
                "verification_passed": None,
                "verification_exit_code": None,
                "iterations_completed": iterations_completed,
                "backend": model_info["backend"],
                "model": model_info["model"],
                "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
            }, indent=2),
            encoding="utf-8",
        )
        print(f"workspace={workspace}")
        print(f"project_type={project_type}")
        print(f"command={command}")
        print(f"goal={goal}")
        print(f"output_path={output_path}")
        print(f"max_iterations={max_iterations}")
        print(f"update_applied={update_applied}")
        print(f"state_changed={state_changed}")
        print(f"output_exported={output_exported}")
        print(f"output_changed={output_changed}")
        print(f"northstar_proposal_written={northstar_proposal_written}")
        print(f"verification_run={verification_run}")
        print(f"iterations_completed={iterations_completed}")
        print(f"verification_passed={verification_passed}")
        print(f"verification_exit_code={verification_exit_code}")
        print(f"verification_command={verification_command}")
        print(f"verification_cwd={verification_cwd}")
        print(f"stop_reason={stop_reason}")
        raise SystemExit(2) from exc

    print(f"workspace={workspace}")
    print(f"project_type={project_type}")
    print(f"command={command}")
    print(f"goal={goal}")
    print(f"output_path={output_path}")
    print(f"max_iterations={max_iterations}")
    print(f"update_applied={update_applied}")
    print(f"state_changed={state_changed}")
    print(f"output_exported={output_exported}")
    print(f"output_changed={output_changed}")
    print(f"northstar_proposal_written={northstar_proposal_written}")
    print(f"verification_run={verification_run}")
    print(f"iterations_completed={iterations_completed}")
    print(f"verification_passed={verification_passed}")
    print(f"verification_exit_code={verification_exit_code}")
    print(f"verification_command={verification_command}")
    print(f"verification_cwd={verification_cwd}")
    print(f"stop_reason={stop_reason}")

    model_info = _active_model_info(config)
    result_data: dict[str, object] = {
        "stop_reason": stop_reason,
        "verification_passed": verification_passed if verification_run else None,
        "verification_exit_code": verification_exit_code,
        "iterations_completed": iterations_completed,
        "backend": model_info["backend"],
        "model": model_info["model"],
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "run-result.json").write_text(
        json.dumps(result_data, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
