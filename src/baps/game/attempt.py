"""Executes a single Blue/Red/Referee attempt cycle and applies the Referee decision to runtime."""

from __future__ import annotations

from pydantic import BaseModel, SerializeAsAny

from baps.adapters.project_adapter import VerificationResult
from baps.core.parsers import parse_red_finding_json, parse_referee_decision_json
from baps.core.prompts import (
    get_research_tools,
    render_red_prompt_supplement_with_adapter,
    render_referee_prompt_supplement_with_adapter,
    render_research_prompt,
    render_tool_session_block,
)
from baps.core.roles import SpecRole
from baps.game.roles import (
    AttemptRejection,
    AttemptRejectionFeedback,
    BlueValidationFeedback,
    PlayGameContext,
    PlayGameFeedback,
)
from baps.models.model_output import ParseRecoveryRecord
from baps.models.models import ToolCallRecord
from baps.state.state import (
    DeltaState,
    PlayGameRuntime,
    RedFinding,
    RefereeDecision,
    apply_referee_decision_to_runtime,
)


class PlayAttemptRecord(BaseModel):
    """Records the inputs and outputs for a single play_game attempt for telemetry."""

    attempt_number: int
    blue_delta: SerializeAsAny[DeltaState] | None = None
    red_finding: RedFinding | None = None
    referee_decision: RefereeDecision | None = None
    candidate_verification: VerificationResult | None = None
    parse_recovery: ParseRecoveryRecord | None = None

    def to_telemetry_dict(self) -> dict:
        """Serialize this record to a JSON-safe dict for blackboard writing."""
        return self.model_dump(mode="json")


def _aggregate_parse_recovery(
    records: list[ParseRecoveryRecord],
) -> ParseRecoveryRecord:
    """Combine multiple ParseRecoveryRecords into one by union of keys and OR of boolean flags."""
    all_keys = sorted({k for r in records for k in r.unexpected_keys_stripped})
    return ParseRecoveryRecord(
        unexpected_keys_stripped=all_keys,
        response_shape_rescued=any(r.response_shape_rescued for r in records),
        output_truncated=any(r.output_truncated for r in records),
        empty_items_filtered=any(r.empty_items_filtered for r in records),
        retry_used=any(r.retry_used for r in records),
        fallback_used=any(r.fallback_used for r in records),
    )


