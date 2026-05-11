from __future__ import annotations

from baps.blackboard import Blackboard
from baps.schemas import Decision, Event, Finding, GameContract, GameRound, GameState, Move


class RuntimeEngine:
    def __init__(self, blackboard: Blackboard):
        self.blackboard = blackboard

    def run_game(self, contract: GameContract, blue_role, red_role, referee_role) -> GameState:
        self.blackboard.append(
            Event(
                id=f"{contract.id}:game_started",
                type="game_started",
                payload={"game_id": contract.id},
            )
        )

        blue_move = Move.model_validate(blue_role(contract))
        if blue_move.game_id != contract.id:
            raise ValueError("blue move game_id does not match contract.id")
        if blue_move.role != "blue":
            raise ValueError("blue move role must be 'blue'")
        self.blackboard.append(
            Event(
                id=f"{contract.id}:blue_move_recorded",
                type="blue_move_recorded",
                payload={"game_id": contract.id, "move": blue_move.model_dump(mode="json")},
            )
        )

        red_finding = Finding.model_validate(red_role(contract, blue_move))
        if red_finding.game_id != contract.id:
            raise ValueError("red finding game_id does not match contract.id")
        self.blackboard.append(
            Event(
                id=f"{contract.id}:red_finding_recorded",
                type="red_finding_recorded",
                payload={"game_id": contract.id, "finding": red_finding.model_dump(mode="json")},
            )
        )

        referee_decision = Decision.model_validate(referee_role(contract, blue_move, red_finding))
        if referee_decision.game_id != contract.id:
            raise ValueError("referee decision game_id does not match contract.id")
        self.blackboard.append(
            Event(
                id=f"{contract.id}:referee_decision_recorded",
                type="referee_decision_recorded",
                payload={"game_id": contract.id, "decision": referee_decision.model_dump(mode="json")},
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
            current_round=1,
            rounds=[round_1],
            final_decision=referee_decision,
        )
        self.blackboard.append(
            Event(
                id=f"{contract.id}:game_completed",
                type="game_completed",
                payload={"game_id": contract.id, "state": state.model_dump(mode="json")},
            )
        )
        return state
