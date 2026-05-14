from __future__ import annotations

from baps.schemas import ActiveGameSummary, Event, ProjectedState


def build_projected_state(events: list[Event]) -> ProjectedState:
    active_by_run: dict[str, ActiveGameSummary] = {}
    active_run_order: list[str] = []

    for event in events:
        payload = event.payload
        game_id = payload.get("game_id")
        run_id = payload.get("run_id")
        if not isinstance(game_id, str) or not game_id.strip():
            continue
        if not isinstance(run_id, str) or not run_id.strip():
            continue

        if event.type == "game_started":
            if run_id in active_by_run:
                continue
            active_by_run[run_id] = ActiveGameSummary(
                id=run_id,
                title=game_id,
                source_run_id=run_id,
                metadata={"game_id": game_id},
            )
            active_run_order.append(run_id)
        elif event.type == "game_completed":
            if run_id not in active_by_run:
                continue
            del active_by_run[run_id]
            active_run_order = [existing_run_id for existing_run_id in active_run_order if existing_run_id != run_id]

    return ProjectedState(
        active_games=[active_by_run[run_id] for run_id in active_run_order if run_id in active_by_run]
    )
