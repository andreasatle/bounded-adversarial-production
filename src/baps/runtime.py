from __future__ import annotations

from datetime import datetime, timezone
import inspect
from uuid import uuid4

from baps.blackboard import Blackboard
from baps.roles import RoleInvocationGuard
from baps.schemas import (
    Decision,
    Event,
    Finding,
    GameContract,
    GameResponse,
    GameRound,
    GameState,
    IntegrationRecommendation,
    Move,
    RoundSummary,
    TerminalOutcome,
)


def generate_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    short_uuid = uuid4().hex[:8]
    return f"run-{timestamp}-{short_uuid}"


def build_game_response(
    state: GameState,
    contract: GameContract,
    trace_event_ids: list[str] | None = None,
) -> GameResponse:
    _validate_state_for_response(state=state, contract=contract)
    last_round = state.rounds[-1]
    if not last_round.moves:
        raise ValueError("last round must contain at least one move")
    if not last_round.findings:
        raise ValueError("last round must contain at least one finding")

    rounds_played = len(state.rounds)
    (
        terminal_reason,
        terminal_outcome,
        integration_recommendation,
    ) = _derive_terminal_semantics(
        decision=state.final_decision,
        rounds_played=rounds_played,
        max_rounds=contract.max_rounds,
    )

    round_summaries: list[RoundSummary] = []
    for round_ in state.rounds:
        if round_.decision is None:
            raise ValueError("each round must contain a decision")
        if not round_.moves:
            raise ValueError("each round must contain at least one move")
        if not round_.findings:
            raise ValueError("each round must contain at least one finding")
        round_summaries.append(
            RoundSummary(
                round_number=round_.round_number,
                blue_summary=round_.moves[-1].summary,
                red_claim=round_.findings[-1].claim,
                referee_decision=round_.decision.decision,
                referee_rationale=round_.decision.rationale,
            )
        )

    return GameResponse(
        game_id=state.game_id,
        run_id=state.run_id,
        rounds_played=rounds_played,
        max_rounds=contract.max_rounds,
        final_decision=state.final_decision,
        terminal_reason=terminal_reason,
        terminal_outcome=terminal_outcome,
        integration_recommendation=integration_recommendation,
        final_blue_summary=last_round.moves[-1].summary,
        final_red_claim=last_round.findings[-1].claim,
        trace_event_ids=list(trace_event_ids) if trace_event_ids is not None else [],
        round_summaries=round_summaries,
    )


def _derive_terminal_semantics(
    *,
    decision: Decision,
    rounds_played: int,
    max_rounds: int,
) -> tuple[str, TerminalOutcome, IntegrationRecommendation]:
    if decision.decision == "accept":
        return ("accepted", "accepted_locally", "integration_recommended")
    if decision.decision == "reject":
        return ("rejected", "rejected_locally", "do_not_integrate")
    if decision.decision == "revise":
        if rounds_played >= max_rounds:
            return ("round_budget_exhausted", "revision_budget_exhausted", "do_not_integrate")
        raise ValueError(
            "cannot build completed game response for revise decision before round budget exhaustion"
        )
    raise ValueError(f"unsupported final decision for game response: {decision.decision}")


def _validate_state_for_response(*, state: GameState, contract: GameContract) -> None:
    if state.final_decision is None:
        raise ValueError("state.final_decision must be present")
    if not state.rounds:
        raise ValueError("state.rounds must be non-empty")

    rounds_played = len(state.rounds)
    if state.current_round != rounds_played:
        raise ValueError("state.current_round must match number of completed rounds")
    if rounds_played > contract.max_rounds:
        raise ValueError("state.rounds exceeds contract.max_rounds")

    last_round_decision = state.rounds[-1].decision
    if last_round_decision is None:
        raise ValueError("last round must contain a decision")
    if state.final_decision != last_round_decision:
        raise ValueError("state.final_decision must match the last round decision")


