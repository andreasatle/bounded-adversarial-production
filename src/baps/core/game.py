from __future__ import annotations

import datetime
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from baps.core.clients import (
    SpecRole,
    _build_client_for_role,
    _build_fallback_chain_for_role,
    _build_role_client,
    _make_fallback_chain_fn,
    _resolve_backend_model,
)
from baps.core.debug import (
    _debug_print_create_game_prompt,
    _debug_print_create_game_raw_model_output,
    debug_event,
)
from baps.models.model_output import BlackboardEvent
from baps.models.models import ModelClient, Role, ToolCallRecord
from baps.core.parsers import (
    NoNewGameError,
    NorthStarUpdateNeededError,
    _normalize_game_spec_with_adapter,
    _parse_create_game_output,
    _parse_red_finding_json,
    _parse_referee_decision_json,
)
from baps.adapters.project_adapter import (
    ProjectTypeAdapter,
    VerificationResult,
    _config_artifact_id,
    resolve_adapter_for_allowed_delta_type,
    resolve_project_type_adapter,
    sanitize_model_string,
)
from baps.core.prompts import (
    _get_research_tools,
    _render_create_game_prompt,
    _render_create_game_red_prompt,
    _render_red_prompt,
    _render_red_prompt_supplement_with_adapter,
    _render_referee_prompt,
    _render_referee_prompt_supplement_with_adapter,
    _render_research_prompt,
    _render_tool_session_block,
)
from baps.state.state import (
    DecomposeSpec,
    DeltaState,
    GameSpec,
    PlayGameRuntime,
    State,
    StateUpdateProposal,
    apply_referee_decision_to_runtime,
)
from baps.tools.tools import ToolExecutor

logger = logging.getLogger(__name__)

_DEFAULT_MAX_PLAY_GAME_ATTEMPTS = 3
_BLACKBOARD_DIR = "blackboard"
_NORTHSTAR_PROPOSALS_FILE = "northstar_proposals.jsonl"
_GAMES_FILE = "games.jsonl"
_VERIFICATION_SUMMARY_CAP = 500

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
        "max_words": {"type": ["integer", "null"]},
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


def _sanitize_feedback_dict(d: dict) -> dict:
    result = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = sanitize_model_string(v)
        elif isinstance(v, list):
            result[k] = [sanitize_model_string(i) if isinstance(i, str) else i for i in v]
        elif isinstance(v, dict):
            result[k] = _sanitize_feedback_dict(v)
        else:
            result[k] = v
    return result


def _derive_state_update_from_delta(
    delta_state: DeltaState, adapter: ProjectTypeAdapter
) -> StateUpdateProposal:
    """Map DeltaState to StateUpdateProposal for non-runtime proposal workflows.

    Canonical runtime integration in orchestration applies integration-eligible
    DeltaState directly through StateService.apply_delta.
    """
    return adapter.delta_to_state_update(delta_state)


def _verify_export_with_adapter(
    adapter: ProjectTypeAdapter,
    output_path: Path,
    state: State,
    artifact_id: str,
    sandbox_mode: str = "docker",
) -> VerificationResult | None:
    verifier = getattr(adapter, "verify_export", None)
    if verifier is None:
        return None
    return verifier(output_path, state, artifact_id, sandbox_mode=sandbox_mode)


def _verify_candidate_with_adapter(
    adapter: ProjectTypeAdapter,
    delta_state: DeltaState,
    state: State,
    artifact_id: str,
    sandbox_mode: str = "docker",
) -> VerificationResult | None:
    verifier = getattr(adapter, "verify_candidate", None)
    if verifier is None:
        return None
    return verifier(delta_state, state, artifact_id, sandbox_mode=sandbox_mode)


def _commit_export_with_adapter(
    adapter: ProjectTypeAdapter, output_path: Path, game_spec: GameSpec
) -> bool:
    committer = getattr(adapter, "commit_export", None)
    if committer is None:
        return False
    committed = committer(output_path, game_spec)
    if committed:
        logger.debug("commit_export: committed export to git at %s", output_path)
    return committed