def run_play_game_attempt(
    *,
    ctx: PlayGameContext,
    attempt: int,
    previous_feedback: PlayGameFeedback | None,
    verification_result: VerificationResult | None,
) -> tuple[
    PlayAttemptRecord,
    DeltaState | None,
    RedFinding | None,
    RefereeDecision | None,
    PlayGameFeedback | None,
]:
    """Execute one Blue/Red/Referee attempt cycle and return the attempt record and role outputs."""
    attempt_rec = PlayAttemptRecord(attempt_number=attempt)

    blue_session: list[ToolCallRecord] = []
    blue_summary = ""
    if ctx.executor is not None:
        blue_research_tools = get_research_tools(ctx.resolved_adapter)
        if blue_research_tools:
            research_prompt = render_research_prompt(
                SpecRole.BLUE, ctx.state_view, ctx.game_spec, []
            )
            blue_summary, blue_session = ctx.blue_role.generate_agentic(
                research_prompt, blue_research_tools, ctx.executor
            )

    ctx.debug_event_fn(
        "blue.input",
        {
            "game_spec": ctx.game_spec.model_dump(mode="json"),
            "state_view": ctx.state_view.model_dump(mode="json"),
            "attempt_number": attempt,
            "previous_feedback": (
                previous_feedback.model_dump(mode="json", exclude_none=True)
                if previous_feedback is not None
                else None
            ),
        },
    )
    blue_prompt = ctx.resolved_adapter.render_blue_prompt(
        ctx.state_view, ctx.game_spec, attempt, previous_feedback
    )
    if blue_session or blue_summary:
        blue_prompt = (
            render_tool_session_block([(SpecRole.BLUE, blue_session, blue_summary)])
            + "\n\n"
            + blue_prompt
        )
    blue_tools = ctx.resolved_adapter.build_blue_tools()
    blue_tool_call = None
    if blue_tools:
        try:
            blue_tool_call = ctx.blue_role.generate_with_tools(blue_prompt, blue_tools)
        except ValueError:
            pass
    if blue_tool_call is not None:
        try:
            candidate_delta = ctx.resolved_adapter.tool_call_to_delta(blue_tool_call)
        except ValueError as exc:
            ctx.debug_event_fn(
                "blue.failed_tool_call", {"tool_call": str(blue_tool_call)}
            )
            reason = f"blue output failed DeltaState validation: {exc}"
            ctx.debug_event_fn(
                "play_game.attempt_rejected", {"attempt": attempt, "reason": reason}
            )
            updated_feedback = BlueValidationFeedback(
                attempt_rejection=AttemptRejection(
                    stage=SpecRole.BLUE,
                    reason=reason,
                    validation_error=str(exc),
                )
            )
            return attempt_rec, None, None, None, updated_feedback
    else:
        blue_generated = ctx.blue_role.generate(blue_prompt)
        try:
            candidate_delta = ctx.resolved_adapter.parse_blue_delta(blue_generated)
        except ValueError as exc:
            reason = f"blue output failed DeltaState validation: {exc}"
            ctx.debug_event_fn(
                "play_game.attempt_rejected", {"attempt": attempt, "reason": reason}
            )
            updated_feedback = BlueValidationFeedback(
                attempt_rejection=AttemptRejection(
                    stage=SpecRole.BLUE,
                    reason=reason,
                    validation_error=str(exc),
                )
            )
            return attempt_rec, None, None, None, updated_feedback
    ctx.debug_event_fn(
        "blue.output", {"delta_state": candidate_delta.model_dump(mode="json")}
    )
    attempt_rec.blue_delta = candidate_delta

    red_session: list[ToolCallRecord] = []
    red_summary = ""
    if ctx.executor is not None:
        red_research_tools = get_research_tools(ctx.resolved_adapter)
        if red_research_tools:
            prior = (
                [(SpecRole.BLUE, blue_session, blue_summary)]
                if blue_session or blue_summary
                else []
            )
            research_prompt = render_research_prompt(
                SpecRole.RED, ctx.state_view, ctx.game_spec, prior
            )
            red_summary, red_session = ctx.red_role.generate_agentic(
                research_prompt, red_research_tools, ctx.executor
            )

    if verification_result is None:
        ctx.debug_event_fn(
            "red.input",
            {
                "game_spec": ctx.game_spec.model_dump(mode="json"),
                "state_view": ctx.state_view.model_dump(mode="json"),
                "delta_state": candidate_delta.model_dump(mode="json"),
                "verification_result": None,
            },
        )
    else:
        ctx.debug_event_fn(
            "red.input",
            {
                "game_spec": ctx.game_spec.model_dump(mode="json"),
                "state_view": ctx.state_view.model_dump(mode="json"),
                "delta_state": candidate_delta.model_dump(mode="json"),
                "verification_result": {
                    "command": verification_result.command,
                    "cwd": verification_result.cwd,
                    "exit_code": verification_result.exit_code,
                    "stdout": verification_result.stdout,
                    "stderr": verification_result.stderr,
                    "passed": verification_result.passed,
                },
            },
        )
    red_supplement = render_red_prompt_supplement_with_adapter(
        ctx.resolved_adapter,
        ctx.state_view,
        ctx.game_spec,
        candidate_delta,
        verification_result,
    )
    tool_context = render_tool_session_block(
        [
            s
            for s in [
                (SpecRole.BLUE, blue_session, blue_summary),
                (SpecRole.RED, red_session, red_summary),
            ]
            if s[1] or s[2]
        ]
    )
    red_supplement_with_tools = (
        (
            tool_context
            + "\n\nTool-use enforcement: treat any claim referencing external "
            "information not supported by the tool call log above as unverified. "
            "If Blue claims to have verified something externally but has no tool calls to show it, "
            "flag that as a finding.\n\n"
        )
        if tool_context
        else ""
    ) + red_supplement
    red_prompt = ctx.render_red_prompt_fn(
        ctx.state_view,
        ctx.game_spec,
        candidate_delta,
        verification_result,
        red_supplement_with_tools,
    )
    red_generated = ctx.red_role.generate(red_prompt)
    red_finding, red_recovery = parse_red_finding_json(
        red_generated,
        workspace=ctx.workspace,
        retry_fn=ctx.red_role.generate,
        fallback_fn=ctx.red_fallback_fn,
    )
    ctx.debug_event_fn(
        "red.output", {"red_finding": red_finding.model_dump(mode="json")}
    )
    attempt_rec.red_finding = red_finding

    referee_session: list[ToolCallRecord] = []
    referee_summary = ""
    if ctx.executor is not None:
        referee_research_tools = get_research_tools(ctx.resolved_adapter)
        if referee_research_tools:
            prior = [
                s
                for s in [
                    (SpecRole.BLUE, blue_session, blue_summary),
                    (SpecRole.RED, red_session, red_summary),
                ]
                if s[1] or s[2]
            ]
            research_prompt = render_research_prompt(
                SpecRole.REFEREE, ctx.state_view, ctx.game_spec, prior
            )
            referee_summary, referee_session = ctx.referee_role.generate_agentic(
                research_prompt, referee_research_tools, ctx.executor
            )

    if verification_result is None:
        ctx.debug_event_fn(
            "referee.input",
            {
                "game_spec": ctx.game_spec.model_dump(mode="json"),
                "state_view": ctx.state_view.model_dump(mode="json"),
                "delta_state": candidate_delta.model_dump(mode="json"),
                "red_finding": red_finding.model_dump(mode="json"),
                "verification_result": None,
            },
        )
    else:
        ctx.debug_event_fn(
            "referee.input",
            {
                "game_spec": ctx.game_spec.model_dump(mode="json"),
                "state_view": ctx.state_view.model_dump(mode="json"),
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
            },
        )
    referee_supplement = render_referee_prompt_supplement_with_adapter(
        ctx.resolved_adapter,
        ctx.state_view,
        ctx.game_spec,
        candidate_delta,
        verification_result,
    )
    all_sessions = [
        s
        for s in [
            (SpecRole.BLUE, blue_session, blue_summary),
            (SpecRole.RED, red_session, red_summary),
            (SpecRole.REFEREE, referee_session, referee_summary),
        ]
        if s[1] or s[2]
    ]
    referee_tool_context = render_tool_session_block(all_sessions)
    referee_supplement_with_tools = (
        (
            referee_tool_context
            + "\n\nTool-use enforcement: any claim referencing external "
            "information not supported by the tool call logs above must be treated as unverified "
            "and rejected.\n\n"
        )
        if referee_tool_context
        else ""
    ) + referee_supplement
    referee_prompt = ctx.render_referee_prompt_fn(
        ctx.state_view,
        ctx.game_spec,
        candidate_delta,
        red_finding,
        verification_result,
        referee_supplement_with_tools,
    )
    referee_generated = ctx.referee_role.generate(referee_prompt)
    referee_decision, referee_recovery = parse_referee_decision_json(
        referee_generated,
        workspace=ctx.workspace,
        retry_fn=ctx.referee_role.generate,
        fallback_fn=ctx.referee_fallback_fn,
    )
    ctx.debug_event_fn(
        "referee.output", {"referee_decision": referee_decision.model_dump(mode="json")}
    )
    attempt_rec.referee_decision = referee_decision
    attempt_rec.parse_recovery = _aggregate_parse_recovery(
        [red_recovery, referee_recovery]
    )
    return (
        attempt_rec,
        candidate_delta,
        red_finding,
        referee_decision,
        previous_feedback,
    )


