from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from baps.models import AnthropicClient, FallbackClient, ModelClient, OllamaClient, OpenAIClient, Role
from baps.northstar_projection import ProjectionType, StateView
from baps.project_adapter import (
    ProjectTypeAdapter,
    VerificationResult,
    _config_artifact_id,
    _config_northstar_markdown,
    normalize_json_candidate,
    build_default_project_type_adapters,
    resolve_adapter_for_allowed_delta_type,
    resolve_project_type_adapter,
)
from baps.document_adapter import DocumentProjectAdapter
from baps.coding_adapter import CodingProjectAdapter
from baps.state import (
    DecomposeSpec,
    DeltaState,
    GameSpec,
    PlayGameRuntime,
    RedFinding,
    RefereeDecision,
    State,
    StateUpdateProposal,
    SubGapSpec,
    fingerprint_state,
    apply_referee_decision_to_runtime,
    build_default_state_artifact_registry,
)
from baps.state_service import StateService
from baps.state_store import JsonStateStore

_DEFAULT_OLLAMA_MODEL = "llama3.2"
_DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
_DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
_DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
_DEFAULT_OPENAI_MODEL = "gpt-4o"
_DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_WORKSPACE = ".baps-workspace"
_DEFAULT_MAX_PLAY_GAME_ATTEMPTS = 3
_DEFAULT_MAX_DEPTH = 3
_BLACKBOARD_DIR = "blackboard"
_NORTHSTAR_PROPOSALS_FILE = "northstar_proposals.jsonl"
_WORKSPACE_CONFIG_FILE = "baps-config.json"


class NoNewGameError(ValueError):
    """Raised when the model explicitly indicates no new game is available."""


class NorthStarUpdateNeededError(ValueError):
    """Raised when CreateGame signals the trajectory has drifted from NorthStar intent."""

    def __init__(self, rationale: str, proposed_northstar: str) -> None:
        super().__init__(rationale)
        self.rationale = rationale
        self.proposed_northstar = proposed_northstar


def _debug_enabled() -> bool:
    return os.getenv("BAPS_DEBUG") == "1"


def _format_debug_yaml_like(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        if not value:
            return [f"{prefix}{{}}"]
        lines: list[str] = []
        for key in sorted(value.keys()):
            item = value[key]
            if isinstance(item, dict):
                if not item:
                    lines.append(f"{prefix}{key}: {{}}")
                else:
                    lines.append(f"{prefix}{key}:")
                    lines.extend(_format_debug_yaml_like(item, indent + 2))
            elif isinstance(item, (list, tuple)):
                if len(item) == 0:
                    lines.append(f"{prefix}{key}: []")
                else:
                    lines.append(f"{prefix}{key}:")
                    lines.extend(_format_debug_yaml_like(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {item}")
        return lines
    if isinstance(value, (list, tuple)):
        if len(value) == 0:
            return [f"{prefix}[]"]
        lines = []
        for item in value:
            if isinstance(item, dict):
                if not item:
                    lines.append(f"{prefix}- {{}}")
                    continue
                keys = sorted(item.keys())
                first_key = keys[0]
                first_value = item[first_key]
                if isinstance(first_value, (dict, list, tuple)):
                    lines.append(f"{prefix}- {first_key}:")
                    lines.extend(_format_debug_yaml_like(first_value, indent + 4))
                else:
                    lines.append(f"{prefix}- {first_key}: {first_value}")
                for key in keys[1:]:
                    nested = item[key]
                    if isinstance(nested, (dict, list, tuple)):
                        if isinstance(nested, dict) and not nested:
                            lines.append(f"{prefix}  {key}: {{}}")
                        elif isinstance(nested, (list, tuple)) and len(nested) == 0:
                            lines.append(f"{prefix}  {key}: []")
                        else:
                            lines.append(f"{prefix}  {key}:")
                            lines.extend(_format_debug_yaml_like(nested, indent + 4))
                    else:
                        lines.append(f"{prefix}  {key}: {nested}")
            elif isinstance(item, (list, tuple)):
                if len(item) == 0:
                    lines.append(f"{prefix}- []")
                else:
                    lines.append(f"{prefix}-")
                    lines.extend(_format_debug_yaml_like(item, indent + 2))
            else:
                lines.append(f"{prefix}- {item}")
        return lines
    return [f"{prefix}{value}"]


def _debug_print_read_config(args: argparse.Namespace, spec_data: dict[str, Any], config: dict[str, Any]) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] read_config.input:")
    input_payload = {
        "cli_args": {
            "workspace": args.workspace,
            "artifact_id": args.artifact_id,
            "goal": args.goal,
            "output": args.output,
            "max_iterations": args.max_iterations,
            "spec": args.spec,
        },
        "yaml_values": spec_data,
    }
    for line in _format_debug_yaml_like(input_payload, indent=2):
        print(line)
    print()
    print("[DEBUG] read_config.output:")
    output_payload = {
        "workspace": str(config["workspace"]),
        "artifact_id": config["artifact_id"],
        "northstar_markdown": config["northstar_markdown"],
        "goal": config["goal"],
        "output_path": str(config["output_path"]),
        "max_iterations": config["max_iterations"],
    }
    for line in _format_debug_yaml_like(output_payload, indent=2):
        print(line)
    print()


def _debug_print_create_state(config: dict[str, Any], state: State) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] create_state.input:")
    input_payload = {
        "project_type": config["project_type"],
        "artifact_id": _config_artifact_id(config),
        "northstar_markdown": _config_northstar_markdown(config),
        "workspace": str(config["workspace"]),
        "goal": config["goal"],
        "output_path": str(config["output_path"]),
        "max_iterations": config["max_iterations"],
    }
    for line in _format_debug_yaml_like(input_payload, indent=2):
        print(line)
    print()
    print("[DEBUG] create_state.output:")
    output_payload = {
        "state": state.model_dump(mode="json"),
    }
    for line in _format_debug_yaml_like(output_payload, indent=2):
        print(line)
    print()


def _debug_print_create_game_input(state: State) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] create_game.input:")
    input_payload = {
        "state": state.model_dump(mode="json"),
    }
    for line in _format_debug_yaml_like(input_payload, indent=2):
        print(line)
    print()


def _debug_print_create_game_output(game_spec: GameSpec) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] create_game.output:")
    output_payload = {
        "game_spec": game_spec.model_dump(mode="json"),
    }
    for line in _format_debug_yaml_like(output_payload, indent=2):
        print(line)
    print()


def _debug_print_create_game_prompt(prompt: str) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] create_game.prompt:")
    for line in prompt.splitlines() or [""]:
        print(f"  {line}")
    print()