def _append_northstar_proposal_to_blackboard(
    workspace: Path, rationale: str, proposed_northstar: str
) -> None:
    blackboard_dir = workspace / _BLACKBOARD_DIR
    blackboard_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "event": BlackboardEvent.NORTHSTAR_UPDATE_PROPOSAL,
        "rationale": sanitize_model_string(rationale),
        "proposed_northstar": sanitize_model_string(proposed_northstar),
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    proposals_path = blackboard_dir / _NORTHSTAR_PROPOSALS_FILE
    with proposals_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _summarize_verification_result(result: VerificationResult | None) -> dict | None:
    if result is None:
        return None
    return {
        "passed": result.passed,
        "exit_code": result.exit_code,
        "stdout_summary": result.stdout[:_VERIFICATION_SUMMARY_CAP] if result.stdout else None,
        "stderr_summary": result.stderr[:_VERIFICATION_SUMMARY_CAP] if result.stderr else None,
    }


def _sanitize_game_spec_dict(game_spec: GameSpec) -> dict:
    return {
        "objective": sanitize_model_string(game_spec.objective),
        "target_artifact_id": game_spec.target_artifact_id,
        "allowed_delta_type": game_spec.allowed_delta_type,
        "success_condition": sanitize_model_string(game_spec.success_condition),
    }


def _append_game_to_blackboard(
    workspace: Path,
    game_id: str,
    depth: int,
    game_spec: GameSpec,
    attempt_records: list[dict],
    final_disposition: str,
    verification_result: VerificationResult | None,
    current_best_delta: DeltaState | None,
    integration_eligible_delta: DeltaState | None,
) -> None:
    blackboard_dir = workspace / _BLACKBOARD_DIR
    blackboard_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "event": BlackboardEvent.PLAY_GAME,
        "game_id": game_id,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "depth": depth,
        "context_chain": list(game_spec.context_chain),
        "game_spec": _sanitize_game_spec_dict(game_spec),
        "attempts": attempt_records,
        "final_disposition": final_disposition,
        "verification_result": _summarize_verification_result(verification_result),
        "current_best_delta": (
            None
            if current_best_delta is None
            else _sanitize_feedback_dict(current_best_delta.model_dump(mode="json"))
        ),
        "integration_eligible_delta": (
            None
            if integration_eligible_delta is None
            else _sanitize_feedback_dict(integration_eligible_delta.model_dump(mode="json"))
        ),
    }
    games_path = blackboard_dir / _GAMES_FILE
    with games_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _client_model_name(client: ModelClient) -> str:
    return getattr(client, "model", type(client).__name__)


def _append_create_game_to_blackboard(
    workspace: Path,
    depth: int,
    context_chain: tuple[str, ...],
    state_view_fingerprint: str,
    result_type: str,
    result: dict | None,
    model_used: str,
) -> None:
    blackboard_dir = workspace / _BLACKBOARD_DIR
    blackboard_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "event": BlackboardEvent.CREATE_GAME,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "depth": depth,
        "context_chain": list(context_chain),
        "state_view_fingerprint": state_view_fingerprint,
        "result_type": result_type,
        "result": result,
        "model_used": model_used,
    }
    games_path = blackboard_dir / _GAMES_FILE
    with games_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _append_integration_to_blackboard(
    workspace: Path,
    depth: int,
    proposal_id: str,
    proposal_summary: str,
    state_changed: bool,
    delta_type: str,
) -> None:
    blackboard_dir = workspace / _BLACKBOARD_DIR
    blackboard_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "event": BlackboardEvent.INTEGRATION,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "depth": depth,
        "proposal_id": proposal_id,
        "proposal_summary": sanitize_model_string(proposal_summary),
        "state_changed": state_changed,
        "delta_type": delta_type,
    }
    games_path = blackboard_dir / _GAMES_FILE
    with games_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _ensure_target_artifact_exists(state: State, artifact_id: str) -> None:
    _ = next((a for a in state.artifacts if a.id == artifact_id), None)
    if _ is None:
        raise ValueError(f"create_game target artifact not found in state: {artifact_id}")


