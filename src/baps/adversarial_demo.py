from __future__ import annotations

from pathlib import Path

from baps.blackboard import Blackboard
from baps.runtime import RuntimeEngine
from baps.schemas import Decision, Finding, GameContract, GameState, Move, Target


def run_adversarial_demo(blackboard_path: Path) -> GameState:
    blackboard = Blackboard(blackboard_path)
    engine = RuntimeEngine(blackboard)
    contract = GameContract(
        id="adversarial-demo-001",
        subject="README demo instructions",
        goal="Produce a README section explaining how to run the demo",
        target=Target(kind="document", ref="README.md"),
        active_roles=["blue", "red", "referee"],
        max_rounds=1,
    )

    def blue_role(_contract: GameContract) -> Move:
        return Move(
            game_id=_contract.id,
            role="blue",
            summary="Draft README section with only `uv run baps-demo` command.",
            payload={"candidate_section": "Run the demo with: uv run baps-demo"},
        )

    def red_role(_contract: GameContract, blue_move: Move) -> Finding:
        return Finding(
            game_id=_contract.id,
            severity="high",
            confidence="high",
            claim=f"Blue candidate is incomplete: {blue_move.summary}",
            evidence=[
                "Candidate omits `uv sync` setup step.",
                "Candidate does not mention expected output fields.",
            ],
            block_integration=True,
        )

    def referee_role(_contract: GameContract, _blue_move: Move, red_finding: Finding) -> Decision:
        decision = "reject" if red_finding.severity == "high" else "accept"
        return Decision(
            game_id=_contract.id,
            decision=decision,
            rationale=f"Decision `{decision}` based on red finding: {red_finding.claim}",
        )

    return engine.run_game(contract, blue_role, red_role, referee_role)


def main() -> None:
    blackboard_path = Path("blackboard/adversarial-events.jsonl")
    state = run_adversarial_demo(blackboard_path)
    round_1 = state.rounds[0]
    blue = round_1.moves[0]
    red = round_1.findings[0]
    referee = state.final_decision

    print(f"game_id={state.game_id}")
    print(f"run_id={state.run_id}")
    print(f"blue_summary={blue.summary}")
    print(f"red_claim={red.claim}")
    print(f"referee_decision={referee.decision if referee is not None else 'none'}")
    print(f"referee_rationale={referee.rationale if referee is not None else 'none'}")
    print(f"blackboard_path={blackboard_path}")