def _debug_print_play_game_input(state: State, game_spec: GameSpec) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] play_game.input:")
    payload = {
        "state": state.model_dump(mode="json"),
        "game_spec": game_spec.model_dump(mode="json"),
    }
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_play_game_output(delta: DeltaState | None) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] play_game.output:")
    payload = {
        "current_best_delta": None if delta is None else delta.model_dump(mode="json"),
    }
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_play_game_attempt(attempt: int) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] play_game.attempt:")
    payload = {"attempt": attempt}
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_blue_failed_tool_call(tool_call: object) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] blue.failed_tool_call:")
    for line in _format_debug_yaml_like({"tool_call": str(tool_call)}, indent=2):
        print(line)
    print()


def _debug_print_attempt_rejected(attempt: int, reason: str) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] play_game.attempt_rejected:")
    payload = {
        "attempt": attempt,
        "reason": reason,
    }
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_blue_input(
    state_view: StateView,
    game_spec: GameSpec,
    attempt_number: int,
    previous_feedback: dict[str, Any] | None,
) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] blue.input:")
    payload = {
        "game_spec": game_spec.model_dump(mode="json"),
        "state_view": state_view.model_dump(mode="json"),
        "attempt_number": attempt_number,
        "previous_feedback": previous_feedback,
    }
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_blue_output(delta: DeltaState) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] blue.output:")
    payload = {"delta_state": delta.model_dump(mode="json")}
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_red_input(
    state_view: StateView,
    game_spec: GameSpec,
    delta_state: DeltaState,
    verification_result: VerificationResult | None = None,
) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] red.input:")
    payload = {
        "game_spec": game_spec.model_dump(mode="json"),
        "state_view": state_view.model_dump(mode="json"),
        "delta_state": delta_state.model_dump(mode="json"),
        "verification_result": (
            None
            if verification_result is None
            else {
                "command": verification_result.command,
                "cwd": verification_result.cwd,
                "exit_code": verification_result.exit_code,
                "stdout": verification_result.stdout,
                "stderr": verification_result.stderr,
                "passed": verification_result.passed,
            }
        ),
    }
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_red_output(red_finding: RedFinding) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] red.output:")
    payload = {"red_finding": red_finding.model_dump(mode="json")}
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_referee_input(
    state_view: StateView,
    game_spec: GameSpec,
    delta_state: DeltaState,
    red_finding: RedFinding,
    verification_result: VerificationResult | None = None,
) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] referee.input:")
    payload = {
        "game_spec": game_spec.model_dump(mode="json"),
        "state_view": state_view.model_dump(mode="json"),
        "delta_state": delta_state.model_dump(mode="json"),
        "red_finding": red_finding.model_dump(mode="json"),
        "verification_result": (
            None
            if verification_result is None
            else {
                "command": verification_result.command,
                "cwd": verification_result.cwd,
                "exit_code": verification_result.exit_code,
                "stdout": verification_result.stdout,
                "stderr": verification_result.stderr,
                "passed": verification_result.passed,
            }
        ),
    }
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_referee_output(referee_decision: RefereeDecision) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] referee.output:")
    payload = {"referee_decision": referee_decision.model_dump(mode="json")}
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_northstar_update_proposal(rationale: str, proposed_northstar: str) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] create_game.northstar_update_proposal:")
    payload = {"rationale": rationale, "proposed_northstar": proposed_northstar}
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_create_game_raw_model_output(raw_text: str) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] create_game.raw_model_output:")
    for line in raw_text.splitlines() or [""]:
        print(f"  {line}")
    print()


def _debug_print_create_game_validation_input(game_spec: GameSpec) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] create_game.validation_input:")
    print(f"objective={game_spec.objective}")
    print(f"success_condition={game_spec.success_condition}")
    print(f"target_artifact_id={game_spec.target_artifact_id}")
    print(f"allowed_delta_type={game_spec.allowed_delta_type}")
    print()


def _debug_print_create_game_validation_failure(message: str) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] create_game.validation_failure:")
    print(f"message={message}")
    print()