def _generate_create_game_with_json_retry(
    role: Role,
    prompt: str,
    max_sub_gaps: int,
    workspace: Path | None,
    fallback_fn: Any = None,
) -> GameSpec | DecomposeSpec:
    generated = role.generate(prompt)
    _debug_print_create_game_raw_model_output(generated)
    return _parse_create_game_output(
        generated,
        max_sub_gaps=max_sub_gaps,
        workspace=workspace,
        retry_fn=role.generate,
        fallback_fn=fallback_fn,
    )


def _validate_game_spec(game_spec: GameSpec) -> None:
    debug_event("create_game.validation_input", {
        "objective": game_spec.objective,
        "success_condition": game_spec.success_condition,
        "target_artifact_id": game_spec.target_artifact_id,
        "allowed_delta_type": game_spec.allowed_delta_type,
    })


def create_game(
    config: dict[str, Any],
    state: State,
    model_client: ModelClient | None = None,
    adapter: ProjectTypeAdapter | None = None,
    verification_result: VerificationResult | None = None,
    context_chain: tuple[str, ...] = (),
    depth: int = 0,
    create_game_red_client: ModelClient | None = None,
    max_create_game_attempts: int = 2,
) -> GameSpec | DecomposeSpec:
    debug_event("create_game.input", {"state": state.model_dump(mode="json")})
    resolved_adapter = (
        adapter
        if adapter is not None
        else resolve_project_type_adapter(config["project_type"])
    )
    state_view = resolved_adapter.build_create_game_state_view(state, config)
    use_planner = model_client is None
    if use_planner:
        role_name_for_client = SpecRole.DECOMPOSE if depth > 0 else SpecRole.CREATE_GAME
        client = _build_client_for_role(role_name_for_client, config)
    else:
        client = model_client
    role_name = SpecRole.DECOMPOSE if depth > 0 else SpecRole.CREATE_GAME
    role = Role(role_name, client, _CREATE_GAME_SCHEMA, constrained=False)
    red_role = (
        Role(SpecRole.CREATE_GAME_RED, create_game_red_client, _RED_FINDING_SCHEMA, constrained=True)
        if create_game_red_client is not None
        else None
    )

    red_feedback: dict[str, Any] | None = None
    last_valid_game_spec: GameSpec | None = None
    max_sub_gaps = int(config.get("max_sub_gaps", 5))

    # Build fallback chains once — they don't change across attempts.
    try:
        _cg_primary_model = _resolve_backend_model(role_name, config)[1] if use_planner else "(provided)"
    except ValueError:
        _cg_primary_model = "(unknown)"
    _create_game_fallback_fn = _make_fallback_chain_fn(
        role_name, _cg_primary_model, _build_fallback_chain_for_role(role_name, config)
    )
    if red_role is not None:
        try:
            _red_cg_primary_model = _resolve_backend_model(SpecRole.CREATE_GAME_RED, config)[1]
        except ValueError:
            _red_cg_primary_model = "(unknown)"
        _red_cg_fallback_fn = _make_fallback_chain_fn(
            SpecRole.CREATE_GAME_RED, _red_cg_primary_model, _build_fallback_chain_for_role(SpecRole.CREATE_GAME_RED, config)
        )
    else:
        _red_cg_fallback_fn = None

    _cg_workspace = config.get("workspace")
    _bb_result_type: str | None = None
    _bb_result: dict | None = None
    _bb_model_used = _client_model_name(role.client)

    try:
        for attempt in range(1, max_create_game_attempts + 1):
            prompt = _render_create_game_prompt(
                config=config,
                state=state,
                state_view=state_view,
                verification_result=verification_result,
                adapter=resolved_adapter,
                context_chain=context_chain,
                create_game_red_feedback=red_feedback,
            )
            _debug_print_create_game_prompt(prompt)
            result = _generate_create_game_with_json_retry(
                role, prompt, max_sub_gaps=max_sub_gaps, workspace=config["workspace"],
                fallback_fn=_create_game_fallback_fn,
            )

            if isinstance(result, DecomposeSpec):
                debug_event("create_game.output", {"game_spec": result.model_dump(mode="json")})
                _bb_result_type = "decompose_spec"
                _bb_result = {
                    "rationale": sanitize_model_string(result.rationale),
                    "sub_gaps": [
                        {"description": sanitize_model_string(sg.description)}
                        for sg in result.sub_gaps
                    ],
                }
                return result

            game_spec = _normalize_game_spec_with_adapter(resolved_adapter, result, state, config)
            try:
                _validate_game_spec(game_spec)
            except ValueError as exc:
                debug_event("create_game.validation_failure", {"message": str(exc)})
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
            last_valid_game_spec = game_spec

            # Red challenge — only when a Red client is wired and this is not the final attempt
            if red_role is not None and attempt < max_create_game_attempts:
                red_prompt = _render_create_game_red_prompt(state_view, game_spec, config)
                debug_event("create_game_red.input", {
                    "game_spec": game_spec.model_dump(mode="json"),
                    "state_view_id": state_view.id,
                })
                red_generated = red_role.generate(red_prompt)
                try:
                    red_finding = _parse_red_finding_json(
                        red_generated, workspace=config.get("workspace"),
                        retry_fn=red_role.generate, fallback_fn=_red_cg_fallback_fn,
                    )
                except ValueError:
                    # Unparseable Red output — accept the GameSpec as-is
                    debug_event("create_game.output", {"game_spec": game_spec.model_dump(mode="json")})
                    _bb_result_type = "game_spec"
                    _bb_result = _sanitize_game_spec_dict(game_spec)
                    return game_spec
                debug_event("create_game_red.output", {"red_finding": red_finding.model_dump(mode="json")})
                if red_finding.disposition == "accept":
                    debug_event("create_game.output", {"game_spec": game_spec.model_dump(mode="json")})
                    _bb_result_type = "game_spec"
                    _bb_result = _sanitize_game_spec_dict(game_spec)
                    return game_spec
                # Red rejects/revises — inject feedback and retry
                red_feedback = red_finding.model_dump(mode="json")
                continue

            debug_event("create_game.output", {"game_spec": game_spec.model_dump(mode="json")})
            _bb_result_type = "game_spec"
            _bb_result = _sanitize_game_spec_dict(game_spec)
            return game_spec

        # All attempts exhausted — return best available spec
        if last_valid_game_spec is not None:
            debug_event("create_game.output", {"game_spec": last_valid_game_spec.model_dump(mode="json")})
            _bb_result_type = "game_spec"
            _bb_result = _sanitize_game_spec_dict(last_valid_game_spec)
            return last_valid_game_spec
        raise ValueError("create_game failed to produce a valid GameSpec after all attempts")

    except NoNewGameError:
        _bb_result_type = "no_new_game"
        raise
    except NorthStarUpdateNeededError:
        _bb_result_type = "northstar_update_needed"
        raise
    finally:
        if _cg_workspace is not None and _bb_result_type is not None:
            _append_create_game_to_blackboard(
                _cg_workspace,
                depth,
                context_chain,
                state_view.input_fingerprint,
                _bb_result_type,
                _bb_result,
                _bb_model_used,
            )