class RuntimeEngine:
    def __init__(self, blackboard: Blackboard, guard: RoleInvocationGuard | None = None):
        self.blackboard = blackboard
        self.guard = guard if guard is not None else RoleInvocationGuard()

    def run_game(self, contract: GameContract, blue_role, red_role, referee_role) -> GameState:
        run_id = generate_run_id()
        self.blackboard.append(
            Event(
                id=f"{contract.id}:{run_id}:r0001:game_started",
                type="game_started",
                payload={"game_id": contract.id, "run_id": run_id},
            )
        )

        def validate_blue_semantics(move: Move) -> None:
            if move.game_id != contract.id:
                raise ValueError("blue move game_id does not match contract.id")
            if move.role != "blue":
                raise ValueError("blue move role must be 'blue'")

        def validate_red_semantics(finding: Finding) -> None:
            if finding.game_id != contract.id:
                raise ValueError("red finding game_id does not match contract.id")

        def validate_referee_semantics(decision: Decision) -> None:
            if decision.game_id != contract.id:
                raise ValueError("referee decision game_id does not match contract.id")

        rounds: list[GameRound] = []
        final_decision: Decision | None = None
        previous_context: dict | None = None
        current_round = 1

        while current_round <= contract.max_rounds:
            if current_round == 1 or previous_context is None:
                blue_args = (contract,)
            else:
                blue_args = (
                    (contract, previous_context)
                    if _supports_revision_context(blue_role)
                    else (contract,)
                )

            blue_move = self.guard.invoke(
                role_callable=blue_role,
                args=blue_args,
                output_model=Move,
                semantic_validator=validate_blue_semantics,
            )
            self.blackboard.append(
                Event(
                    id=f"{contract.id}:{run_id}:r{current_round:04d}:blue_move_recorded",
                    type="blue_move_recorded",
                    payload={
                        "game_id": contract.id,
                        "run_id": run_id,
                        "round_number": current_round,
                        "move": blue_move.model_dump(mode="json"),
                    },
                )
            )

            red_finding = self.guard.invoke(
                role_callable=red_role,
                args=(contract, blue_move),
                output_model=Finding,
                semantic_validator=validate_red_semantics,
            )
            self.blackboard.append(
                Event(
                    id=f"{contract.id}:{run_id}:r{current_round:04d}:red_finding_recorded",
                    type="red_finding_recorded",
                    payload={
                        "game_id": contract.id,
                        "run_id": run_id,
                        "round_number": current_round,
                        "finding": red_finding.model_dump(mode="json"),
                    },
                )
            )

            referee_decision = self.guard.invoke(
                role_callable=referee_role,
                args=(contract, blue_move, red_finding),
                output_model=Decision,
                semantic_validator=validate_referee_semantics,
            )
            self.blackboard.append(
                Event(
                    id=f"{contract.id}:{run_id}:r{current_round:04d}:referee_decision_recorded",
                    type="referee_decision_recorded",
                    payload={
                        "game_id": contract.id,
                        "run_id": run_id,
                        "round_number": current_round,
                        "decision": referee_decision.model_dump(mode="json"),
                    },
                )
            )

            rounds.append(
                GameRound(
                    round_number=current_round,
                    moves=[blue_move],
                    findings=[red_finding],
                    decision=referee_decision,
                )
            )
            final_decision = referee_decision
            previous_context = {
                "previous_blue_summary": blue_move.summary,
                "previous_red_claim": red_finding.claim,
                "previous_referee_rationale": referee_decision.rationale,
            }

            if referee_decision.decision in {"accept", "reject"}:
                break
            if referee_decision.decision == "revise" and current_round < contract.max_rounds:
                current_round += 1
                continue
            break

        state = GameState(
            game_id=contract.id,
            run_id=run_id,
            current_round=current_round,
            rounds=rounds,
            final_decision=final_decision,
        )
        if final_decision is None:
            raise ValueError("final_decision must be present when writing game_completed event")
        _, terminal_outcome, integration_recommendation = _derive_terminal_semantics(
            decision=final_decision,
            rounds_played=len(rounds),
            max_rounds=contract.max_rounds,
        )
        self.blackboard.append(
            Event(
                id=f"{contract.id}:{run_id}:game_completed",
                type="game_completed",
                payload={
                    "game_id": contract.id,
                    "run_id": run_id,
                    "state": state.model_dump(mode="json"),
                    "terminal_outcome": terminal_outcome,
                    "integration_recommendation": integration_recommendation,
                },
            )
        )
        return state


def _supports_revision_context(role_callable) -> bool:
    signature = inspect.signature(role_callable)
    params = list(signature.parameters.values())
    if any(param.kind == inspect.Parameter.VAR_POSITIONAL for param in params):
        return True
    positional = [
        param
        for param in params
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    return len(positional) >= 2