def _debug_print_verification_result(result: VerificationResult | None) -> None:
    if not _debug_enabled() or result is None:
        return
    print("[DEBUG] verify_export.result:")
    payload = {
        "verification": {
            "command": result.command,
            "cwd": result.cwd,
            "exit_code": result.exit_code,
            "passed": result.passed,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    }
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _build_client_for_backend(backend: str) -> ModelClient:
    if backend == "anthropic":
        return _build_anthropic_client()
    if backend == "openai":
        return _build_openai_client()
    return OllamaClient(
        model=os.getenv("BAPS_OLLAMA_MODEL", _DEFAULT_OLLAMA_MODEL),
        base_url=os.getenv("BAPS_OLLAMA_BASE_URL", _DEFAULT_OLLAMA_BASE_URL),
    )


def _build_anthropic_client() -> ModelClient:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key.strip():
        raise ValueError("ANTHROPIC_API_KEY must be set when BAPS_BACKEND=anthropic")
    return AnthropicClient(
        model=os.getenv("BAPS_ANTHROPIC_MODEL", _DEFAULT_ANTHROPIC_MODEL),
        api_key=api_key,
        base_url=os.getenv("BAPS_ANTHROPIC_BASE_URL", _DEFAULT_ANTHROPIC_BASE_URL),
    )


def _build_openai_client() -> ModelClient:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key.strip():
        raise ValueError("OPENAI_API_KEY must be set when BAPS_BACKEND=openai")
    return OpenAIClient(
        model=os.getenv("BAPS_OPENAI_MODEL", _DEFAULT_OPENAI_MODEL),
        api_key=api_key,
        base_url=os.getenv("BAPS_OPENAI_BASE_URL", _DEFAULT_OPENAI_BASE_URL),
    )


def _build_model_client() -> ModelClient:
    backends_raw = os.getenv("BAPS_BACKENDS", "").strip()
    if backends_raw:
        backends = [b.strip().lower() for b in backends_raw.split(",") if b.strip()]
        if not backends:
            raise ValueError("BAPS_BACKENDS must contain at least one backend")
        clients = [_build_client_for_backend(b) for b in backends]
        return FallbackClient(clients) if len(clients) > 1 else clients[0]
    return _build_client_for_backend(os.getenv("BAPS_BACKEND", "ollama").lower())


def _build_planner_model_client() -> ModelClient:
    backends_raw = os.getenv("BAPS_BACKENDS", "").strip()
    if backends_raw:
        backends = [b.strip().lower() for b in backends_raw.split(",") if b.strip()]
        if not backends:
            raise ValueError("BAPS_BACKENDS must contain at least one backend")
        clients = [_build_client_for_backend(b) for b in backends]
        return FallbackClient(clients) if len(clients) > 1 else clients[0]
    backend = os.getenv("BAPS_BACKEND", "ollama").lower()
    if backend == "anthropic":
        return _build_anthropic_client()
    if backend == "openai":
        return _build_openai_client()
    return OllamaClient(
        model=(
            os.getenv("BAPS_OLLAMA_PLANNER_MODEL")
            or os.getenv("BAPS_OLLAMA_MODEL", _DEFAULT_OLLAMA_MODEL)
        ),
        base_url=os.getenv("BAPS_OLLAMA_BASE_URL", _DEFAULT_OLLAMA_BASE_URL),
    )


def _build_decompose_client() -> ModelClient:
    """Build a model client for the decompose role.

    Checks BAPS_DECOMPOSE_BACKEND / BAPS_DECOMPOSE_MODEL first.
    Falls back to the create_game client when no decompose-specific vars are set,
    so the decompose role is a transparent no-op by default.
    """
    role_backend = os.getenv("BAPS_DECOMPOSE_BACKEND", "").strip().lower()
    role_model = os.getenv("BAPS_DECOMPOSE_MODEL", "").strip()
    if role_backend or role_model:
        return _build_role_client("decompose")
    return _build_planner_model_client()


def _build_role_client(role: str) -> ModelClient:
    """Build a model client for a named role (blue, red, referee, create_game).

    Checks BAPS_{ROLE}_BACKEND and BAPS_{ROLE}_MODEL first; falls back to the
    global _build_model_client() when no role-specific vars are set.
    """
    role_upper = role.upper()
    role_backend = os.getenv(f"BAPS_{role_upper}_BACKEND", "").strip().lower()
    role_model = os.getenv(f"BAPS_{role_upper}_MODEL", "").strip()

    if not role_backend and not role_model:
        return _build_model_client()

    backend = role_backend or os.getenv("BAPS_BACKEND", "ollama").lower()

    if backend == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key.strip():
            raise ValueError("ANTHROPIC_API_KEY must be set for anthropic backend")
        return AnthropicClient(
            model=role_model or os.getenv("BAPS_ANTHROPIC_MODEL", _DEFAULT_ANTHROPIC_MODEL),
            api_key=api_key,
            base_url=os.getenv("BAPS_ANTHROPIC_BASE_URL", _DEFAULT_ANTHROPIC_BASE_URL),
        )
    if backend == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key.strip():
            raise ValueError("OPENAI_API_KEY must be set for openai backend")
        return OpenAIClient(
            model=role_model or os.getenv("BAPS_OPENAI_MODEL", _DEFAULT_OPENAI_MODEL),
            api_key=api_key,
            base_url=os.getenv("BAPS_OPENAI_BASE_URL", _DEFAULT_OPENAI_BASE_URL),
        )
    return OllamaClient(
        model=role_model or os.getenv("BAPS_OLLAMA_MODEL", _DEFAULT_OLLAMA_MODEL),
        base_url=os.getenv("BAPS_OLLAMA_BASE_URL", _DEFAULT_OLLAMA_BASE_URL),
    )


# Role schemas.
# constrained=True: Ollama constrained decoding enforces the schema at inference time.
# Safe only when all string fields are enums or carry maxLength.
# constrained=False: schema is prompt-documentation only; model is free to emit any string.
#
# CreateGame and Blue have unbounded free-text string fields (objective, file content)
# and must use constrained=False.
# Red and Referee have only enum strings plus maxLength-bounded rationale/hints,
# so constrained=True is safe.
_CREATE_GAME_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "objective": {"type": "string"},
        "target_artifact_id": {"type": "string"},
        "allowed_delta_type": {"type": "string"},
        "success_condition": {"type": "string"},
        "no_new_game": {"type": "boolean"},
        "reason": {"type": "string"},
        "northstar_update_needed": {"type": "boolean"},
        "rationale": {"type": "string"},
        "proposed_northstar": {"type": "string"},
    },
    "additionalProperties": False,
}
_RED_FINDING_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "disposition": {"type": "string", "enum": ["accept", "revise", "reject"]},
        "rationale": {"type": "string", "maxLength": 500},
        "success_condition_met": {"type": ["boolean", "null"]},
        "findings": {"type": "array", "items": {"type": "string", "maxLength": 300}},
    },
    "required": ["disposition", "rationale"],
    "additionalProperties": False,
}
_REFEREE_DECISION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "disposition": {"type": "string", "enum": ["accept", "revise", "reject"]},
        "rationale": {"type": "string", "maxLength": 500},
        "red_override": {"type": ["boolean", "null"]},
        "improvement_hints": {"type": "array", "items": {"type": "string", "maxLength": 300}},
    },
    "required": ["disposition", "rationale"],
    "additionalProperties": False,
}


def _require_non_empty(value: str, field_name: str) -> str:
    if value.strip() == "":
        raise ValueError(f"{field_name} must be non-empty")
    return value