def _initial_play_game_feedback(
    verification_result: VerificationResult | None,
) -> dict[str, Any] | None:
    if verification_result is None:
        return None
    return {
        "prior_export_verification": {
            "exit_code": verification_result.exit_code,
            "passed": verification_result.passed,
            "stdout": verification_result.stdout,
            "stderr": verification_result.stderr,
        }
    }


def _resolve_play_game_roles(
    resolved_adapter: ProjectTypeAdapter,
    config: dict[str, Any] | None,
    model_client: ModelClient | None,
    red_model_client: ModelClient | None,
    referee_model_client: ModelClient | None,
) -> tuple[Role, Role, Role]:
    def _get_client(explicit: ModelClient | None, role: str) -> ModelClient:
        if explicit is not None:
            return explicit
        if config is not None:
            return _build_client_for_role(role, config)
        return _build_role_client(role)

    blue_role = Role(
        SpecRole.BLUE,
        _get_client(model_client, SpecRole.BLUE),
        resolved_adapter.build_blue_output_format(),
        constrained=False,
    )
    red_role = Role(
        SpecRole.RED,
        _get_client(red_model_client, SpecRole.RED),
        _RED_FINDING_SCHEMA,
        constrained=True,
    )
    referee_role = Role(
        SpecRole.REFEREE,
        _get_client(referee_model_client, SpecRole.REFEREE),
        _REFEREE_DECISION_SCHEMA,
        constrained=True,
    )
    return blue_role, red_role, referee_role


