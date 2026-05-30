from __future__ import annotations

import logging
import uuid
from pathlib import Path

from pydantic import BaseModel

from baps.core.clients import SpecRole, _build_client_for_role
from baps.core.run_config import RunConfig
from baps.core.debug import _debug_print_northstar_update_proposal, _debug_print_verification_result
from baps.game.engine import (
    _commit_export_with_adapter,
    _verify_export_with_adapter,
    create_game,
    play_game,
)
from baps.game.telemetry import (
    append_integration_to_blackboard,
    append_northstar_proposal_to_blackboard,
)
from baps.core.parsers import NoNewGameError, NorthStarUpdateNeededError
from baps.adapters.project_adapter import (
    ProjectTypeAdapter,
    VerificationResult,
    _config_artifact_id,
    _config_northstar_markdown,
)
from baps.state.state import DecomposeSpec, State, StopReason
from baps.state.state_service import StateService
from baps.summarizer.summarizer import SummarizationContext
from baps.tools.tools import build_default_tool_executor


class IterationRunResult(BaseModel):
    """Result returned by _run_project_iterations, summarising outcome fields across all iterations."""
    update_applied: bool
    state_changed: bool
    output_exported: bool
    output_changed: bool
    northstar_proposal_written: bool
    verification_result: VerificationResult | None
    iterations_completed: int
    stop_reason: StopReason

logger = logging.getLogger(__name__)

_DEFAULT_MAX_DEPTH = 3


class _RunContext:
    """Mutable execution context threaded through recursive gap solving."""

    def __init__(self, initial_state: State, max_iterations: int) -> None:
        """Initialize context with the starting state and iteration budget."""
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
    config: RunConfig,
    adapter: ProjectTypeAdapter,
    state_service: StateService,
    output_path: Path,
    artifact_id: str,
    max_depth: int,
    depth: int,
    summarization_context: SummarizationContext | None = None,
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
            summarization_context=summarization_context,
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
                append_northstar_proposal_to_blackboard(
                    workspace=config.workspace,
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
        append_northstar_proposal_to_blackboard(
            workspace=config.workspace,
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
                summarization_context=summarization_context,
            )
            if ctx.stop_reason == StopReason.PLAY_GAME_NO_DELTA:
                ctx.stop_reason = None  # leaf found nothing; continue sibling sub-gaps
            elif ctx.stop_reason is not None:
                return
        return

    # Leaf: GameSpec — inject full context chain and execute
    game_spec = result.model_copy(update={"context_chain": context_chain})
    logger.info("[solve_gap] depth=%d playing leaf game: %s", depth, game_spec.objective)

    sandbox_mode = config.sandbox
    delta_state = play_game(
        ctx.current_state,
        game_spec,
        adapter=adapter,
        verification_result=ctx.verification_result,
        executor=build_default_tool_executor(),
        sandbox_mode=sandbox_mode,
        config=config,
        depth=depth,
        summarization_context=summarization_context,
    )
    if delta_state is None:
        ctx.stop_reason = StopReason.PLAY_GAME_NO_DELTA
        return

    before_state = state_service.load_state()
    updated_state = state_service.apply_delta(delta_state)
    changed = state_service.states_differ(before_state, updated_state)

    _integration_workspace = config.workspace
    if _integration_workspace is not None:
        append_integration_to_blackboard(
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
    config: RunConfig,
    adapter: ProjectTypeAdapter,
    state_service: StateService,
    initial_state: State,
    summarization_context: SummarizationContext | None = None,
) -> IterationRunResult:
    """Drive the outer iteration loop, calling _solve_gap until a stop condition is reached."""
    output_path = config.output_path
    max_iterations = config.max_iterations
    artifact_id = _config_artifact_id(config)
    max_depth = config.max_depth

    if config.project_type == "coding" and config.sandbox == "none":
        from baps.tools.sandbox import SANDBOX_NONE_WARNING
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
            summarization_context=summarization_context,
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
            append_northstar_proposal_to_blackboard(
                workspace=config.workspace,
                rationale=rationale,
                proposed_northstar=_config_northstar_markdown(config),
            )
            ctx.northstar_proposal_written = True
            ctx.stop_reason = StopReason.NORTHSTAR_UPDATE_PROPOSED

    if ctx.stop_reason is None:
        ctx.stop_reason = StopReason.ITERATION_LIMIT_REACHED

    return IterationRunResult(
        update_applied=ctx.update_applied,
        state_changed=ctx.state_changed,
        output_exported=ctx.output_exported,
        output_changed=ctx.output_changed,
        northstar_proposal_written=ctx.northstar_proposal_written,
        verification_result=ctx.verification_result,
        iterations_completed=ctx.iterations_completed,
        stop_reason=ctx.stop_reason,
    )
