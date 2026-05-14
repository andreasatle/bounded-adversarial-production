from __future__ import annotations

from baps.blackboard import Blackboard
from baps.game_types import GameDefinition, build_game_definition
from baps.models import ModelClient
from baps.prompt_roles import build_prompt_roles
from baps.runtime import RuntimeEngine, build_game_response
from baps.schemas import GameContract, GameRequest, GameResponse, Target
from baps.state_sources import StateManifest, StateSourceAdapter, resolve_state_context


class GameService:
    def __init__(
        self,
        *,
        model_client: ModelClient,
        blackboard: Blackboard,
        game_definition: GameDefinition | None = None,
        max_rounds: int = 1,
        shared_context: str = "",
        red_material: bool = True,
        state_manifest: StateManifest | None = None,
        state_adapter: StateSourceAdapter | None = None,
    ):
        if max_rounds < 1:
            raise ValueError("max_rounds must be >= 1")
        self.model_client = model_client
        self.blackboard = blackboard
        self.game_definition = game_definition
        self.max_rounds = max_rounds
        self.shared_context = shared_context
        self.red_material = red_material
        self.state_manifest = state_manifest
        self.state_adapter = state_adapter

    def play(self, request: GameRequest) -> GameResponse:
        resolved_game_definition = (
            self.game_definition
            if self.game_definition is not None
            else build_game_definition(request)
        )

        resolved_shared_context = self.shared_context
        if request.state_source_ids:
            if self.state_manifest is None or self.state_adapter is None:
                raise ValueError(
                    "request.state_source_ids requires both state_manifest and state_adapter"
                )
            state_context = resolve_state_context(
                manifest=self.state_manifest,
                source_ids=request.state_source_ids,
                adapter=self.state_adapter,
            )
            resolved_shared_context = (
                f"{resolved_shared_context}\n\n{state_context}"
                if resolved_shared_context
                else state_context
            )

        blue_role, red_role, referee_role = build_prompt_roles(
            model_client=self.model_client,
            prompt_sections=resolved_game_definition.prompt_sections,
            shared_context=resolved_shared_context,
            red_material=self.red_material,
        )

        contract = GameContract(
            id="play-game-001",
            subject=request.subject,
            goal=request.goal,
            target=Target(kind=request.target_kind, ref=request.target_ref),
            active_roles=["blue", "red", "referee"],
            max_rounds=self.max_rounds,
        )

        state = RuntimeEngine(self.blackboard).run_game(contract, blue_role, red_role, referee_role)
        return build_game_response(state, contract)
