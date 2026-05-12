from __future__ import annotations

from baps.models import ModelClient
from baps.prompts import PromptRenderer
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


def make_prompt_blue_role(
    model_client: ModelClient,
    template: str = "Blue role for game {game_id}: {goal}",
    extra_context: dict | None = None,
):
    renderer = PromptRenderer(template)
    context_overrides = dict(extra_context) if extra_context is not None else {}

    def _role(contract: GameContract) -> Move:
        context = {
            "game_id": contract.id,
            "subject": contract.subject,
            "goal": contract.goal,
            "target_kind": contract.target.kind,
            "target_ref": contract.target.ref,
        }
        context.update(context_overrides)
        prompt = renderer.render(context)
        summary = model_client.generate(prompt)
        return Move(
            game_id=contract.id,
            role="blue",
            summary=summary,
            payload={"goal": contract.goal},
        )

    return _role


def make_prompt_red_role(
    model_client: ModelClient,
    template: str = "Red role for game {game_id}: critique blue move `{blue_summary}` for goal `{goal}`",
    extra_context: dict | None = None,
):
    renderer = PromptRenderer(template)
    context_overrides = dict(extra_context) if extra_context is not None else {}

    def _role(contract: GameContract, blue_move: Move) -> Finding:
        context = {
            "game_id": contract.id,
            "subject": contract.subject,
            "goal": contract.goal,
            "target_kind": contract.target.kind,
            "target_ref": contract.target.ref,
            "blue_summary": blue_move.summary,
            "blue_payload": blue_move.payload,
        }
        context.update(context_overrides)
        prompt = renderer.render(context)
        claim = model_client.generate(prompt)
        return Finding(
            game_id=contract.id,
            severity="medium",
            confidence="medium",
            claim=claim,
            evidence=[f"Blue summary: {blue_move.summary}"],
            block_integration=False,
        )

    return _role


def make_prompt_referee_role(
    model_client: ModelClient,
    template: str = (
        "Referee for game {game_id}. Structured decision is already fixed to `{decision}`. "
        "{decision_rationale_goal} "
        "Blue move: `{blue_summary}`. "
        "Red finding: `{red_claim}` (severity={red_severity}, confidence={red_confidence}, "
        "block_integration={red_block_integration})."
    ),
    extra_context: dict | None = None,
):
    renderer = PromptRenderer(template)
    context_overrides = dict(extra_context) if extra_context is not None else {}

    def _role(contract: GameContract, blue_move: Move, red_finding: Finding) -> Decision:
        decision = "reject" if red_finding.block_integration else "accept"
        context = {
            "game_id": contract.id,
            "subject": contract.subject,
            "goal": contract.goal,
            "target_kind": contract.target.kind,
            "target_ref": contract.target.ref,
            "blue_summary": blue_move.summary,
            "red_claim": red_finding.claim,
            "red_severity": red_finding.severity,
            "red_confidence": red_finding.confidence,
            "red_block_integration": red_finding.block_integration,
            "decision": decision,
            "decision_rationale_goal": (
                "Provide one concise rationale that supports this fixed decision. "
                "Do not choose a different decision and do not contradict it."
            ),
        }
        context.update(context_overrides)
        prompt = renderer.render(context)
        rationale = model_client.generate(prompt)
        return Decision(
            game_id=contract.id,
            decision=decision,
            rationale=rationale,
        )

    return _role
