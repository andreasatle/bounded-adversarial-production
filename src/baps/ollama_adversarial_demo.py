from __future__ import annotations

import os
from pathlib import Path

from baps.blackboard import Blackboard
from baps.example_roles import make_prompt_blue_role, make_prompt_red_role, make_prompt_referee_role
from baps.models import OllamaClient
from baps.runtime import RuntimeEngine
from baps.schemas import GameContract, GameState, Target


def run_ollama_adversarial_demo(blackboard_path: Path) -> GameState:
    model = os.getenv("BAPS_OLLAMA_MODEL", "gemma3")
    base_url = os.getenv("BAPS_OLLAMA_BASE_URL", "http://localhost:11434")
    model_client = OllamaClient(model=model, base_url=base_url)

    blue_role = make_prompt_blue_role(
        model_client,
        template="Provide one concise candidate README demo instruction for goal: {goal}",
    )
    red_role = make_prompt_red_role(
        model_client,
        template="Provide one concrete criticism of this candidate: {blue_summary}",
    )
    referee_role = make_prompt_referee_role(
        model_client,
        template="Provide one concise rationale for final decision using finding: {red_claim}",
    )

    blackboard = Blackboard(blackboard_path)
    engine = RuntimeEngine(blackboard)
    contract = GameContract(
        id="ollama-adversarial-demo-001",
        subject="README demo instructions",
        goal="Produce a README section explaining how to run the demo",
        target=Target(kind="document", ref="README.md"),
        active_roles=["blue", "red", "referee"],
        max_rounds=1,
    )
    return engine.run_game(contract, blue_role, red_role, referee_role)


def main() -> None:
    blackboard_path = Path("blackboard/ollama-adversarial-events.jsonl")
    state = run_ollama_adversarial_demo(blackboard_path)
    round_1 = state.rounds[0]
    blue = round_1.moves[0]
    red = round_1.findings[0]
    referee = state.final_decision

    print(f"game_id={state.game_id}")
    print(f"run_id={state.run_id}")
    print(f"blue_summary={blue.summary}")
    print(f"red_claim={red.claim}")
    print(f"red_block_integration={red.block_integration}")
    print(f"referee_decision={referee.decision if referee is not None else 'none'}")
    print(f"referee_rationale={referee.rationale if referee is not None else 'none'}")
    print(f"blackboard_path={blackboard_path}")
