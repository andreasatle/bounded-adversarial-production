from __future__ import annotations

from baps.blackboard import Blackboard
from baps.game_service import GameService
from baps.planner import Planner
from baps.projections import build_projected_state_from_blackboard
from baps.schemas import GameResponse


def run_one_autonomous_step(
    north_star: str,
    blackboard: Blackboard,
    planner: Planner,
    game_service: GameService,
) -> GameResponse:
    if not north_star.strip():
        raise ValueError("north_star must be a non-empty string")

    projected_state = build_projected_state_from_blackboard(blackboard)
    request = planner.plan_next_game(projected_state, north_star)
    return game_service.play(request)


def run_autonomous_steps(
    north_star: str,
    blackboard: Blackboard,
    planner: Planner,
    game_service: GameService,
    max_steps: int,
) -> list[GameResponse]:
    if not north_star.strip():
        raise ValueError("north_star must be a non-empty string")
    if max_steps < 1:
        raise ValueError("max_steps must be >= 1")

    responses: list[GameResponse] = []
    for _ in range(max_steps):
        responses.append(
            run_one_autonomous_step(
                north_star=north_star,
                blackboard=blackboard,
                planner=planner,
                game_service=game_service,
            )
        )
    return responses
