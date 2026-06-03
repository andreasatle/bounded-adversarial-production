"""Emits play_game telemetry (debug events and blackboard records) after all attempts complete."""

from __future__ import annotations

from baps.adapters.project_adapter import VerificationResult
from baps.game.attempt import PlayAttemptRecord
from baps.game.roles import PlayGameContext
from baps.game.telemetry import append_game_to_blackboard
from baps.state.state import PlayGameRuntime


def record_play_game_telemetry(
    *,
    ctx: PlayGameContext,
    attempt_records: list[PlayAttemptRecord],
    last_candidate_result: VerificationResult | None,
    runtime: PlayGameRuntime,
) -> None:
    """Emit a debug event and write the completed game record to the blackboard."""
    ctx.debug_event_fn(
        "play_game.output",
        {
            "current_best_delta": (
                None if runtime.current_best_delta is None else runtime.current_best_delta.model_dump(mode="json")
            ),
            "integration_eligible_delta": (
                None
                if runtime.integration_eligible_delta is None
                else runtime.integration_eligible_delta.model_dump(mode="json")
            ),
        },
    )
    if ctx.workspace is None:
        return
    final_disposition = (
        "accepted"
        if runtime.integration_eligible_delta is not None
        else "rejected"
        if any(r.blue_delta is not None for r in attempt_records)
        else "no_delta"
    )
    append_game_to_blackboard(
        workspace=ctx.workspace,
        game_id=ctx.game_id,
        depth=ctx.depth,
        game_spec=ctx.game_spec,
        attempt_records=attempt_records,
        final_disposition=final_disposition,
        verification_result=last_candidate_result,
        current_best_delta=runtime.current_best_delta,
        integration_eligible_delta=runtime.integration_eligible_delta,
    )