def _build_play_game_fallbacks(
    config: dict[str, Any] | None,
    red_model_client: ModelClient | None,
    referee_model_client: ModelClient | None,
) -> tuple[Path | None, Any, Any]:
    workspace = config.get("workspace") if config else None
    if config is None:
        return workspace, None, None
    try:
        red_primary = (
            _resolve_backend_model(SpecRole.RED, config)[1]
            if red_model_client is None
            else "(provided)"
        )
    except ValueError:
        red_primary = "(unknown)"
    try:
        referee_primary = (
            _resolve_backend_model(SpecRole.REFEREE, config)[1]
            if referee_model_client is None
            else "(provided)"
        )
    except ValueError:
        referee_primary = "(unknown)"
    red_fallback_fn = _make_fallback_chain_fn(
        SpecRole.RED, red_primary, _build_fallback_chain_for_role(SpecRole.RED, config)
    )
    referee_fallback_fn = _make_fallback_chain_fn(
        SpecRole.REFEREE,
        referee_primary,
        _build_fallback_chain_for_role(SpecRole.REFEREE, config),
    )
    return workspace, red_fallback_fn, referee_fallback_fn


def _run_play_game_attempt(
    *,
    attempt: int,
    resolved_adapter: ProjectTypeAdapter,
    state_view: Any,
    game_spec: GameSpec,
    verification_result: VerificationResult | None,
    previous_feedback: dict[str, Any] | None,
    executor: ToolExecutor | None,
    blue_role: Role,
    red_role: Role,
    referee_role: Role,
    workspace: Path | None,
    red_fallback_fn: Any,
    referee_fallback_fn: Any,
) -> tuple[dict, DeltaState | None, Any | None, Any | None, dict[str, Any] | None]:
    attempt_rec: dict = {
        "attempt_number": attempt,
        "blue_delta": None,
        "red_finding": None,
        "referee_decision": None,
        "candidate_verification": None,
    }

    blue_session: list[ToolCallRecord] = []
    blue_summary = ""
    if executor is not None:
        blue_research_tools = _get_research_tools(resolved_adapter, SpecRole.BLUE)
        if blue_research_tools:
            research_prompt = _render_research_prompt(SpecRole.BLUE, state_view, game_spec, [])
            blue_summary, blue_session = blue_role.generate_agentic(
                research_prompt, blue_research_tools, executor
            )

    debug_event("blue.input", {
        "game_spec": game_spec.model_dump(mode="json"),
        "state_view": state_view.model_dump(mode="json"),
        "attempt_number": attempt,
        "previous_feedback": previous_feedback,
    })
    blue_prompt = resolved_adapter.render_blue_prompt(
        state_view, game_spec, attempt, previous_feedback
    )
    if blue_session or blue_summary:
        blue_prompt = _render_tool_session_block([(SpecRole.BLUE, blue_session, blue_summary)]) + "\n\n" + blue_prompt
    blue_tools = resolved_adapter.build_blue_tools()
    blue_tool_call = None
    if blue_tools:
        try:
            blue_tool_call = blue_role.generate_with_tools(blue_prompt, blue_tools)
        except ValueError:
            pass
    if blue_tool_call is not None:
        try:
            candidate_delta = resolved_adapter.tool_call_to_delta(blue_tool_call)
        except ValueError as exc:
            debug_event("blue.failed_tool_call", {"tool_call": str(blue_tool_call)})
            reason = f"blue output failed DeltaState validation: {exc}"
            debug_event("play_game.attempt_rejected", {"attempt": attempt, "reason": reason})
            updated_feedback = {
                "attempt_rejection": {
                    "stage": SpecRole.BLUE,
                    "reason": reason,
                    "validation_error": str(exc),
                }
            }
            return attempt_rec, None, None, None, updated_feedback
    else:
        blue_generated = blue_role.generate(blue_prompt)
        try:
            candidate_delta = resolved_adapter.parse_blue_delta(blue_generated)
        except ValueError as exc:
            reason = f"blue output failed DeltaState validation: {exc}"
            debug_event("play_game.attempt_rejected", {"attempt": attempt, "reason": reason})
            updated_feedback = {
                "attempt_rejection": {
                    "stage": SpecRole.BLUE,
                    "reason": reason,
                    "validation_error": str(exc),
                }
            }
            return attempt_rec, None, None, None, updated_feedback
    debug_event("blue.output", {"delta_state": candidate_delta.model_dump(mode="json")})
    attempt_rec["blue_delta"] = _sanitize_feedback_dict(candidate_delta.model_dump(mode="json"))

    red_session: list[ToolCallRecord] = []
    red_summary = ""
    if executor is not None:
        red_research_tools = _get_research_tools(resolved_adapter, SpecRole.RED)
        if red_research_tools:
            prior = [(SpecRole.BLUE, blue_session, blue_summary)] if blue_session or blue_summary else []
            research_prompt = _render_research_prompt(SpecRole.RED, state_view, game_spec, prior)
            red_summary, red_session = red_role.generate_agentic(
                research_prompt, red_research_tools, executor
            )

    if verification_result is None:
        debug_event("red.input", {
            "game_spec": game_spec.model_dump(mode="json"),
            "state_view": state_view.model_dump(mode="json"),
            "delta_state": candidate_delta.model_dump(mode="json"),
            "verification_result": None,
        })
    else:
        debug_event("red.input", {
            "game_spec": game_spec.model_dump(mode="json"),
            "state_view": state_view.model_dump(mode="json"),
            "delta_state": candidate_delta.model_dump(mode="json"),
            "verification_result": {
                "command": verification_result.command,
                "cwd": verification_result.cwd,
                "exit_code": verification_result.exit_code,
                "stdout": verification_result.stdout,
                "stderr": verification_result.stderr,
                "passed": verification_result.passed,
            },
        })
    red_supplement = _render_red_prompt_supplement_with_adapter(
        resolved_adapter,
        state_view,
        game_spec,
        candidate_delta,
        verification_result,
    )
    tool_context = _render_tool_session_block([
        s for s in [(SpecRole.BLUE, blue_session, blue_summary), (SpecRole.RED, red_session, red_summary)]
        if s[1] or s[2]
    ])
    red_supplement_with_tools = (
        (tool_context + "\n\nTool-use enforcement: treat any claim referencing external "
            "information not supported by the tool call log above as unverified. "
            "If Blue claims to have verified something externally but has no tool calls to show it, "
            "flag that as a finding.\n\n")
        if tool_context else ""
    ) + red_supplement
    red_prompt = _render_red_prompt(
        state_view,
        game_spec,
        candidate_delta,
        verification_result,
        red_supplement_with_tools,
    )
    red_generated = red_role.generate(red_prompt)
    red_finding = _parse_red_finding_json(
        red_generated, workspace=workspace,
        retry_fn=red_role.generate, fallback_fn=red_fallback_fn,
    )
    debug_event("red.output", {"red_finding": red_finding.model_dump(mode="json")})
    attempt_rec["red_finding"] = _sanitize_feedback_dict(red_finding.model_dump(mode="json"))

    referee_session: list[ToolCallRecord] = []
    referee_summary = ""
    if executor is not None:
        referee_research_tools = _get_research_tools(resolved_adapter, SpecRole.REFEREE)
        if referee_research_tools:
            prior = [s for s in [
                (SpecRole.BLUE, blue_session, blue_summary),
                (SpecRole.RED, red_session, red_summary),
            ] if s[1] or s[2]]
            research_prompt = _render_research_prompt(SpecRole.REFEREE, state_view, game_spec, prior)
            referee_summary, referee_session = referee_role.generate_agentic(
                research_prompt, referee_research_tools, executor
            )

    if verification_result is None:
        debug_event("referee.input", {
            "game_spec": game_spec.model_dump(mode="json"),
            "state_view": state_view.model_dump(mode="json"),
            "delta_state": candidate_delta.model_dump(mode="json"),
            "red_finding": red_finding.model_dump(mode="json"),
            "verification_result": None,
        })
    else:
        debug_event("referee.input", {
            "game_spec": game_spec.model_dump(mode="json"),
            "state_view": state_view.model_dump(mode="json"),
            "delta_state": candidate_delta.model_dump(mode="json"),
            "red_finding": red_finding.model_dump(mode="json"),
            "verification_result": {
                "command": verification_result.command,
                "cwd": verification_result.cwd,
                "exit_code": verification_result.exit_code,
                "stdout": verification_result.stdout,
                "stderr": verification_result.stderr,
                "passed": verification_result.passed,
            },
        })
    referee_supplement = _render_referee_prompt_supplement_with_adapter(
        resolved_adapter,
        state_view,
        game_spec,
        candidate_delta,
        verification_result,
    )
    all_sessions = [s for s in [
        (SpecRole.BLUE, blue_session, blue_summary),
        (SpecRole.RED, red_session, red_summary),
        (SpecRole.REFEREE, referee_session, referee_summary),
    ] if s[1] or s[2]]
    referee_tool_context = _render_tool_session_block(all_sessions)
    referee_supplement_with_tools = (
        (referee_tool_context + "\n\nTool-use enforcement: any claim referencing external "
            "information not supported by the tool call logs above must be treated as unverified "
            "and rejected.\n\n")
        if referee_tool_context else ""
    ) + referee_supplement
    referee_prompt = _render_referee_prompt(
        state_view,
        game_spec,
        candidate_delta,
        red_finding,
        verification_result,
        referee_supplement_with_tools,
    )
    referee_generated = referee_role.generate(referee_prompt)
    referee_decision = _parse_referee_decision_json(
        referee_generated, workspace=workspace,
        retry_fn=referee_role.generate, fallback_fn=referee_fallback_fn,
    )
    debug_event("referee.output", {"referee_decision": referee_decision.model_dump(mode="json")})
    attempt_rec["referee_decision"] = _sanitize_feedback_dict(referee_decision.model_dump(mode="json"))
    return attempt_rec, candidate_delta, red_finding, referee_decision, previous_feedback


