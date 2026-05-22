from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from baps.models import ModelClient, OllamaClient
from baps.northstar_projection import ProjectionType, StateView
from baps.project_adapter import (
    ProjectTypeAdapter,
    VerificationResult,
    build_default_project_type_adapters,
    resolve_adapter_for_allowed_delta_type,
    resolve_project_type_adapter,
)
from baps.document_adapter import DocumentProjectAdapter
from baps.coding_adapter import CodingProjectAdapter
from baps.state import (
    DeltaState,
    GameSpec,
    PlayGameRuntime,
    RedFinding,
    RefereeDecision,
    State,
    StateUpdateProposal,
    fingerprint_state,
    apply_referee_decision_to_runtime,
    build_default_state_artifact_registry,
)
from baps.state_service import StateService
from baps.state_store import JsonStateStore

REQUEST = "Write a short report."


class NoNewAtomicGameError(ValueError):
    """Raised when the model explicitly indicates no new atomic game is available."""


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


def _debug_print_blue_raw_model_output(raw_text: str) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] blue.raw_model_output:")
    for line in raw_text.splitlines() or [""]:
        print(f"  {line}")
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


def _build_create_game_model_client() -> ModelClient:
    model = os.getenv("BAPS_OLLAMA_MODEL", "llama3.2")
    base_url = os.getenv("BAPS_OLLAMA_BASE_URL", "http://localhost:11434")
    return OllamaClient(model=model, base_url=base_url)


def _build_blue_model_client() -> ModelClient:
    model = os.getenv("BAPS_OLLAMA_MODEL", "llama3.2")
    base_url = os.getenv("BAPS_OLLAMA_BASE_URL", "http://localhost:11434")
    return OllamaClient(model=model, base_url=base_url)


def _build_red_model_client() -> ModelClient:
    model = os.getenv("BAPS_OLLAMA_MODEL", "llama3.2")
    base_url = os.getenv("BAPS_OLLAMA_BASE_URL", "http://localhost:11434")
    return OllamaClient(model=model, base_url=base_url)


def _build_referee_model_client() -> ModelClient:
    model = os.getenv("BAPS_OLLAMA_MODEL", "llama3.2")
    base_url = os.getenv("BAPS_OLLAMA_BASE_URL", "http://localhost:11434")
    return OllamaClient(model=model, base_url=base_url)


def _require_non_empty(value: str, field_name: str) -> str:
    if value.strip() == "":
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _config_artifact_id(config: dict[str, Any]) -> str:
    if "artifact_id" not in config:
        raise ValueError("artifact_id must be non-empty")
    return _require_non_empty(str(config["artifact_id"]), "artifact_id")


