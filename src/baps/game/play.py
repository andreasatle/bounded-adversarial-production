from __future__ import annotations

from pathlib import Path

from baps.adapters.project_adapter import VerificationResult
from baps.state.state import GameSpec, PlayGameRuntime

from baps.game.telemetry import _append_game_to_blackboard


def _record_play_game_telemetry(
    *,
    workspace: Path | None,
    game_id: str,
    depth: int,
    game_spec: GameSpec,
    attempt_records: list[dict],
    last_candidate_result: VerificationResult | None,
    runtime: PlayGameRuntime,
    debug_event_fn,
) -> None:
    debug_event_fn("play_game.output", {
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
