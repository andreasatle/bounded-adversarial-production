from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from baps.blackboard import Blackboard
from baps.roles import RoleInvocationGuard
from baps.schemas import Decision, Event, Finding, GameContract, GameRound, GameState, Move


def generate_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    short_uuid = uuid4().hex[:8]
    return f"run-{timestamp}-{short_uuid}"


class RuntimeEngine:
    def __init__(self, blackboard: Blackboard, guard: RoleInvocationGuard | None = None):
        self.blackboard = blackboard
        self.guard = guard if guard is not None else RoleInvocationGuard()

    def run_game(self, contract: GameContract, blue_role, red_role, referee_role) -> GameState:
        run_id = generate_run_id()
        self.blackboard.append(
            Event(
                id=f"{contract.id}:{run_id}:game_started",
                type="game_started",
                payload={"game_id": contract.id, "run_id": run_id},
            )
        )

        def validate_blue_semantics(move: Move) -> None:
            if move.game_id != contract.id:
                raise ValueError("blue move game_id does not match contract.id")
            if move.role != "blue":
                raise ValueError("blue move role must be 'blue'")

        blue_move = self.guard.invoke(
            role_callable=blue_role,
            args=(contract,),
            output_model=Move,
            semantic_validator=validate_blue_semantics,
        )
        self.blackboard.append(
            Event(
                id=f"{contract.id}:{run_id}:blue_move_recorded",
                type="blue_move_recorded",
                payload={
                    "game_id": contract.id,
                    "run_id": run_id,
                    "move": blue_move.model_dump(mode="json"),
                },
            )
        )

        def validate_red_semantics(finding: Finding) -> None:
            if finding.game_id != contract.id:
                raise ValueError("red finding game_id does not match contract.id")

        red_finding = self.guard.invoke(
            role_callable=red_role,
            args=(contract, blue_move),
            output_model=Finding,
            semantic_validator=validate_red_semantics,
        )
        self.blackboard.append(
            Event(
                id=f"{contract.id}:{run_id}:red_finding_recorded",
                type="red_finding_recorded",
                payload={
                    "game_id": contract.id,
                    "run_id": run_id,
                    "finding": red_finding.model_dump(mode="json"),
                },
            )
        )

        def validate_referee_semantics(decision: Decision) -> None:
            if decision.game_id != contract.id:
                raise ValueError("referee decision game_id does not match contract.id")

        referee_decision = self.guard.invoke(
            role_callable=referee_role,
            args=(contract, blue_move, red_finding),
            output_model=Decision,
            semantic_validator=validate_referee_semantics,
        )
        self.blackboard.append(
            Event(
                id=f"{contract.id}:{run_id}:referee_decision_recorded",
                type="referee_decision_recorded",
                payload={
                    "game_id": contract.id,
                    "run_id": run_id,
                    "decision": referee_decision.model_dump(mode="json"),
                },
            )
        )

        round_1 = GameRound(
            round_number=1,
            moves=[blue_move],
            findings=[red_finding],
            decision=referee_decision,
        )
        state = GameState(
            game_id=contract.id,
            run_id=run_id,
            current_round=1,
            rounds=[round_1],
            final_decision=referee_decision,
        )
        self.blackboard.append(
            Event(
                id=f"{contract.id}:{run_id}:game_completed",
                type="game_completed",
                payload={"game_id": contract.id, "run_id": run_id, "state": state.model_dump(mode="json")},
            )
        )
        return state
