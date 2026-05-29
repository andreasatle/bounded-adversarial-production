from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Callable

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
from baps.core.run_config import RunConfig
from baps.models.models import ModelClient, Role
from baps.game.attempt import (
    PlayAttemptRecord,
    apply_play_game_attempt_decision,
    run_play_game_attempt,
)
from baps.game.play import record_play_game_telemetry
from baps.game.roles import (
    PlayGameContext,
    PlayGameFeedback,
    _RED_FINDING_SCHEMA,
    _VerifyCandidateFn,
    build_play_game_fallbacks,
    initial_play_game_feedback,
    resolve_play_game_roles,
)
from baps.game.telemetry import (
    _VERIFICATION_SUMMARY_CAP,
    append_create_game_to_blackboard,
    append_integration_to_blackboard,
    append_northstar_proposal_to_blackboard,
    client_model_name,
    sanitize_game_spec_dict,
)
from baps.core.parsers import (
    NoNewGameError,
    NorthStarUpdateNeededError,
    _normalize_game_spec_with_adapter,
    _parse_create_game_output,
    _parse_red_finding_json,
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
    _render_create_game_prompt,
    _render_create_game_red_prompt,
    _render_red_prompt,
    _render_referee_prompt,
)
from baps.northstar.northstar_projection import StateView
from baps.summarizer.summarizer import SummarizationContext
from baps.state.state import (
    DecomposeSpec,
    DeltaState,
    GameSpec,
    PlayGameRuntime,
    RedFinding,
    State,
)
from baps.tools.tools import ToolExecutor

logger = logging.getLogger(__name__)

_DEFAULT_MAX_PLAY_GAME_ATTEMPTS = 3

__all__ = [
    "_VERIFICATION_SUMMARY_CAP",
    "_commit_export_with_adapter",
    "_verify_export_with_adapter",
    "create_game",
    "play_game",
]

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
    config: RunConfig,
    state: State,
    model_client: ModelClient | None = None,
    adapter: ProjectTypeAdapter | None = None,
    verification_result: VerificationResult | None = None,
    context_chain: tuple[str, ...] = (),
    depth: int = 0,
    create_game_red_client: ModelClient | None = None,
    summarization_context: SummarizationContext | None = None,
) -> GameSpec | DecomposeSpec:
    debug_event("create_game.input", {"state": state.model_dump(mode="json")})
    resolved_adapter = (
        adapter
        if adapter is not None
        else resolve_project_type_adapter(config.project_type)
    )
    state_view = resolved_adapter.build_create_game_state_view(
        state, config.to_adapter_config(), summarization_context=summarization_context
    )
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
    max_sub_gaps = config.max_sub_gaps
    max_create_game_attempts = config.max_create_game_attempts

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

    _cg_workspace = config.workspace
    _bb_result_type: str | None = None
    _bb_result: dict | None = None
    _bb_model_used = client_model_name(role.client)

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
                role, prompt, max_sub_gaps=max_sub_gaps, workspace=config.workspace,
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
                    red_finding, _ = _parse_red_finding_json(
                        red_generated, workspace=config.workspace,
                        retry_fn=red_role.generate, fallback_fn=_red_cg_fallback_fn,
                    )
                except ValueError:
                    # Unparseable Red output — accept the GameSpec as-is
                    debug_event("create_game.output", {"game_spec": game_spec.model_dump(mode="json")})
                    _bb_result_type = "game_spec"
                    _bb_result = sanitize_game_spec_dict(game_spec)
                    return game_spec
                debug_event("create_game_red.output", {"red_finding": red_finding.model_dump(mode="json")})
                if red_finding.disposition == "accept":
                    debug_event("create_game.output", {"game_spec": game_spec.model_dump(mode="json")})
                    _bb_result_type = "game_spec"
                    _bb_result = sanitize_game_spec_dict(game_spec)
                    return game_spec
                # Red rejects/revises — inject feedback and retry
                red_feedback = red_finding.model_dump(mode="json")
                continue

            debug_event("create_game.output", {"game_spec": game_spec.model_dump(mode="json")})
            _bb_result_type = "game_spec"
            _bb_result = sanitize_game_spec_dict(game_spec)
            return game_spec

        # All attempts exhausted — return best available spec
        if last_valid_game_spec is not None:
            debug_event("create_game.output", {"game_spec": last_valid_game_spec.model_dump(mode="json")})
            _bb_result_type = "game_spec"
            _bb_result = sanitize_game_spec_dict(last_valid_game_spec)
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
            append_create_game_to_blackboard(
                _cg_workspace,
                depth,
                context_chain,
                state_view.input_fingerprint,
                _bb_result_type,
                _bb_result,
                _bb_model_used,
            )