def _apply_play_game_attempt_decision(
    *,
    runtime: PlayGameRuntime,
    attempt: int,
    max_attempts: int,
    attempt_rec: dict,
    candidate_delta: DeltaState,
    red_finding: Any,
    referee_decision: Any,
    resolved_adapter: ProjectTypeAdapter,
    state: State,
    game_spec: GameSpec,
    sandbox_mode: str,
) -> tuple[PlayGameRuntime, dict[str, Any] | None, VerificationResult | None, bool]:
    runtime = apply_referee_decision_to_runtime(
        runtime=runtime,
        candidate_delta=candidate_delta,
        decision=referee_decision,
    )
    if referee_decision.disposition == "accept":
        candidate_result = _verify_candidate_with_adapter(
            resolved_adapter, candidate_delta, state, game_spec.target_artifact_id,
            sandbox_mode=sandbox_mode,
        )
        attempt_rec["candidate_verification"] = _summarize_verification_result(candidate_result)
        if (
            candidate_result is not None
            and not candidate_result.passed
            and attempt < max_attempts
        ):
            previous_feedback = {
                "red_finding": _sanitize_feedback_dict(red_finding.model_dump(mode="json")),
                "referee_decision": _sanitize_feedback_dict(referee_decision.model_dump(mode="json")),
                "candidate_verification": {
                    "exit_code": candidate_result.exit_code,
                    "passed": False,
                    "stdout": candidate_result.stdout,
                    "stderr": candidate_result.stderr,
                },
            }
            return runtime, previous_feedback, candidate_result, False
        return runtime, None, candidate_result, True
    previous_feedback = {
        "red_finding": _sanitize_feedback_dict(red_finding.model_dump(mode="json")),
        "referee_decision": _sanitize_feedback_dict(referee_decision.model_dump(mode="json")),
    }
    return runtime, previous_feedback, None, False