def _config_northstar_markdown(config: dict[str, Any]) -> str:
    return _require_non_empty(str(config.get("northstar_markdown", "")), "northstar_markdown")


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
        else spec_data.get("workspace", ".baps-workspace")
    )
    project_type_raw = (
        args.project_type
        if args.project_type is not None
        else spec_data.get("project_type")
    )
    artifact_id_raw = spec_data.get("artifact_id")
    if args.artifact_id is not None:
        artifact_id_raw = args.artifact_id
    if "required_sections" in spec_data:
        raise ValueError(
            "required_sections is no longer supported; declare required structure in northstar_markdown"
        )
    northstar_markdown_raw = spec_data.get("northstar_markdown")
    northstar_path_raw = spec_data.get("northstar_path")
    if northstar_markdown_raw is None and northstar_path_raw is not None:
        northstar_path = Path(str(northstar_path_raw))
        if not northstar_path.is_absolute():
            northstar_path = Path.cwd() / northstar_path
        if not northstar_path.exists():
            raise ValueError(f"northstar_path file not found: {northstar_path}")
        northstar_markdown_raw = northstar_path.read_text(encoding="utf-8")
    goal_raw = args.goal if args.goal is not None else spec_data.get("goal", REQUEST)
    output_raw = args.output if args.output is not None else spec_data.get("output")
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
    goal = _require_non_empty(str(goal_raw), "goal")
    northstar_markdown = _require_non_empty(
        str(northstar_markdown_raw) if northstar_markdown_raw is not None else goal,
        "northstar_markdown",
    )
    workspace = Path(workspace_str)

    if output_raw is None:
        output_path = workspace / "output" / "report.md"
    else:
        output_str = _require_non_empty(str(output_raw), "output")
        output_path = _resolve_output_path(workspace, output_str)

    try:
        max_iterations = int(max_iterations_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_iterations must be an integer >= 1") from exc

    if max_iterations < 1:
        raise ValueError("max_iterations must be >= 1")

    config = {
        "workspace": workspace,
        "project_type": project_type,
        "artifact_id": artifact_id,
        "northstar_markdown": northstar_markdown,
        "goal": goal,
        "output_path": output_path,
        "max_iterations": max_iterations,
        "spec_path": spec_path,
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
    return (
        "Create a GameSpec JSON object for the given project state.\n\n"
        "Derive the next coherent game task from projected state context, including NorthStar intent.\n"
        "CreateGame is State/NorthStar-aware.\n"
        "PlayGame is GameSpec-bound.\n\n"
        "Input:\n"
        f"- goal: {config['goal']}\n"
        "- state_view:\n"
        "\n"
        f"{state_view.content}\n"
        "\n"
        f"- artifact_id: {_config_artifact_id(config)}\n"
        "- Use StateView NorthStar section as authoritative context.\n\n"
        f"{verification_block}"
        "Return only a JSON object.\n"
        "Do not wrap output in markdown.\n"
        "Do not use triple-backtick fences.\n"
        "Do not include prose before JSON.\n"
        "Do not include prose after JSON.\n"
        "No extra fields.\n"
        "If no useful coherent game task remains for current state+northstar, return exactly:\n"
        '{\"no_new_atomic_game\": true, \"reason\": \"...\"}\n'
        "If the current project trajectory does not align with NorthStar intent, return exactly:\n"
        '{\"northstar_update_needed\": true, \"rationale\": \"...\", \"proposed_northstar\": \"...\"}\n'
        "Use northstar_update_needed when the game direction contradicts NorthStar intent or accumulated state has drifted from the NorthStar goal.\n"
        "proposed_northstar must contain the complete updated NorthStar content as a plain string.\n"
        "GameSpec must be self-contained for PlayGame execution without independently reading full NorthStar.\n"
        "The objective must describe BOTH:\n"
        "1. structural change\n"
        "2. substantive local intent\n"
        "Do not emit objectives that only describe structure.\n"
        "The GameSpec must contain enough local intent so PlayGame can execute without reading NorthStar.\n"
        "Fold relevant NorthStar intent into objective and success_condition.\n"
        "Avoid purely structural objectives when NorthStar contains substantive intent.\n"
        "Illustrative examples (not fixed policy):\n"
        "BAD objective: Apply structural formatting only.\n"
        "GOOD objective: Apply one structural change with concrete local intent tied to project goals.\n"
        "BAD success_condition: structure exists.\n"
        "GOOD success_condition: one bounded artifact change exists and satisfies stated local intent.\n"
        "GameSpec should represent one coherent task:\n"
        "- target exactly one artifact.\n"
        "- permit exactly one delta type.\n"
        "- require exactly one coherent state change.\n"
        "- success_condition must be checkable from that one change.\n"
        "- structural change, local content intent, and semantic purpose may coexist when they belong to the same artifact update.\n"
        "- reject only when multiple independent tasks/features are bundled.\n"
        "Examples:\n"
        "- VALID: One bounded artifact update with explicit intent.\n"
        "- INVALID: Two independent feature changes in one GameSpec.\n"
        "- INVALID: Artifact update plus export/operational task in one GameSpec.\n"
        "Required JSON shape:\n"
        "{\n"
        '  "objective": "...",\n'
        '  "target_artifact_id": "...",\n'
        '  "allowed_delta_type": "...",\n'
        '  "success_condition": "..."\n'
        "}\n\n"
        f"For this project type, allowed_delta_type must be {resolved_adapter.supported_delta_type}.\n"
        f"{supplement}"
    )


def _ensure_target_artifact_exists(state: State, artifact_id: str) -> None:
    _ = next((a for a in state.artifacts if a.id == artifact_id), None)
    if _ is None:
        raise ValueError(f"create_game target artifact not found in state: {artifact_id}")


def _parse_game_spec_json(text: str) -> GameSpec:
    normalized = _normalize_json_candidate(text)
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


def _parse_create_game_output(text: str) -> GameSpec:
    normalized = _normalize_json_candidate(text)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ValueError("create_game model output must be valid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("create_game model output must be a JSON object")

    if set(parsed.keys()) == {"no_new_atomic_game", "reason"}:
        if parsed["no_new_atomic_game"] is not True:
            raise ValueError(
                "create_game no-game response must set no_new_atomic_game=true"
            )
        reason = str(parsed["reason"]).strip()
        if not reason:
            raise ValueError("create_game no-game response reason must be non-empty")
        raise NoNewAtomicGameError(reason)

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

    return _parse_game_spec_json(normalized)


def _validate_atomic_game_spec(game_spec: GameSpec) -> None:
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


def _normalize_json_candidate(text: str) -> str:
    normalized = text.strip()
    fence_pattern = re.compile(
        r"\A```(?:json)?[ \t]*\n(?P<body>[\s\S]*?)\n```[ \t]*\Z",
        re.IGNORECASE,
    )
    fence_match = fence_pattern.match(normalized)
    if fence_match is not None:
        normalized = fence_match.group("body").strip()
    return normalized


def _parse_red_finding_json(text: str) -> RedFinding:
    normalized = _normalize_json_candidate(text)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ValueError("red model output must be valid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("red model output must be a JSON object")

    required_keys = {"disposition", "rationale"}
    if set(parsed.keys()) != required_keys:
        raise ValueError(
            "red model output must contain exactly keys: disposition, rationale"
        )

    try:
        return RedFinding.model_validate(parsed)
    except Exception as exc:
        raise ValueError("red model output failed RedFinding validation") from exc


def _parse_referee_decision_json(text: str) -> RefereeDecision:
    normalized = _normalize_json_candidate(text)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ValueError("referee model output must be valid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("referee model output must be a JSON object")

    required_keys = {"disposition", "rationale"}
    if set(parsed.keys()) != required_keys:
        raise ValueError(
            "referee model output must contain exactly keys: disposition, rationale"
        )

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
) -> GameSpec:
    _debug_print_create_game_input(state)
    resolved_adapter = (
        adapter
        if adapter is not None
        else _resolve_project_type_adapter(config["project_type"])
    )
    state_view = resolved_adapter.build_create_game_state_view(state, config)
    client = model_client if model_client is not None else _build_create_game_model_client()
    prompt = _render_create_game_prompt(
        config=config,
        state=state,
        state_view=state_view,
        verification_result=verification_result,
        adapter=resolved_adapter,
    )
    _debug_print_create_game_prompt(prompt)
    generated = client.generate(prompt)
    _debug_print_create_game_raw_model_output(generated)
    try:
        game_spec = _parse_create_game_output(generated)
    except (ValueError, NoNewAtomicGameError):
        raise
    game_spec = _normalize_game_spec_with_adapter(
        resolved_adapter, game_spec, state, config
    )
    try:
        _validate_atomic_game_spec(game_spec)
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


def _render_blue_prompt(
    state_view: StateView,
    game_spec: GameSpec,
    attempt_number: int,
    previous_feedback: dict[str, Any] | None,
    project_delta_instructions: str = "",
) -> str:
    previous_feedback_json = json.dumps(previous_feedback, sort_keys=True)
    return (
        "Produce exactly one delta JSON object allowed by GameSpec.allowed_delta_type.\n\n"
        "Input:\n"
        "- state_view:\n"
        "\n"
        f"{state_view.content}\n"
        "\n"
        f"- attempt_number: {attempt_number}\n"
        f"- previous_feedback_json: {previous_feedback_json}\n"
        f"- objective: {game_spec.objective}\n"
        f"- target_artifact_id: {game_spec.target_artifact_id}\n"
        f"- allowed_delta_type: {game_spec.allowed_delta_type}\n"
        f"- success_condition: {game_spec.success_condition}\n\n"
        "Execution rules:\n"
        "- Produce one delta that satisfies objective and success_condition.\n"
        "- Use StateView as the current artifact context.\n"
        "- Do not duplicate existing artifact content.\n"
        "- Do not rewrite unrelated existing state.\n"
        "- Do not emit placeholder or filler content.\n"
        "- If previous_feedback_json contains validation errors, repair those exact errors in this attempt.\n"
        "- Do not repeat outputs that fail previously reported validation constraints.\n"
        "- When attempt_number > 1, treat previous_feedback_json as mandatory correction requirements.\n\n"
        "Return only a JSON object.\n"
        "Do not wrap output in markdown.\n"
        "Do not use triple-backtick fences.\n"
        "Do not include prose before JSON.\n"
        "Do not include prose after JSON.\n"
        "No extra fields.\n\n"
        f"{project_delta_instructions}"
    )


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
            "- If pytest discovered tests, do not claim test files are empty.\n"
            "- If verification passed, treat that as strong evidence toward accept.\n"
            "- If verification failed, reason from exit_code/stdout/stderr evidence.\n\n"
        )
    return (
        "Evaluate the candidate DeltaDocumentState and return a RedFinding JSON object.\n\n"
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
        "No extra fields.\n"
        f"{prompt_supplement}"
        "Required JSON shape:\n"
        "{\n"
        '  "disposition": "accept" | "revise" | "reject",\n'
        '  "rationale": "..."\n'
        "}"
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
            "- If pytest discovered tests, do not claim test files are empty.\n"
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
        "No extra fields.\n"
        f"{prompt_supplement}"
        "Required JSON shape:\n"
        "{\n"
        '  "disposition": "accept" | "revise" | "reject",\n'
        '  "rationale": "..."\n'
        "}"
    )


def play_game(
    state: State,
    game_spec: GameSpec,
    adapter: ProjectTypeAdapter | None = None,
    model_client: ModelClient | None = None,
    red_model_client: ModelClient | None = None,
    referee_model_client: ModelClient | None = None,
    verification_result: VerificationResult | None = None,
    max_attempts: int = 3,
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
    client = model_client if model_client is not None else _build_blue_model_client()
    red_client = (
        red_model_client if red_model_client is not None else _build_red_model_client()
    )
    referee_client = (
        referee_model_client
        if referee_model_client is not None
        else _build_referee_model_client()
    )
    for attempt in range(1, max_attempts + 1):
        _debug_print_play_game_attempt(attempt)
        _debug_print_blue_input(state_view, game_spec, attempt, previous_feedback)
        blue_prompt = resolved_adapter.render_blue_prompt(
            state_view, game_spec, attempt, previous_feedback
        )
        blue_generated = client.generate(blue_prompt)
        try:
            candidate_delta = resolved_adapter.parse_blue_delta(blue_generated)
        except ValueError as exc:
            _debug_print_blue_raw_model_output(blue_generated)
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
        red_generated = red_client.generate(red_prompt)
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
        referee_generated = referee_client.generate(referee_prompt)
        referee_decision = _parse_referee_decision_json(referee_generated)
        _debug_print_referee_output(referee_decision)

        runtime = apply_referee_decision_to_runtime(
            runtime=runtime,
            candidate_delta=candidate_delta,
            decision=referee_decision,
        )
        if referee_decision.disposition == "accept":
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


def _append_northstar_proposal_to_blackboard(
    workspace: Path, rationale: str, proposed_northstar: str
) -> None:
    blackboard_dir = workspace / "blackboard"
    blackboard_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "event": "northstar_update_proposal",
        "rationale": rationale,
        "proposed_northstar": proposed_northstar,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    proposals_path = blackboard_dir / "northstar_proposals.jsonl"
    with proposals_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _state_path_for_workspace(workspace: Path) -> Path:
    return workspace / "state" / "state.json"


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


def _run_project_iterations(
    config: dict[str, Any],
    adapter: ProjectTypeAdapter,
    state_service: StateService,
    initial_state: State,
) -> dict[str, object]:
    output_path = config["output_path"]
    max_iterations = config["max_iterations"]
    artifact_id = _config_artifact_id(config)

    current_state = initial_state
    update_applied = False
    state_changed = False
    output_exported = False
    output_changed = False
    northstar_proposal_written = False
    verification_result: VerificationResult | None = None
    create_game_verification_result: VerificationResult | None = None
    stop_reason = "iteration_limit_reached"

    for _iteration in range(1, max_iterations + 1):
        try:
            game_spec = create_game(
                config,
                current_state,
                adapter=adapter,
                verification_result=create_game_verification_result,
            )
        except NoNewAtomicGameError:
            stop_reason = "create_game_no_new_atomic_game"
            break
        except NorthStarUpdateNeededError as exc:
            _debug_print_northstar_update_proposal(exc.rationale, exc.proposed_northstar)
            _append_northstar_proposal_to_blackboard(
                workspace=config["workspace"],
                rationale=exc.rationale,
                proposed_northstar=exc.proposed_northstar,
            )
            northstar_proposal_written = True
            stop_reason = "northstar_update_proposed"
            break

        delta_state = play_game(
            current_state,
            game_spec,
            adapter=adapter,
        )
        if delta_state is None:
            stop_reason = "play_game_no_delta"
            break

        before_state = state_service.load_state()
        proposal = _derive_state_update_from_delta(delta_state, adapter=adapter)
        updated_state = state_service.apply_update(proposal)

        changed_this_iteration = (
            fingerprint_state(before_state) != fingerprint_state(updated_state)
        )
        update_applied = True
        output_changed = adapter.export_state(updated_state, output_path, artifact_id)
        output_exported = output_exported or output_changed
        verification_result = _verify_export_with_adapter(
            adapter, output_path, updated_state, artifact_id
        )
        _debug_print_verification_result(verification_result)
        create_game_verification_result = verification_result
        if changed_this_iteration:
            state_changed = True
            current_state = updated_state
            continue

        stop_reason = "no_state_change"
        current_state = updated_state
        break

    return {
        "update_applied": update_applied,
        "state_changed": state_changed,
        "output_exported": output_exported,
        "output_changed": output_changed,
        "northstar_proposal_written": northstar_proposal_written,
        "verification_result": verification_result,
        "stop_reason": stop_reason,
    }


def main() -> None:
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
        help="Project type (currently supported: document, coding).",
    )
    parser.add_argument(
        "--artifact-id",
        default=None,
        help="Artifact id for project state.",
    )
    parser.add_argument(
        "--goal",
        default=None,
        help="Runtime goal text.",
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
            stop_reason = str(results["stop_reason"])
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
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
    print(f"verification_passed={verification_passed}")
    print(f"verification_exit_code={verification_exit_code}")
    print(f"verification_command={verification_command}")
    print(f"verification_cwd={verification_cwd}")
    print(f"stop_reason={stop_reason}")


if __name__ == "__main__":
    main()