def _build_play_game_context(
    state: State,
    game_spec: GameSpec,
    adapter: ProjectTypeAdapter | None,
    model_client: ModelClient | None,
    red_model_client: ModelClient | None,
    referee_model_client: ModelClient | None,
    executor: ToolExecutor | None,
    sandbox_mode: str,
    config: RunConfig | None,
    depth: int,
    max_attempts: int,
    debug_event_fn: Callable[[str, dict[str, Any]], None],
    render_red_prompt_fn: Callable[[StateView, GameSpec, DeltaState, VerificationResult | None, str], str],
    render_referee_prompt_fn: Callable[[StateView, GameSpec, DeltaState, RedFinding, VerificationResult | None, str], str],
    verify_candidate_fn: _VerifyCandidateFn,
) -> PlayGameContext:
    resolved_adapter = (
        adapter
        if adapter is not None
        else resolve_adapter_for_allowed_delta_type(game_spec.allowed_delta_type)
    )
    debug_event_fn("play_game.input", {
        "state": state.model_dump(mode="json"),
        "game_spec": game_spec.model_dump(mode="json"),
    })
    state_view = resolved_adapter.build_state_view(state, game_spec)
    game_id = str(uuid.uuid4())
    blue_role, red_role, referee_role = resolve_play_game_roles(
        resolved_adapter,
        config,
        model_client,
        red_model_client,
        referee_model_client,
        build_client_for_role_fn=_build_client_for_role,
        build_role_client_fn=_build_role_client,
    )
    workspace, red_fallback_fn, referee_fallback_fn = build_play_game_fallbacks(
        config,
        red_model_client,
        referee_model_client,
        build_fallback_chain_for_role_fn=_build_fallback_chain_for_role,
    )
    return PlayGameContext(
        resolved_adapter=resolved_adapter,
        state=state,
        game_spec=game_spec,
        state_view=state_view,
        game_id=game_id,
        workspace=workspace,
        sandbox_mode=sandbox_mode,
        executor=executor,
        blue_role=blue_role,
        red_role=red_role,
        referee_role=referee_role,
        red_fallback_fn=red_fallback_fn,
        referee_fallback_fn=referee_fallback_fn,
        depth=depth,
        max_attempts=max_attempts,
        debug_event_fn=debug_event_fn,
        render_red_prompt_fn=render_red_prompt_fn,
        render_referee_prompt_fn=render_referee_prompt_fn,
        verify_candidate_fn=verify_candidate_fn,
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
    config: RunConfig | None = None,
    depth: int = 0,
) -> DeltaState | None:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    ctx = _build_play_game_context(
        state=state,
        game_spec=game_spec,
        adapter=adapter,
        model_client=model_client,
        red_model_client=red_model_client,
        referee_model_client=referee_model_client,
        executor=executor,
        sandbox_mode=sandbox_mode,
        config=config,
        depth=depth,
        max_attempts=max_attempts,
        debug_event_fn=debug_event,
        render_red_prompt_fn=_render_red_prompt,
        render_referee_prompt_fn=_render_referee_prompt,
        verify_candidate_fn=_verify_candidate_with_adapter,
    )
    runtime = PlayGameRuntime()
    previous_feedback: PlayGameFeedback | None = initial_play_game_feedback(verification_result)
    attempt_records: list[PlayAttemptRecord] = []
    last_candidate_result: VerificationResult | None = None

    for attempt in range(1, max_attempts + 1):
        debug_event("play_game.attempt", {"attempt": attempt})
        attempt_rec, candidate_delta, red_finding, referee_decision, updated_feedback = run_play_game_attempt(
            ctx=ctx,
            attempt=attempt,
            previous_feedback=previous_feedback,
            verification_result=verification_result,
        )
        if candidate_delta is None:
            previous_feedback = updated_feedback
            attempt_records.append(attempt_rec)
            continue
        runtime, previous_feedback, candidate_result, stop_attempts = apply_play_game_attempt_decision(
            ctx=ctx,
            runtime=runtime,
            attempt=attempt,
            attempt_rec=attempt_rec,
            candidate_delta=candidate_delta,
            red_finding=red_finding,
            referee_decision=referee_decision,
        )
        if candidate_result is not None:
            last_candidate_result = candidate_result
        attempt_records.append(attempt_rec)
        if stop_attempts:
            break

    record_play_game_telemetry(
        ctx=ctx,
        runtime=runtime,
        attempt_records=attempt_records,
        last_candidate_result=last_candidate_result,
    )
    return runtime.integration_eligible_delta
