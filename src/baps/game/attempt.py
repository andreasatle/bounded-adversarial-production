from __future__ import annotations

from typing import Any

from baps.core.clients import SpecRole
from baps.core.parsers import _parse_red_finding_json, _parse_referee_decision_json
from baps.core.prompts import (
    _get_research_tools,
    _render_red_prompt_supplement_with_adapter,
    _render_referee_prompt_supplement_with_adapter,
    _render_research_prompt,
    _render_tool_session_block,
)
from baps.adapters.project_adapter import ProjectTypeAdapter, VerificationResult
from baps.models.models import Role, ToolCallRecord
from baps.state.state import DeltaState, GameSpec, PlayGameRuntime, State, apply_referee_decision_to_runtime
from baps.tools.tools import ToolExecutor

from baps.game.telemetry import _sanitize_feedback_dict, _summarize_verification_result


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
    workspace: Any,
    red_fallback_fn: Any,
    referee_fallback_fn: Any,
    debug_event_fn: Any,
    render_red_prompt_fn: Any,
    render_referee_prompt_fn: Any,
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

    debug_event_fn("blue.input", {
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
            debug_event_fn("blue.failed_tool_call", {"tool_call": str(blue_tool_call)})
            reason = f"blue output failed DeltaState validation: {exc}"
            debug_event_fn("play_game.attempt_rejected", {"attempt": attempt, "reason": reason})
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
            debug_event_fn("play_game.attempt_rejected", {"attempt": attempt, "reason": reason})
            updated_feedback = {
                "attempt_rejection": {
                    "stage": SpecRole.BLUE,
                    "reason": reason,
                    "validation_error": str(exc),
                }
            }
            return attempt_rec, None, None, None, updated_feedback
    debug_event_fn("blue.output", {"delta_state": candidate_delta.model_dump(mode="json")})
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
        debug_event_fn("red.input", {
            "game_spec": game_spec.model_dump(mode="json"),
            "state_view": state_view.model_dump(mode="json"),
            "delta_state": candidate_delta.model_dump(mode="json"),
            "verification_result": None,
        })
    else:
        debug_event_fn("red.input", {
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
    red_prompt = render_red_prompt_fn(
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
    debug_event_fn("red.output", {"red_finding": red_finding.model_dump(mode="json")})
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
        debug_event_fn("referee.input", {
            "game_spec": game_spec.model_dump(mode="json"),
            "state_view": state_view.model_dump(mode="json"),
            "delta_state": candidate_delta.model_dump(mode="json"),
            "red_finding": red_finding.model_dump(mode="json"),
            "verification_result": None,
        })
    else:
        debug_event_fn("referee.input", {
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
    referee_prompt = render_referee_prompt_fn(
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
    debug_event_fn("referee.output", {"referee_decision": referee_decision.model_dump(mode="json")})
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
    verify_candidate_fn: Any,
) -> tuple[PlayGameRuntime, dict[str, Any] | None, VerificationResult | None, bool]:
    runtime = apply_referee_decision_to_runtime(
        runtime=runtime,
        candidate_delta=candidate_delta,
        decision=referee_decision,
    )
    if referee_decision.disposition == "accept":
        candidate_result = verify_candidate_fn(
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
