from __future__ import annotations

import argparse
import os
from pathlib import Path

from baps.blackboard import Blackboard
from baps.example_roles import make_prompt_blue_role, make_prompt_red_role, make_prompt_referee_role
from baps.models import OllamaClient
from baps.runtime import RuntimeEngine
from baps.schemas import GameContract, GameState, Target


def run_play_game(
    *,
    subject: str,
    goal: str,
    target_kind: str,
    target_ref: str | None,
    model: str,
    base_url: str,
    blackboard_path: Path,
) -> GameState:
    model_client = OllamaClient(model=model, base_url=base_url)
    blue_role = make_prompt_blue_role(model_client)
    red_role = make_prompt_red_role(model_client)
    referee_role = make_prompt_referee_role(model_client)

    contract = GameContract(
        id="play-game-001",
        subject=subject,
        goal=goal,
        target=Target(kind=target_kind, ref=target_ref),
        active_roles=["blue", "red", "referee"],
        max_rounds=1,
    )
    engine = RuntimeEngine(Blackboard(blackboard_path))
    return engine.run_game(contract, blue_role, red_role, referee_role)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="baps-play-game")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--target-kind", required=True)
    parser.add_argument("--target-ref")
    parser.add_argument("--model", default=os.getenv("BAPS_OLLAMA_MODEL", "gemma3"))
    parser.add_argument("--base-url", default=os.getenv("BAPS_OLLAMA_BASE_URL", "http://localhost:11434"))
    parser.add_argument("--blackboard-path", default="blackboard/play-game-events.jsonl")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    blackboard_path = Path(args.blackboard_path)
    state = run_play_game(
        subject=args.subject,
        goal=args.goal,
        target_kind=args.target_kind,
        target_ref=args.target_ref,
        model=args.model,
        base_url=args.base_url,
        blackboard_path=blackboard_path,
    )

    round_1 = state.rounds[0]
    blue = round_1.moves[0]
    red = round_1.findings[0]
    referee = state.final_decision
    print(f"game_id={state.game_id}")
    print(f"run_id={state.run_id}")
    print(f"subject={args.subject}")
    print(f"goal={args.goal}")
    print(f"target_kind={args.target_kind}")
    print(f"target_ref={args.target_ref}")
    print(f"blue_summary={blue.summary}")
    print(f"red_claim={red.claim}")
    print(f"red_block_integration={red.block_integration}")
    print(f"referee_decision={referee.decision if referee is not None else 'none'}")
    print(f"referee_rationale={referee.rationale if referee is not None else 'none'}")
    print(f"blackboard_path={blackboard_path}")
