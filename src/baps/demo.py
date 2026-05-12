from __future__ import annotations

from pathlib import Path

from baps.blackboard import Blackboard
from baps.example_roles import blue_role, red_role, referee_role
from baps.runtime import RuntimeEngine
from baps.schemas import GameContract, GameState, Target


def run_demo(blackboard_path: Path) -> GameState:
    blackboard = Blackboard(blackboard_path)
    engine = RuntimeEngine(blackboard)
    contract = GameContract(
        id="demo-game-001",
        subject="Demo game",
        goal="Run one deterministic Blue/Red/Referee cycle",
        target=Target(kind="blackboard", ref="demo"),
        active_roles=["blue", "red", "referee"],
        max_rounds=1,
    )
    return engine.run_game(contract, blue_role, red_role, referee_role)


def main() -> None:
    blackboard_path = Path("blackboard/events.jsonl")
    state = run_demo(blackboard_path)
    final_decision = state.final_decision.decision if state.final_decision is not None else "none"
    print(f"game_id={state.game_id}")
    print(f"run_id={state.run_id}")
    print(f"final_decision={final_decision}")
    print(f"blackboard_path={blackboard_path}")