def _record_play_game_telemetry(
    *,
    workspace: Path | None,
    game_id: str,
    depth: int,
    game_spec: GameSpec,
    attempt_records: list[dict],
    last_candidate_result: VerificationResult | None,
    runtime: PlayGameRuntime,
) -> None:
    debug_event("play_game.output", {
        "current_best_delta": (
            None
            if runtime.current_best_delta is None
            else runtime.current_best_delta.model_dump(mode="json")
        ),
        "integration_eligible_delta": (
            None
            if runtime.integration_eligible_delta is None
            else runtime.integration_eligible_delta.model_dump(mode="json")
        ),
    })
    if workspace is None:
        return
    final_disposition = (
        "accepted" if runtime.integration_eligible_delta is not None
        else "rejected" if any(r["blue_delta"] is not None for r in attempt_records)
        else "no_delta"
    )
    _append_game_to_blackboard(
        workspace=workspace,
        game_id=game_id,
        depth=depth,
        game_spec=game_spec,
        attempt_records=attempt_records,
        final_disposition=final_disposition,
        verification_result=last_candidate_result,
        current_best_delta=runtime.current_best_delta,
        integration_eligible_delta=runtime.integration_eligible_delta,
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
    executor: ToolExecutor | None = None,
    sandbox_mode: str = "docker",
    config: dict[str, Any] | None = None,
    depth: int = 0,
) -> DeltaState | None:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    resolved_adapter = (
        adapter
        if adapter is not None
        else resolve_adapter_for_allowed_delta_type(game_spec.allowed_delta_type)
    )
    debug_event("play_game.input", {
        "state": state.model_dump(mode="json"),
        "game_spec": game_spec.model_dump(mode="json"),
    })
    state_view = resolved_adapter.build_state_view(state, game_spec)
    runtime = PlayGameRuntime()
    previous_feedback = _initial_play_game_feedback(verification_result)
    attempt_records: list[dict] = []
    last_candidate_result: VerificationResult | None = None
    game_id = str(uuid.uuid4())
    blue_role, red_role, referee_role = _resolve_play_game_roles(
        resolved_adapter,
        config,
        model_client,
        red_model_client,
        referee_model_client,
    )
    workspace, red_fallback_fn, referee_fallback_fn = _build_play_game_fallbacks(
        config,
        red_model_client,
        referee_model_client,
    )

    for attempt in range(1, max_attempts + 1):
        debug_event("play_game.attempt", {"attempt": attempt})
        attempt_rec, candidate_delta, red_finding, referee_decision, updated_feedback = _run_play_game_attempt(
            attempt=attempt,
            resolved_adapter=resolved_adapter,
            state_view=state_view,
            game_spec=game_spec,
            verification_result=verification_result,
            previous_feedback=previous_feedback,
            executor=executor,
            blue_role=blue_role,
            red_role=red_role,
            referee_role=referee_role,
            workspace=workspace,
            red_fallback_fn=red_fallback_fn,
            referee_fallback_fn=referee_fallback_fn,
        )
        if candidate_delta is None:
            previous_feedback = updated_feedback
            attempt_records.append(attempt_rec)
            continue
        runtime, previous_feedback, candidate_result, stop_attempts = _apply_play_game_attempt_decision(
            runtime=runtime,
            attempt=attempt,
            max_attempts=max_attempts,
            attempt_rec=attempt_rec,
            candidate_delta=candidate_delta,
            red_finding=red_finding,
            referee_decision=referee_decision,
            resolved_adapter=resolved_adapter,
            state=state,
            game_spec=game_spec,
            sandbox_mode=sandbox_mode,
        )
        if candidate_result is not None:
            last_candidate_result = candidate_result
        attempt_records.append(attempt_rec)
        if stop_attempts:
            break

    _record_play_game_telemetry(
        workspace=workspace,
        game_id=game_id,
        depth=depth,
        game_spec=game_spec,
        attempt_records=attempt_records,
        last_candidate_result=last_candidate_result,
        runtime=runtime,
    )
    return runtime.integration_eligible_delta