def apply_play_game_attempt_decision(
    *,
    ctx: PlayGameContext,
    runtime: PlayGameRuntime,
    attempt: int,
    attempt_rec: PlayAttemptRecord,
    candidate_delta: DeltaState,
    red_finding: RedFinding,
    referee_decision: RefereeDecision,
) -> tuple[
    PlayGameRuntime, AttemptRejectionFeedback | None, VerificationResult | None, bool
]:
    """Apply the Referee decision to runtime, optionally verify the candidate, and return updated state."""
    runtime = apply_referee_decision_to_runtime(
        runtime=runtime,
        candidate_delta=candidate_delta,
        decision=referee_decision,
    )
    if referee_decision.disposition == "accept":
        candidate_result = ctx.verify_candidate_fn(
            ctx.resolved_adapter,
            candidate_delta,
            ctx.state,
            ctx.game_spec.target_artifact_id,
            sandbox_mode=ctx.sandbox_mode,
        )
        attempt_rec.candidate_verification = candidate_result
        if (
            candidate_result is not None
            and not candidate_result.passed
            and attempt < ctx.max_attempts
        ):
            previous_feedback = AttemptRejectionFeedback(
                red_finding=red_finding,
                referee_decision=referee_decision,
                candidate_verification=candidate_result,
            )
            return runtime, previous_feedback, candidate_result, False
        return runtime, None, candidate_result, True
    previous_feedback = AttemptRejectionFeedback(
        red_finding=red_finding,
        referee_decision=referee_decision,
    )
    return runtime, previous_feedback, None, False
