from __future__ import annotations

from baps.blackboard import Blackboard
from baps.example_roles import make_prompt_blue_role, make_prompt_red_role, make_prompt_referee_role
from baps.game_types import GameDefinition, build_game_definition
from baps.models import ModelClient
from baps.prompt_assembly import PromptSection, PromptSpec, assemble_prompt
from baps.runtime import RuntimeEngine, build_game_response
from baps.schemas import GameContract, GameRequest, GameResponse, Target


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
    ):
        if max_rounds < 1:
            raise ValueError("max_rounds must be >= 1")
        self.model_client = model_client
        self.blackboard = blackboard
        self.game_definition = game_definition
        self.max_rounds = max_rounds
        self.shared_context = shared_context
        self.red_material = red_material

    def play(self, request: GameRequest) -> GameResponse:
        resolved_game_definition = (
            self.game_definition
            if self.game_definition is not None
            else build_game_definition(request)
        )

        prompt_sections = resolved_game_definition.prompt_sections
        blue_template = assemble_prompt(
            PromptSpec(
                sections=[
                    PromptSection(
                        name="Role",
                        content=(
                            "Using shared context, provide one concise candidate answer for goal `{goal}`."
                        ),
                    ),
                    PromptSection(
                        name="Shared Context",
                        content="Shared context:\n{shared_context}",
                    ),
                    *prompt_sections.blue_sections,
                ]
            )
        )
        red_template = assemble_prompt(
            PromptSpec(
                sections=[
                    PromptSection(
                        name="Scope",
                        content=(
                            "Critique only this Blue move/change from the current game: `{blue_summary}`. "
                            "Do not perform a general audit. Use shared context only as supporting evidence."
                        ),
                    ),
                    PromptSection(
                        name="Shared Context",
                        content="Shared context:\n{shared_context}",
                    ),
                    PromptSection(
                        name="Output Format",
                        content="MATERIAL: yes|no\nCLAIM: concise critique/assessment",
                    ),
                    *prompt_sections.red_sections,
                ]
            )
        )
        referee_template = assemble_prompt(
            PromptSpec(
                sections=[
                    PromptSection(
                        name="Decision",
                        content=(
                            "Structured decision is already fixed to `{decision}`. "
                            "Provide one concise rationale supporting that fixed decision. "
                            "Do not contradict or reselect the decision."
                        ),
                    ),
                    PromptSection(
                        name="Inputs",
                        content="Blue move: `{blue_summary}`. Red finding: `{red_claim}`.",
                    ),
                    PromptSection(
                        name="Shared Context",
                        content="Shared context:\n{shared_context}",
                    ),
                    *prompt_sections.referee_sections,
                ]
            )
        )

        extra_context = {"shared_context": self.shared_context}
        blue_role = make_prompt_blue_role(
            self.model_client,
            template=blue_template,
            extra_context=extra_context,
        )
        red_role = make_prompt_red_role(
            self.model_client,
            template=red_template,
            extra_context=extra_context,
            default_material=self.red_material,
        )
        referee_role = make_prompt_referee_role(
            self.model_client,
            template=referee_template,
            extra_context=extra_context,
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
