from __future__ import annotations

import argparse
import logging
from typing import Any

from baps.northstar.northstar_projection import StateView
from baps.adapters.project_adapter import (
    VerificationResult,
    _config_artifact_id,
    _config_northstar_markdown,
    _verification_result_to_dict,
)
from baps.state.state import DeltaState, GameSpec, RedFinding, RefereeDecision, State

logger = logging.getLogger(__name__)


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


def _debug_log(key: str, payload: object) -> None:
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("%s:\n%s", key, "\n".join(_format_debug_yaml_like(payload, indent=2)))


def _debug_print_read_config(args: argparse.Namespace, spec_data: dict[str, Any], config: dict[str, Any]) -> None:
    _debug_log("read_config.input", {
        "cli_args": {
            "workspace": args.workspace,
            "artifact_id": args.artifact_id,
            "goal": args.goal,
            "output": args.output,
            "max_iterations": args.max_iterations,
            "spec": args.spec,
        },
        "yaml_values": spec_data,
    })
    _debug_log("read_config.output", {
        "workspace": str(config["workspace"]),
        "artifact_id": config["artifact_id"],
        "northstar_markdown": config["northstar_markdown"],
        "goal": config["goal"],
        "output_path": str(config["output_path"]),
        "max_iterations": config["max_iterations"],
    })


def _debug_print_create_state(config: dict[str, Any], state: State) -> None:
    _debug_log("create_state.input", {
        "project_type": config["project_type"],
        "artifact_id": _config_artifact_id(config),
        "northstar_markdown": _config_northstar_markdown(config),
        "workspace": str(config["workspace"]),
        "goal": config["goal"],
        "output_path": str(config["output_path"]),
        "max_iterations": config["max_iterations"],
    })
    _debug_log("create_state.output", {"state": state.model_dump(mode="json")})


def _debug_print_create_game_input(state: State) -> None:
    _debug_log("create_game.input", {"state": state.model_dump(mode="json")})


def _debug_print_create_game_output(game_spec: GameSpec) -> None:
    _debug_log("create_game.output", {"game_spec": game_spec.model_dump(mode="json")})


def _debug_print_create_game_prompt(prompt: str) -> None:
    if logger.isEnabledFor(logging.DEBUG):
        indented = "\n".join(f"  {line}" for line in (prompt.splitlines() or [""]))
        logger.debug("create_game.prompt:\n%s", indented)


def _debug_print_play_game_input(state: State, game_spec: GameSpec) -> None:
    _debug_log("play_game.input", {
        "state": state.model_dump(mode="json"),
        "game_spec": game_spec.model_dump(mode="json"),
    })


def _debug_print_play_game_output(delta: DeltaState | None) -> None:
    _debug_log("play_game.output", {
        "current_best_delta": None if delta is None else delta.model_dump(mode="json"),
    })


def _debug_print_play_game_attempt(attempt: int) -> None:
    _debug_log("play_game.attempt", {"attempt": attempt})


def _debug_print_blue_failed_tool_call(tool_call: object) -> None:
    _debug_log("blue.failed_tool_call", {"tool_call": str(tool_call)})


def _debug_print_attempt_rejected(attempt: int, reason: str) -> None:
    _debug_log("play_game.attempt_rejected", {"attempt": attempt, "reason": reason})


def _debug_print_blue_input(
    state_view: StateView,
    game_spec: GameSpec,
    attempt_number: int,
    previous_feedback: dict[str, Any] | None,
) -> None:
    _debug_log("blue.input", {
        "game_spec": game_spec.model_dump(mode="json"),
        "state_view": state_view.model_dump(mode="json"),
        "attempt_number": attempt_number,
        "previous_feedback": previous_feedback,
    })


def _debug_print_blue_output(delta: DeltaState) -> None:
    _debug_log("blue.output", {"delta_state": delta.model_dump(mode="json")})


def _debug_print_red_input(
    state_view: StateView,
    game_spec: GameSpec,
    delta_state: DeltaState,
    verification_result: VerificationResult | None = None,
) -> None:
    _debug_log("red.input", {
        "game_spec": game_spec.model_dump(mode="json"),
        "state_view": state_view.model_dump(mode="json"),
        "delta_state": delta_state.model_dump(mode="json"),
        "verification_result": (
            None if verification_result is None
            else _verification_result_to_dict(verification_result)
        ),
    })


def _debug_print_red_output(red_finding: RedFinding) -> None:
    _debug_log("red.output", {"red_finding": red_finding.model_dump(mode="json")})


def _debug_print_referee_input(
    state_view: StateView,
    game_spec: GameSpec,
    delta_state: DeltaState,
    red_finding: RedFinding,
    verification_result: VerificationResult | None = None,
) -> None:
    _debug_log("referee.input", {
        "game_spec": game_spec.model_dump(mode="json"),
        "state_view": state_view.model_dump(mode="json"),
        "delta_state": delta_state.model_dump(mode="json"),
        "red_finding": red_finding.model_dump(mode="json"),
        "verification_result": (
            None if verification_result is None
            else _verification_result_to_dict(verification_result)
        ),
    })


def _debug_print_referee_output(referee_decision: RefereeDecision) -> None:
    _debug_log("referee.output", {"referee_decision": referee_decision.model_dump(mode="json")})


def _debug_print_northstar_update_proposal(rationale: str, proposed_northstar: str) -> None:
    _debug_log("create_game.northstar_update_proposal", {
        "rationale": rationale,
        "proposed_northstar": proposed_northstar,
    })


def _debug_print_create_game_raw_model_output(raw_text: str) -> None:
    if logger.isEnabledFor(logging.DEBUG):
        indented = "\n".join(f"  {line}" for line in (raw_text.splitlines() or [""]))
        logger.debug("create_game.raw_model_output:\n%s", indented)


def _debug_print_create_game_red_input(state_view: StateView, game_spec: GameSpec) -> None:
    _debug_log("create_game_red.input", {
        "game_spec": game_spec.model_dump(mode="json"),
        "state_view_id": state_view.id,
    })


def _debug_print_create_game_red_output(red_finding: RedFinding) -> None:
    _debug_log("create_game_red.output", {"red_finding": red_finding.model_dump(mode="json")})


def _debug_print_create_game_validation_input(game_spec: GameSpec) -> None:
    _debug_log("create_game.validation_input", {
        "objective": game_spec.objective,
        "success_condition": game_spec.success_condition,
        "target_artifact_id": game_spec.target_artifact_id,
        "allowed_delta_type": game_spec.allowed_delta_type,
    })


def _debug_print_create_game_validation_failure(message: str) -> None:
    _debug_log("create_game.validation_failure", {"message": message})


def _debug_print_verification_result(result: VerificationResult | None) -> None:
    if result is not None:
        _debug_log("verify_export.result", {"verification": _verification_result_to_dict(result)})
