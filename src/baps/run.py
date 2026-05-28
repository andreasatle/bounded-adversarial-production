from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import uuid
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
    _make_fallback_chain_fn,
    _parse_spec_roles,
    _resolve_backend_model,
)
from baps.debug import (
    _debug_print_blue_input,
    _debug_print_create_game_input,
    _debug_print_create_game_output,
    _debug_print_create_game_prompt,
    _debug_print_create_game_raw_model_output,
    _debug_print_create_game_red_input,
    _debug_print_create_game_red_output,
    _debug_print_create_game_validation_failure,
    _debug_print_create_game_validation_input,
    _debug_print_create_state,
    _debug_print_northstar_update_proposal,
    _debug_print_play_game_attempt,
    _debug_print_play_game_input,
    _debug_print_play_game_output,
    _debug_print_read_config,
    _debug_print_red_input,
    _debug_print_red_output,
    _debug_print_referee_input,
    _debug_print_referee_output,
    _debug_print_verification_result,
    _format_debug_yaml_like,
    _debug_log,
    _debug_print_attempt_rejected,
    _debug_print_blue_failed_tool_call,
    _debug_print_blue_output,
)
from baps.game import (
    _DEFAULT_MAX_PLAY_GAME_ATTEMPTS,
    _BLACKBOARD_DIR,
    _GAMES_FILE,
    _NORTHSTAR_PROPOSALS_FILE,
    _VERIFICATION_SUMMARY_CAP,
    _CREATE_GAME_SCHEMA,
    _RED_FINDING_SCHEMA,
    _REFEREE_DECISION_SCHEMA,
    _append_create_game_to_blackboard,
    _append_game_to_blackboard,
    _append_integration_to_blackboard,
    _append_northstar_proposal_to_blackboard,
    _client_model_name,
    _commit_export_with_adapter,
    _derive_state_update_from_delta,
    _ensure_target_artifact_exists,
    _generate_create_game_with_json_retry,
    _sanitize_feedback_dict,
    _sanitize_game_spec_dict,
    _summarize_verification_result,
    _validate_game_spec,
    _verify_candidate_with_adapter,
    _verify_export_with_adapter,
    create_game,
    play_game,
)
from baps.parsers import (
    NoNewGameError,
    NorthStarUpdateNeededError,
    _CREATE_GAME_ALL_KEYS,
    _DECOMPOSE_EMPTY_SUBGAPS_CORRECTION_PROMPT,
    _UNRECOGNIZABLE_SHAPE_CORRECTION_PROMPT,
    _RED_ALL_KEYS,
    _RED_REQUIRED_KEYS,
    _REFEREE_ALL_KEYS,
    _REFEREE_REQUIRED_KEYS,
    _normalize_game_spec_with_adapter,
    _parse_create_game_output,
    _parse_red_finding_json,
    _parse_referee_decision_json,
    _parse_role_output,
)
from baps.prompts import (
    _get_research_tools,
    _render_create_game_prompt,
    _render_create_game_red_prompt,
    _render_red_prompt,
    _render_red_prompt_supplement_with_adapter,
    _render_referee_prompt,
    _render_referee_prompt_supplement_with_adapter,
    _render_research_prompt,
    _render_tool_session_block,
    _render_verification_block,
)
from baps.models import Backend, ModelClient, Role, ToolCallRecord
from baps.tools import ToolExecutor, build_default_tool_executor
from baps.model_output import BlackboardEvent, parse_model_output
from baps.northstar_projection import ProjectionType, STATE_VIEW_START, STATE_VIEW_END, StateView
from baps.project_adapter import (
    ProjectTypeAdapter,
    VerificationResult,
    _config_artifact_id,
    _config_northstar_markdown,
    _verification_result_to_dict,
    sanitize_model_string,
    build_default_project_type_adapters,
    resolve_adapter_for_allowed_delta_type,
    resolve_project_type_adapter,
)
from baps.state import (
    DecomposeSpec,
    DeltaState,
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

logger = logging.getLogger(__name__)

_DEFAULT_WORKSPACE = ".baps-workspace"
_DEFAULT_MAX_DEPTH = 3
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


class _RunContext:
    """Mutable execution context threaded through recursive gap solving."""

    def __init__(self, initial_state: State, max_iterations: int) -> None:
        self.current_state = initial_state
        self.iterations_remaining = max_iterations
        self.iterations_completed = 0
        self.update_applied = False
        self.state_changed = False
        self.output_exported = False
        self.output_changed = False
        self.northstar_proposal_written = False
        self.verification_result: VerificationResult | None = None
        self.stop_reason: StopReason | None = None
        # Set when no_new_game is overridden because verification is failing.
        # A second consecutive override (no leaf game ran in between) escalates.
        self.no_new_game_verification_override: bool = False


def _solve_gap(
    context_chain: tuple[str, ...],
    ctx: _RunContext,
    config: dict[str, Any],
    adapter: ProjectTypeAdapter,
    state_service: StateService,
    output_path: Path,
    artifact_id: str,
    max_depth: int,
    depth: int,
) -> None:
    """Recursively plan and execute within a gap scope. Mutates ctx."""
    if ctx.stop_reason is not None:
        return

    try:
        result = create_game(
            config,
            ctx.current_state,
            adapter=adapter,
            verification_result=ctx.verification_result,
            context_chain=context_chain,
            depth=depth,
            create_game_red_client=_build_client_for_role(SpecRole.CREATE_GAME_RED, config),
        )
    except NoNewGameError:
        if depth == 0:
            vr = ctx.verification_result
            if vr is not None and not vr.passed:
                # Failing tests are evidence of a gap.  Refuse to stop.
                if not ctx.no_new_game_verification_override:
                    logger.warning(
                        "[solve_gap] create_game returned no_new_game but last "
                        "verification failed (exit_code=%d); not stopping — "
                        "retrying with verification failure as context.",
                        vr.exit_code,
                    )
                    ctx.no_new_game_verification_override = True
                    return  # outer loop retries; verification context already in ctx
                # Second consecutive no_new_game with failing verification — model
                # cannot identify the gap.  Escalate so the human is alerted.
                logger.warning(
                    "[solve_gap] create_game returned no_new_game twice with "
                    "failing verification; escalating to northstar_update_proposed."
                )
                _append_northstar_proposal_to_blackboard(
                    workspace=config["workspace"],
                    rationale=(
                        "create_game returned no_new_game despite failing verification "
                        "(tests still failing). The model could not identify a gap to "
                        "close the failing tests. NorthStar or the success condition "
                        "may need revision."
                    ),
                    proposed_northstar=_config_northstar_markdown(config),
                )
                ctx.northstar_proposal_written = True
                ctx.stop_reason = StopReason.NORTHSTAR_UPDATE_PROPOSED
                return
            ctx.stop_reason = StopReason.CREATE_GAME_NO_NEW_GAME
        return
    except NorthStarUpdateNeededError as exc:
        _debug_print_northstar_update_proposal(exc.rationale, exc.proposed_northstar)
        _append_northstar_proposal_to_blackboard(
            workspace=config["workspace"],
            rationale=exc.rationale,
            proposed_northstar=exc.proposed_northstar,
        )
        ctx.northstar_proposal_written = True
        ctx.stop_reason = StopReason.NORTHSTAR_UPDATE_PROPOSED
        return

    if isinstance(result, DecomposeSpec):
        if depth >= max_depth:
            logger.info("[solve_gap] max_depth=%d reached, cannot decompose further; stopping.", max_depth)
            ctx.stop_reason = StopReason.MAX_DEPTH_REACHED
            return
        logger.info(
            "[solve_gap] depth=%d decomposing into %d sub-gaps: %s",
            depth, len(result.sub_gaps), result.rationale,
        )
        for sub_gap in result.sub_gaps:
            _solve_gap(
                context_chain + (sub_gap.description,),
                ctx,
                config,
                adapter,
                state_service,
                output_path,
                artifact_id,
                max_depth,
                depth + 1,
            )
            if ctx.stop_reason == StopReason.PLAY_GAME_NO_DELTA:
                ctx.stop_reason = None  # leaf found nothing; continue sibling sub-gaps
            elif ctx.stop_reason is not None:
                return
        return

    # Leaf: GameSpec — inject full context chain and execute
    game_spec = result.model_copy(update={"context_chain": context_chain})
    logger.info("[solve_gap] depth=%d playing leaf game: %s", depth, game_spec.objective)

    sandbox_mode = config.get("sandbox", "docker")
    delta_state = play_game(
        ctx.current_state,
        game_spec,
        adapter=adapter,
        verification_result=ctx.verification_result,
        executor=build_default_tool_executor(),
        sandbox_mode=sandbox_mode,
        config=config,
        depth=depth,
    )
    if delta_state is None:
        ctx.stop_reason = StopReason.PLAY_GAME_NO_DELTA
        return

    before_state = state_service.load_state()
    updated_state = state_service.apply_delta(delta_state)
    changed = state_service.states_differ(before_state, updated_state)

    _integration_workspace = config.get("workspace")
    if _integration_workspace is not None:
        _append_integration_to_blackboard(
            workspace=_integration_workspace,
            depth=depth,
            proposal_id=str(uuid.uuid4()),
            proposal_summary=game_spec.objective,
            state_changed=changed,
            delta_type=getattr(delta_state, "operation", type(delta_state).__name__),
        )

    ctx.output_changed = adapter.export_state(updated_state, output_path, artifact_id)
    ctx.output_exported = ctx.output_exported or ctx.output_changed
    ctx.verification_result = _verify_export_with_adapter(
        adapter, output_path, updated_state, artifact_id, sandbox_mode=sandbox_mode
    )
    _debug_print_verification_result(ctx.verification_result)
    if ctx.output_changed:
        _commit_export_with_adapter(adapter, output_path, game_spec)

    ctx.update_applied = True
    ctx.iterations_completed += 1
    ctx.iterations_remaining -= 1
    ctx.no_new_game_verification_override = False
    ctx.current_state = updated_state

    if changed:
        ctx.state_changed = True
    else:
        ctx.stop_reason = StopReason.NO_STATE_CHANGE


def _run_project_iterations(
    config: dict[str, Any],
    adapter: ProjectTypeAdapter,
    state_service: StateService,
    initial_state: State,
) -> dict[str, object]:
    output_path = config["output_path"]
    max_iterations = config["max_iterations"]
    artifact_id = _config_artifact_id(config)
    max_depth = int(config.get("max_depth", _DEFAULT_MAX_DEPTH))

    if config.get("project_type") == "coding" and config.get("sandbox") == "none":
        from baps.sandbox import SANDBOX_NONE_WARNING
        logger.warning("%s", SANDBOX_NONE_WARNING)

    ctx = _RunContext(initial_state=initial_state, max_iterations=max_iterations)

    while ctx.iterations_remaining > 0 and ctx.stop_reason is None:
        _solve_gap(
            context_chain=(),
            ctx=ctx,
            config=config,
            adapter=adapter,
            state_service=state_service,
            output_path=output_path,
            artifact_id=artifact_id,
            max_depth=max_depth,
            depth=0,
        )
        # A gap was identified but the system could not close it.  Escalate to
        # a NorthStar proposal so the human is alerted through the normal
        # approval channel rather than receiving a silent stop.
        if ctx.stop_reason in (StopReason.PLAY_GAME_NO_DELTA, StopReason.NO_STATE_CHANGE):
            if ctx.stop_reason == StopReason.PLAY_GAME_NO_DELTA:
                rationale = (
                    "Gap was identified but play_game produced no accepted delta — "
                    "Blue was unable to close the gap. "
                    "NorthStar may need clarification or the gap may be unreachable "
                    "with the current approach."
                )
            else:
                rationale = (
                    "Gap was identified and a delta was produced and accepted, but "
                    "applying it produced no state change — the gap may already be "
                    "satisfied or the delta was a no-op. "
                    "NorthStar may need clarification or the success condition may "
                    "need revision."
                )
            _append_northstar_proposal_to_blackboard(
                workspace=config["workspace"],
                rationale=rationale,
                proposed_northstar=_config_northstar_markdown(config),
            )
            ctx.northstar_proposal_written = True
            ctx.stop_reason = StopReason.NORTHSTAR_UPDATE_PROPOSED

    if ctx.stop_reason is None:
        ctx.stop_reason = StopReason.ITERATION_LIMIT_REACHED

    return {
        "update_applied": ctx.update_applied,
        "state_changed": ctx.state_changed,
        "output_exported": ctx.output_exported,
        "output_changed": ctx.output_changed,
        "northstar_proposal_written": ctx.northstar_proposal_written,
        "verification_result": ctx.verification_result,
        "iterations_completed": ctx.iterations_completed,
        "stop_reason": ctx.stop_reason,
    }


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
        print(f"command=reset")
        print(f"wiped=True")
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
