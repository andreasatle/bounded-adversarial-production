from __future__ import annotations

from baps.schemas import Decision, Finding, GameContract, Move


def blue_role(contract: GameContract) -> Move:
    return Move(
        game_id=contract.id,
        role="blue",
        summary="Propose a minimal safe implementation update.",
        payload={"goal": contract.goal},
    )


def red_role(contract: GameContract, blue_move: Move) -> Finding:
    return Finding(
        game_id=contract.id,
        severity="low",
        confidence="high",
        claim=f"Potential risk identified in blue move: {blue_move.summary}",
        evidence=["Manual review suggests low-impact edge-case exposure."],
        block_integration=False,
    )


def referee_role(contract: GameContract, blue_move: Move, red_finding: Finding) -> Decision:
    return Decision(
        game_id=contract.id,
        decision="accept",
        rationale=f"Accepted move '{blue_move.summary}' after reviewing finding '{red_finding.claim}'.",
    )