_KNOWN_SPEC_KEYS = frozenset({
    "workspace",
    "project_type",
    "artifact_id",
    "northstar_markdown",
    "northstar_path",
    "goal",
    "output",
    "max_iterations",
    "source_path",
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
        return output_candidate
    return workspace / output_candidate


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
    if getattr(args, "command", None) == "run":
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

    config = {
        "workspace": workspace,
        "project_type": project_type,
        "artifact_id": artifact_id,
        "northstar_markdown": northstar_markdown,
        "goal": goal,
        "output_path": output_path,
        "max_iterations": max_iterations,
        "spec_path": spec_path,
        "source_path": source_path,
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


def _render_create_game_prompt(
    config: dict[str, Any],
    state: State,
    state_view: StateView,
    verification_result: VerificationResult | None = None,
    adapter: ProjectTypeAdapter | None = None,
    context_chain: tuple[str, ...] = (),
) -> str:
    resolved_adapter = (
        adapter
        if adapter is not None
        else _resolve_project_type_adapter(config["project_type"])
    )
    supplement = resolved_adapter.render_create_game_prompt_supplement(
        state=state,
        config=config,
        state_view=state_view,
        verification_result=verification_result,
    )
    verification_block = ""
    if verification_result is not None:
        verification_json = json.dumps(
            {
                "command": verification_result.command,
                "cwd": verification_result.cwd,
                "exit_code": verification_result.exit_code,
                "stdout": verification_result.stdout,
                "stderr": verification_result.stderr,
                "passed": verification_result.passed,
            },
            sort_keys=True,
        )
        verification_block = (
            "- previous_verification_result_json: "
            f"{verification_json}\n"
            "- previous_verification_result_json applies only to the previous exported state.\n\n"
        )
    context_block = ""
    if context_chain:
        lines = ["Parent planning context (gap decomposition chain, coarsest → finest):"]
        for i, desc in enumerate(context_chain):
            lines.append(f"  [{i + 1}] {desc}")
        lines.append("  [current] Plan within this scope.\n")
        context_block = "\n".join(lines) + "\n"
    return (
        "Create a GameSpec JSON object that closes the highest-priority gap between current state and NorthStar.\n\n"
        f"{context_block}"
        "Input:\n"
        f"- goal: {config['goal']}\n"
        "- state_view:\n"
        "\n"
        f"{state_view.content}\n"
        "\n"
        f"- artifact_id: {_config_artifact_id(config)}\n\n"
        f"{verification_block}"
        "Process — work through these steps before producing output:\n\n"
        "STEP 1 — GAP ANALYSIS:\n"
        "  Compare the current state (state_view) against NorthStar intent (and parent context if present).\n"
        "  Enumerate what is absent, incomplete, or incorrect within your current scope.\n"
        "  Be specific: name the missing pieces, not just categories.\n\n"
        "STEP 2 — PRIORITIZE:\n"
        "  Select the single highest-impact gap — the one that unblocks the most downstream work.\n\n"
        "STEP 3 — DECIDE: direct game or decompose?\n"
        "  If the gap can be closed coherently by Blue in one turn: produce a GameSpec.\n"
        "  If the gap is too large or spans multiple independent concerns: decompose it.\n\n"
        "STEP 4 — SELF-CONTAIN:\n"
        "  Fold all relevant intent into objective and success_condition (GameSpec).\n"
        "  Or into sub_gap descriptions (decompose). Each sub_gap must be specific enough\n"
        "  to recursively plan from, and together they must fully close the parent gap.\n\n"
        "Return only a JSON object.\n"
        "Do not wrap output in markdown.\n"
        "Do not use triple-backtick fences.\n"
        "Do not include prose before or after JSON.\n"
        "No extra fields.\n\n"
        "If all gaps in current scope are closed, return exactly:\n"
        '{\"no_new_game\": true, \"reason\": \"...\"}\n\n'
        "If this gap is too large or spans independent concerns, return exactly:\n"
        '{\"decompose\": true, \"rationale\": \"...\", \"sub_gaps\": [{\"description\": \"...\"}, ...]}\n'
        "Sub-gaps must partition the current gap: together they close it, individually they are coherent.\n"
        "Sub-gaps are executed strictly in list order — each sub-gap runs to completion before the next begins.\n"
        "Order sub-gaps by dependency: if sub-gap B requires anything that sub-gap A produces, A must appear before B.\n"
        "A sub-gap must never depend on the output of a later sub-gap.\n\n"
        "If the current trajectory cannot satisfy NorthStar without changing NorthStar itself, return exactly:\n"
        '{\"northstar_update_needed\": true, \"rationale\": \"...\", \"proposed_northstar\": \"...\"}\n'
        "proposed_northstar must contain the complete updated NorthStar content as a plain string.\n\n"
        "GameSpec JSON shape:\n"
        "{\n"
        '  "objective": "...",\n'
        '  "target_artifact_id": "...",\n'
        '  "allowed_delta_type": "...",\n'
        '  "success_condition": "..."\n'
        "}\n\n"
        "objective: name the gap being closed and what the closed state looks like.\n"
        "success_condition: verifiable from the artifact alone — state what must be present or true.\n"
        "Do not artificially split a coherent gap into multiple games — use decompose instead.\n"
        "All files or sections that must change together to close a gap belong in one game.\n"
        f"For this project type, allowed_delta_type must be {resolved_adapter.supported_delta_type}.\n"
        f"{supplement}"
    )


def _ensure_target_artifact_exists(state: State, artifact_id: str) -> None:
    _ = next((a for a in state.artifacts if a.id == artifact_id), None)
    if _ is None:
        raise ValueError(f"create_game target artifact not found in state: {artifact_id}")


def _parse_game_spec_json(text: str) -> GameSpec:
    normalized = normalize_json_candidate(text)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ValueError("create_game model output must be valid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("create_game model output must be a JSON object")

    required_keys = {
        "objective",
        "target_artifact_id",
        "allowed_delta_type",
        "success_condition",
    }
    if set(parsed.keys()) != required_keys:
        raise ValueError(
            "create_game model output must contain exactly keys: "
            "objective, target_artifact_id, allowed_delta_type, success_condition"
        )

    try:
        return GameSpec.model_validate(parsed)
    except Exception as exc:
        raise ValueError("create_game model output failed GameSpec validation") from exc


def _parse_create_game_output(text: str) -> GameSpec | DecomposeSpec:
    normalized = normalize_json_candidate(text)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ValueError("create_game model output must be valid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("create_game model output must be a JSON object")

    if set(parsed.keys()) == {"no_new_game", "reason"}:
        if parsed["no_new_game"] is not True:
            raise ValueError(
                "create_game no-game response must set no_new_game=true"
            )
        reason = str(parsed["reason"]).strip()
        if not reason:
            raise ValueError("create_game no-game response reason must be non-empty")
        raise NoNewGameError(reason)

    if set(parsed.keys()) == {"northstar_update_needed", "rationale", "proposed_northstar"}:
        if parsed["northstar_update_needed"] is not True:
            raise ValueError(
                "create_game northstar_update_needed response must set northstar_update_needed=true"
            )
        rationale = str(parsed["rationale"]).strip()
        if not rationale:
            raise ValueError(
                "create_game northstar_update_needed response rationale must be non-empty"
            )
        proposed_northstar = str(parsed["proposed_northstar"]).strip()
        if not proposed_northstar:
            raise ValueError(
                "create_game northstar_update_needed response proposed_northstar must be non-empty"
            )
        raise NorthStarUpdateNeededError(
            rationale=rationale, proposed_northstar=proposed_northstar
        )

    if set(parsed.keys()) == {"decompose", "rationale", "sub_gaps"}:
        if parsed["decompose"] is not True:
            raise ValueError("create_game decompose response must set decompose=true")
        rationale = str(parsed["rationale"]).strip()
        if not rationale:
            raise ValueError("create_game decompose response rationale must be non-empty")
        sub_gaps_raw = parsed["sub_gaps"]
        if not isinstance(sub_gaps_raw, list) or not sub_gaps_raw:
            raise ValueError("create_game decompose response sub_gaps must be a non-empty list")
        sub_gaps = tuple(
            SubGapSpec(description=str(sg.get("description", "")).strip())
            for sg in sub_gaps_raw
            if isinstance(sg, dict)
        )
        if not sub_gaps:
            raise ValueError("create_game decompose response sub_gaps contained no valid entries")
        return DecomposeSpec(rationale=rationale, sub_gaps=sub_gaps)

    return _parse_game_spec_json(normalized)


def _validate_game_spec(game_spec: GameSpec) -> None:
    _debug_print_create_game_validation_input(game_spec)
    if not game_spec.objective.strip():
        raise ValueError("create_game model output objective must be non-empty")
    if not game_spec.success_condition.strip():
        raise ValueError("create_game model output success_condition must be non-empty")
    if not game_spec.target_artifact_id.strip():
        raise ValueError("create_game model output target_artifact_id must be non-empty")
    if not game_spec.allowed_delta_type.strip():
        raise ValueError("create_game model output allowed_delta_type must be non-empty")


def _normalize_game_spec_with_adapter(
    adapter: ProjectTypeAdapter,
    game_spec: GameSpec,
    state: State,
    config: dict[str, Any],
) -> GameSpec:
    normalizer = getattr(adapter, "normalize_game_spec", None)
    if normalizer is None:
        return game_spec
    return normalizer(game_spec, state, config)


def _render_red_prompt_supplement_with_adapter(
    adapter: ProjectTypeAdapter,
    state_view: StateView,
    game_spec: GameSpec,
    delta_state: DeltaState,
    verification_result: VerificationResult | None,
) -> str:
    renderer = getattr(adapter, "render_red_prompt_supplement", None)
    if renderer is None:
        return ""
    return renderer(
        state_view=state_view,
        game_spec=game_spec,
        delta_state=delta_state,
        verification_result=verification_result,
    )


def _render_referee_prompt_supplement_with_adapter(
    adapter: ProjectTypeAdapter,
    state_view: StateView,
    game_spec: GameSpec,
    delta_state: DeltaState,
    verification_result: VerificationResult | None,
) -> str:
    renderer = getattr(adapter, "render_referee_prompt_supplement", None)
    if renderer is None:
        return ""
    return renderer(
        state_view=state_view,
        game_spec=game_spec,
        delta_state=delta_state,
        verification_result=verification_result,
    )



_RED_REQUIRED_KEYS = frozenset({"disposition", "rationale"})
_RED_OPTIONAL_KEYS = frozenset({"success_condition_met", "findings"})
_REFEREE_REQUIRED_KEYS = frozenset({"disposition", "rationale"})
_REFEREE_OPTIONAL_KEYS = frozenset({"red_override", "improvement_hints"})


def _parse_red_finding_json(text: str) -> RedFinding:
    normalized = normalize_json_candidate(text)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ValueError("red model output must be valid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("red model output must be a JSON object")

    present = set(parsed.keys())
    if not _RED_REQUIRED_KEYS.issubset(present):
        missing = _RED_REQUIRED_KEYS - present
        raise ValueError(f"red model output missing required keys: {sorted(missing)}")
    unexpected = present - _RED_REQUIRED_KEYS - _RED_OPTIONAL_KEYS
    if unexpected:
        raise ValueError(f"red model output contains unexpected keys: {sorted(unexpected)}")

    try:
        return RedFinding.model_validate(parsed)
    except Exception as exc:
        raise ValueError("red model output failed RedFinding validation") from exc


def _parse_referee_decision_json(text: str) -> RefereeDecision:
    normalized = normalize_json_candidate(text)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ValueError("referee model output must be valid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("referee model output must be a JSON object")

    present = set(parsed.keys())
    if not _REFEREE_REQUIRED_KEYS.issubset(present):
        missing = _REFEREE_REQUIRED_KEYS - present
        raise ValueError(f"referee model output missing required keys: {sorted(missing)}")
    unexpected = present - _REFEREE_REQUIRED_KEYS - _REFEREE_OPTIONAL_KEYS
    if unexpected:
        raise ValueError(f"referee model output contains unexpected keys: {sorted(unexpected)}")

    try:
        return RefereeDecision.model_validate(parsed)
    except Exception as exc:
        raise ValueError("referee model output failed RefereeDecision validation") from exc


def create_game(
    config: dict[str, Any],
    state: State,
    model_client: ModelClient | None = None,
    adapter: ProjectTypeAdapter | None = None,
    verification_result: VerificationResult | None = None,
    context_chain: tuple[str, ...] = (),
    depth: int = 0,
) -> GameSpec | DecomposeSpec:
    _debug_print_create_game_input(state)
    resolved_adapter = (
        adapter
        if adapter is not None
        else _resolve_project_type_adapter(config["project_type"])
    )
    state_view = resolved_adapter.build_create_game_state_view(state, config)
    use_planner = model_client is None
    if use_planner:
        client = _build_decompose_client() if depth > 0 else _build_planner_model_client()
    else:
        client = model_client
    role_name = "decompose" if depth > 0 else "create_game"
    role = Role(role_name, client, _CREATE_GAME_SCHEMA, constrained=False)
    prompt = _render_create_game_prompt(
        config=config,
        state=state,
        state_view=state_view,
        verification_result=verification_result,
        adapter=resolved_adapter,
        context_chain=context_chain,
    )
    _debug_print_create_game_prompt(prompt)
    generated = role.generate(prompt)
    _debug_print_create_game_raw_model_output(generated)
    try:
        result = _parse_create_game_output(generated)
    except ValueError as exc:
        if "valid JSON" not in str(exc) or not use_planner:
            raise
        # Planner returned empty or unparseable output — retry once with executor model
        if _debug_enabled():
            print(f"[DEBUG] {role_name}.fallback: planner invalid JSON, retrying with executor model")
        fallback_role = Role(role_name, _build_role_client("create_game"), _CREATE_GAME_SCHEMA, constrained=False)
        generated = fallback_role.generate(prompt)
        _debug_print_create_game_raw_model_output(generated)
        result = _parse_create_game_output(generated)
    except NoNewGameError:
        raise

    if isinstance(result, DecomposeSpec):
        _debug_print_create_game_output(result)
        return result

    game_spec = _normalize_game_spec_with_adapter(
        resolved_adapter, result, state, config
    )
    try:
        _validate_game_spec(game_spec)
    except ValueError as exc:
        _debug_print_create_game_validation_failure(str(exc))
        raise
    expected_artifact_id = _config_artifact_id(config)
    if game_spec.target_artifact_id != expected_artifact_id:
        raise ValueError(
            "create_game target artifact must match configured artifact_id: "
            f"expected {expected_artifact_id}, got {game_spec.target_artifact_id}"
        )
    _ensure_target_artifact_exists(state, game_spec.target_artifact_id)
    if game_spec.allowed_delta_type != resolved_adapter.supported_delta_type:
        raise ValueError(
            "create_game allowed_delta_type must match project adapter: "
            f"expected {resolved_adapter.supported_delta_type}, got {game_spec.allowed_delta_type}"
        )
    _debug_print_create_game_output(game_spec)
    return game_spec



def _render_red_prompt(
    state_view: StateView,
    game_spec: GameSpec,
    delta_state: DeltaState,
    verification_result: VerificationResult | None = None,
    prompt_supplement: str = "",
) -> str:
    state_view_json = json.dumps(state_view.model_dump(mode="json"), sort_keys=True)
    delta_state_json = json.dumps(delta_state.model_dump(mode="json"), sort_keys=True)
    verification_block = ""
    if verification_result is not None:
        verification_json = json.dumps(
            {
                "command": verification_result.command,
                "cwd": verification_result.cwd,
                "exit_code": verification_result.exit_code,
                "stdout": verification_result.stdout,
                "stderr": verification_result.stderr,
                "passed": verification_result.passed,
            },
            sort_keys=True,
        )
        verification_block = (
            f"- verification_result_json: {verification_json}\n"
            "Verification guidance:\n"
            "- Treat verification_result_json as execution evidence.\n"
            "- If verification passed, treat that as strong evidence toward accept.\n"
            "- If verification failed, reason from exit_code/stdout/stderr evidence.\n\n"
        )
    return (
        "Evaluate the candidate DeltaState and return a RedFinding JSON object.\n\n"
        "Input:\n"
        f"- state_view_json: {state_view_json}\n"
        f"- delta_state_json: {delta_state_json}\n"
        f"- objective: {game_spec.objective}\n"
        f"- target_artifact_id: {game_spec.target_artifact_id}\n"
        f"- allowed_delta_type: {game_spec.allowed_delta_type}\n"
        f"- success_condition: {game_spec.success_condition}\n\n"
        f"{verification_block}"
        "Evaluation policy:\n"
        "- Treat GameSpec.success_condition as authoritative acceptance contract.\n"
        "- Evaluate only against objective, success_condition, and validity/safety constraints.\n"
        "- Determine whether the candidate DeltaState moves the project toward the objective.\n"
        "- Determine whether the candidate satisfies the success_condition.\n"
        "- Identify inconsistency, harm, incompleteness, or quality issues.\n"
        "- Reject/revise only for: contradiction with success_condition, invalid delta, missing required artifact change, or explicit quality/safety issue.\n"
        "- Do not invent stronger requirements than objective/success_condition.\n"
        "- Do not demand more comprehensive/complete coverage unless explicitly required by GameSpec.\n"
        "- Do not add stricter standards such as 'more comprehensive', 'better coverage', 'stronger tests', or 'more complete' unless those words (or equivalent requirements) are explicit in GameSpec.\n"
        "- Use revise only when the candidate is promising but needs improvement for goal satisfaction.\n"
        "- Do NOT reject or revise merely because state differs from the original state.\n\n"
        "Return only a JSON object.\n"
        "Do not wrap output in markdown.\n"
        "Do not use triple-backtick fences.\n"
        "Do not include prose before JSON.\n"
        "Do not include prose after JSON.\n"
        f"{prompt_supplement}"
        "Required JSON shape:\n"
        "{\n"
        '  "disposition": "accept" | "revise" | "reject",\n'
        '  "rationale": "...",\n'
        '  "success_condition_met": true | false,\n'
        '  "findings": ["<specific issue 1>", "<specific issue 2>"]\n'
        "}\n"
        "findings must be an empty list for accept. "
        "success_condition_met must be true for accept and false for revise/reject.\n"
    )


def _render_referee_prompt(
    state_view: StateView,
    game_spec: GameSpec,
    delta_state: DeltaState,
    red_finding: RedFinding,
    verification_result: VerificationResult | None = None,
    prompt_supplement: str = "",
) -> str:
    state_view_json = json.dumps(state_view.model_dump(mode="json"), sort_keys=True)
    delta_state_json = json.dumps(delta_state.model_dump(mode="json"), sort_keys=True)
    red_finding_json = json.dumps(red_finding.model_dump(mode="json"), sort_keys=True)
    verification_block = ""
    if verification_result is not None:
        verification_json = json.dumps(
            {
                "command": verification_result.command,
                "cwd": verification_result.cwd,
                "exit_code": verification_result.exit_code,
                "stdout": verification_result.stdout,
                "stderr": verification_result.stderr,
                "passed": verification_result.passed,
            },
            sort_keys=True,
        )
        verification_block = (
            f"- verification_result_json: {verification_json}\n"
            "Verification guidance:\n"
            "- Treat verification_result_json as execution evidence.\n"
            "- If verification passed, treat that as strong evidence toward accept.\n"
            "- If verification failed, reason from exit_code/stdout/stderr evidence.\n\n"
        )
    return (
        "Act as Referee and decide whether to accept, revise, or reject the candidate delta.\n\n"
        "Input:\n"
        f"- state_view_json: {state_view_json}\n"
        f"- delta_state_json: {delta_state_json}\n"
        f"- red_finding_json: {red_finding_json}\n"
        f"- objective: {game_spec.objective}\n"
        f"- target_artifact_id: {game_spec.target_artifact_id}\n"
        f"- allowed_delta_type: {game_spec.allowed_delta_type}\n"
        f"- success_condition: {game_spec.success_condition}\n\n"
        f"{verification_block}"
        "Referee authority scope:\n"
        "- You are the game-local authority for this PlayGame decision.\n"
        "- You do NOT decide final State integration; integration is decided later by Integrator.\n\n"
        "Decision policy:\n"
        "- Treat GameSpec.success_condition as authoritative acceptance contract.\n"
        "- Evaluate only against objective, success_condition, and validity/safety constraints.\n"
        "- accept: objective/success_condition are satisfied enough for this game AND Red has no unresolved material findings.\n"
        "- revise: objective/success_condition are only partially satisfied OR Red has unresolved improvements that should be addressed.\n"
        "- reject: candidate is invalid, harmful, incoherent, or wrong direction.\n"
        "- Do not invent stronger requirements than objective/success_condition.\n"
        "- Do not require broader coverage/comprehensiveness unless explicitly required by GameSpec.\n"
        "- Do not add stricter standards such as 'more comprehensive', 'better coverage', 'stronger tests', or 'more complete' unless those words (or equivalent requirements) are explicit in GameSpec.\n"
        "- Do NOT choose revise merely because state changed.\n\n"
        "Return only a JSON object.\n"
        "Do not wrap output in markdown.\n"
        "Do not use triple-backtick fences.\n"
        "Do not include prose before JSON.\n"
        "Do not include prose after JSON.\n"
        f"{prompt_supplement}"
        "Required JSON shape:\n"
        "{\n"
        '  "disposition": "accept" | "revise" | "reject",\n'
        '  "rationale": "...",\n'
        '  "red_override": true | false,\n'
        '  "improvement_hints": ["<specific actionable improvement 1>", "<specific actionable improvement 2>"]\n'
        "}\n"
        "red_override must be true when your disposition differs from Red's disposition. "
        "improvement_hints must be empty for accept.\n"
    )


def play_game(
    state: State,
    game_spec: GameSpec,
    adapter: ProjectTypeAdapter | None = None,
    model_client: ModelClient | None = None,
    red_model_client: ModelClient | None = None,
    referee_model_client: ModelClient | None = None,
    verification_result: VerificationResult | None = None,
    max_attempts: int = _DEFAULT_MAX_PLAY_GAME_ATTEMPTS,
) -> DeltaState | None:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    resolved_adapter = (
        adapter
        if adapter is not None
        else _resolve_adapter_for_allowed_delta_type(game_spec.allowed_delta_type)
    )
    _debug_print_play_game_input(state, game_spec)
    state_view = resolved_adapter.build_state_view(state, game_spec)
    runtime = PlayGameRuntime()
    previous_feedback: dict[str, Any] | None = None
    if verification_result is not None:
        previous_feedback = {
            "prior_export_verification": {
                "exit_code": verification_result.exit_code,
                "passed": verification_result.passed,
                "stdout": verification_result.stdout,
                "stderr": verification_result.stderr,
            }
        }
    blue_role = Role(
        "blue",
        model_client if model_client is not None else _build_role_client("blue"),
        resolved_adapter.build_blue_output_format(),
        constrained=False,
    )
    red_role = Role(
        "red",
        red_model_client if red_model_client is not None else _build_role_client("red"),
        _RED_FINDING_SCHEMA,
        constrained=True,
    )
    referee_role = Role(
        "referee",
        referee_model_client if referee_model_client is not None else _build_role_client("referee"),
        _REFEREE_DECISION_SCHEMA,
        constrained=True,
    )
    for attempt in range(1, max_attempts + 1):
        _debug_print_play_game_attempt(attempt)
        _debug_print_blue_input(state_view, game_spec, attempt, previous_feedback)
        blue_prompt = resolved_adapter.render_blue_prompt(
            state_view, game_spec, attempt, previous_feedback
        )
        blue_tools = resolved_adapter.build_blue_tools()
        blue_tool_call = None
        try:
            blue_tool_call = blue_role.generate_with_tools(blue_prompt, blue_tools)
        except ValueError:
            pass
        if blue_tool_call is not None:
            try:
                candidate_delta = resolved_adapter.tool_call_to_delta(blue_tool_call)
            except ValueError as exc:
                _debug_print_blue_failed_tool_call(blue_tool_call)
                reason = f"blue output failed DeltaState validation: {exc}"
                _debug_print_attempt_rejected(attempt, reason)
                previous_feedback = {
                    "attempt_rejection": {
                        "stage": "blue",
                        "reason": reason,
                        "validation_error": str(exc),
                    }
                }
                continue
        else:
            blue_generated = blue_role.generate(blue_prompt)
            try:
                candidate_delta = resolved_adapter.parse_blue_delta(blue_generated)
            except ValueError as exc:
                reason = f"blue output failed DeltaState validation: {exc}"
                _debug_print_attempt_rejected(attempt, reason)
                previous_feedback = {
                    "attempt_rejection": {
                        "stage": "blue",
                        "reason": reason,
                        "validation_error": str(exc),
                    }
                }
                continue
        _debug_print_blue_output(candidate_delta)

        if verification_result is None:
            _debug_print_red_input(state_view, game_spec, candidate_delta)
        else:
            _debug_print_red_input(
                state_view, game_spec, candidate_delta, verification_result
            )
        red_supplement = _render_red_prompt_supplement_with_adapter(
            resolved_adapter,
            state_view,
            game_spec,
            candidate_delta,
            verification_result,
        )
        red_prompt = _render_red_prompt(
            state_view,
            game_spec,
            candidate_delta,
            verification_result,
            red_supplement,
        )
        red_generated = red_role.generate(red_prompt)
        red_finding = _parse_red_finding_json(red_generated)
        _debug_print_red_output(red_finding)

        if verification_result is None:
            _debug_print_referee_input(
                state_view, game_spec, candidate_delta, red_finding
            )
        else:
            _debug_print_referee_input(
                state_view, game_spec, candidate_delta, red_finding, verification_result
            )
        referee_supplement = _render_referee_prompt_supplement_with_adapter(
            resolved_adapter,
            state_view,
            game_spec,
            candidate_delta,
            verification_result,
        )
        referee_prompt = _render_referee_prompt(
            state_view,
            game_spec,
            candidate_delta,
            red_finding,
            verification_result,
            referee_supplement,
        )
        referee_generated = referee_role.generate(referee_prompt)
        referee_decision = _parse_referee_decision_json(referee_generated)
        _debug_print_referee_output(referee_decision)

        runtime = apply_referee_decision_to_runtime(
            runtime=runtime,
            candidate_delta=candidate_delta,
            decision=referee_decision,
        )
        if referee_decision.disposition == "accept":
            candidate_result = _verify_candidate_with_adapter(
                resolved_adapter, candidate_delta, state, game_spec.target_artifact_id
            )
            if (
                candidate_result is not None
                and not candidate_result.passed
                and attempt < max_attempts
            ):
                previous_feedback = {
                    "red_finding": red_finding.model_dump(mode="json"),
                    "referee_decision": referee_decision.model_dump(mode="json"),
                    "candidate_verification": {
                        "exit_code": candidate_result.exit_code,
                        "passed": False,
                        "stdout": candidate_result.stdout,
                        "stderr": candidate_result.stderr,
                    },
                }
                continue
            _debug_print_play_game_output(runtime.current_best_delta)
            return runtime.current_best_delta
        previous_feedback = {
            "red_finding": red_finding.model_dump(mode="json"),
            "referee_decision": referee_decision.model_dump(mode="json"),
        }
    _debug_print_play_game_output(runtime.current_best_delta)
    return runtime.current_best_delta


def _derive_state_update_from_delta(
    delta_state: DeltaState, adapter: ProjectTypeAdapter
) -> StateUpdateProposal:
    return adapter.delta_to_state_update(delta_state)


def _verify_export_with_adapter(
    adapter: ProjectTypeAdapter, output_path: Path, state: State, artifact_id: str
) -> VerificationResult | None:
    verifier = getattr(adapter, "verify_export", None)
    if verifier is None:
        return None
    return verifier(output_path, state, artifact_id)


def _verify_candidate_with_adapter(
    adapter: ProjectTypeAdapter,
    delta_state: DeltaState,
    state: State,
    artifact_id: str,
) -> VerificationResult | None:
    verifier = getattr(adapter, "verify_candidate", None)
    if verifier is None:
        return None
    return verifier(delta_state, state, artifact_id)


def _commit_export_with_adapter(
    adapter: ProjectTypeAdapter, output_path: Path, game_spec: GameSpec
) -> bool:
    committer = getattr(adapter, "commit_export", None)
    if committer is None:
        return False
    committed = committer(output_path, game_spec)
    if _debug_enabled() and committed:
        print(f"[DEBUG] commit_export: committed export to git at {output_path}")
    return committed


def _append_northstar_proposal_to_blackboard(
    workspace: Path, rationale: str, proposed_northstar: str
) -> None:
    blackboard_dir = workspace / _BLACKBOARD_DIR
    blackboard_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "event": "northstar_update_proposal",
        "rationale": rationale,
        "proposed_northstar": proposed_northstar,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    proposals_path = blackboard_dir / _NORTHSTAR_PROPOSALS_FILE
    with proposals_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


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


def _ensure_not_initialized(workspace: Path) -> None:
    if _state_path_for_workspace(workspace).exists():
        raise ValueError("project already initialized")


def _ensure_initialized(workspace: Path) -> None:
    if not _state_path_for_workspace(workspace).exists():
        raise ValueError("project state not initialized")


def _initialize_project(
    config: dict[str, Any],
) -> tuple[StateService, State]:
    workspace = config["workspace"]
    _ensure_not_initialized(workspace)
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
    _ensure_initialized(workspace)
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
        self.stop_reason: str | None = None


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
        )
    except NoNewGameError:
        if depth == 0:
            ctx.stop_reason = "create_game_no_new_game"
        return
    except NorthStarUpdateNeededError as exc:
        _debug_print_northstar_update_proposal(exc.rationale, exc.proposed_northstar)
        _append_northstar_proposal_to_blackboard(
            workspace=config["workspace"],
            rationale=exc.rationale,
            proposed_northstar=exc.proposed_northstar,
        )
        ctx.northstar_proposal_written = True
        ctx.stop_reason = "northstar_update_proposed"
        return

    if isinstance(result, DecomposeSpec):
        if depth >= max_depth:
            print(
                f"[solve_gap] max_depth={max_depth} reached, cannot decompose further; stopping.",
                flush=True,
            )
            ctx.stop_reason = "max_depth_reached"
            return
        print(
            f"[solve_gap] depth={depth} decomposing into {len(result.sub_gaps)} sub-gaps: "
            f"{result.rationale}",
            flush=True,
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
            if ctx.stop_reason is not None:
                return
        return

    # Leaf: GameSpec — inject full context chain and execute
    game_spec = result.model_copy(update={"context_chain": context_chain})
    if context_chain:
        print(
            f"[solve_gap] depth={depth} playing leaf game: {game_spec.objective[:80]}",
            flush=True,
        )

    delta_state = play_game(
        ctx.current_state,
        game_spec,
        adapter=adapter,
        verification_result=ctx.verification_result,
    )
    if delta_state is None:
        ctx.stop_reason = "play_game_no_delta"
        return

    before_state = state_service.load_state()
    updated_state = state_service.apply_delta(delta_state)
    changed = fingerprint_state(before_state) != fingerprint_state(updated_state)

    ctx.output_changed = adapter.export_state(updated_state, output_path, artifact_id)
    ctx.output_exported = ctx.output_exported or ctx.output_changed
    ctx.verification_result = _verify_export_with_adapter(
        adapter, output_path, updated_state, artifact_id
    )
    _debug_print_verification_result(ctx.verification_result)
    if ctx.output_changed:
        _commit_export_with_adapter(adapter, output_path, game_spec)

    ctx.update_applied = True
    ctx.iterations_completed += 1
    ctx.iterations_remaining -= 1
    ctx.current_state = updated_state

    if changed:
        ctx.state_changed = True
    else:
        ctx.stop_reason = "no_state_change"


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

    if ctx.stop_reason is None:
        ctx.stop_reason = "iteration_limit_reached"

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


def _active_model_info() -> dict[str, str]:
    backends_raw = os.getenv("BAPS_BACKENDS", "").strip()
    if backends_raw:
        backends = [b.strip().lower() for b in backends_raw.split(",") if b.strip()]
        return {"backend": ",".join(backends), "model": "fallback-chain"}
    backend = os.getenv("BAPS_BACKEND", "ollama").lower()
    if backend == "anthropic":
        model_id = os.getenv("BAPS_ANTHROPIC_MODEL", _DEFAULT_ANTHROPIC_MODEL)
    elif backend == "openai":
        model_id = os.getenv("BAPS_OPENAI_MODEL", _DEFAULT_OPENAI_MODEL)
    else:
        model_id = os.getenv("BAPS_OLLAMA_MODEL", _DEFAULT_OLLAMA_MODEL)
    return {"backend": backend, "model": model_id}


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run one hardened deterministic baps loop.")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("init", "run", "init_and_run"),
        default="init_and_run",
        help="Lifecycle command.",
    )
    parser.add_argument("--spec", default=None, help="YAML spec path.")
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace directory for runtime outputs.",
    )
    parser.add_argument(
        "--project-type",
        default=None,
        help="Project type (currently supported: document, coding, audit).",
    )
    parser.add_argument(
        "--artifact-id",
        default=None,
        help="Artifact id for project state.",
    )
    parser.add_argument(
        "--goal",
        default=None,
        help="Runtime goal text. Required if not set in spec or workspace config.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output markdown path (relative paths are resolved under workspace).",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Maximum loop iterations (must be >= 1).",
    )
    args = parser.parse_args()

    try:
        config = resolve_run_config(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
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
        print(f"error: {exc}", file=sys.stderr)
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
    stop_reason = "not_run"

    try:
        if command == "init":
            _initialize_project(config)
            stop_reason = "initialized_only"
        elif command == "run":
            state_service = _load_project_service(workspace)
            current_state = state_service.load_state()
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
            stop_reason = str(results["stop_reason"])
        else:  # init_and_run
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
            stop_reason = str(results["stop_reason"])
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        stop_reason = "error"
        model_info = _active_model_info()
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

    model_info = _active_model_info()
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
