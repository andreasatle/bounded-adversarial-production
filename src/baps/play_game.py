from __future__ import annotations

import argparse
import os
from pathlib import Path

from baps.blackboard import Blackboard
from baps.example_roles import make_prompt_blue_role, make_prompt_red_role, make_prompt_referee_role
from baps.game_types import (
    GameDefinition,
    get_builtin_game_definition,
    load_game_definition,
)
from baps.models import OllamaClient
from baps.prompt_assembly import PromptSection, PromptSpec, assemble_prompt
from baps.runtime import RuntimeEngine, build_game_response
from baps.schemas import GameContract, GameState, Target


def _truncate_for_output(value: str, limit: int = 200) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _max_rounds_type(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("--max-rounds must be >= 1")
    return parsed


def load_context_files(paths: list[str]) -> str:
    parts: list[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            raise FileNotFoundError(f"context file not found: {raw_path}")
        text = path.read_text(encoding="utf-8")
        parts.append(f"===== FILE: {raw_path} =====\n{text}")
    return "\n\n".join(parts)


def run_play_game(
    *,
    subject: str,
    goal: str,
    target_kind: str,
    target_ref: str | None,
    model: str,
    base_url: str,
    blackboard_path: Path,
    shared_context: str = "",
    max_rounds: int = 1,
    red_material: bool = True,
    game_definition: GameDefinition | None = None,
    game_type: str = "documentation-refinement",
) -> GameState:
    resolved_game_definition = (
        game_definition
        if game_definition is not None
        else get_builtin_game_definition(game_type)
    )
    model_client = OllamaClient(model=model, base_url=base_url)
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

    blue_role = make_prompt_blue_role(
        model_client,
        template=blue_template,
        extra_context={"shared_context": shared_context},
    )
    red_role = make_prompt_red_role(
        model_client,
        template=red_template,
        extra_context={"shared_context": shared_context},
        default_material=red_material,
    )
    referee_role = make_prompt_referee_role(
        model_client,
        template=referee_template,
        extra_context={"shared_context": shared_context},
    )

    contract = GameContract(
        id="play-game-001",
        subject=subject,
        goal=goal,
        target=Target(kind=target_kind, ref=target_ref),
        active_roles=["blue", "red", "referee"],
        max_rounds=max_rounds,
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
    parser.add_argument("--context-file", action="append", default=[])
    parser.add_argument("--game-type", default="documentation-refinement")
    parser.add_argument("--game-definition-file")
    parser.add_argument("--max-rounds", type=_max_rounds_type, default=1)
    parser.add_argument("--red-material", action="store_true", default=True)
    parser.add_argument("--red-non-material", action="store_false", dest="red_material")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    blackboard_path = Path(args.blackboard_path)
    shared_context = load_context_files(args.context_file)
    resolved_game_definition = (
        load_game_definition(Path(args.game_definition_file))
        if args.game_definition_file
        else get_builtin_game_definition(args.game_type)
    )
    state = run_play_game(
        subject=args.subject,
        goal=args.goal,
        target_kind=args.target_kind,
        target_ref=args.target_ref,
        model=args.model,
        base_url=args.base_url,
        blackboard_path=blackboard_path,
        shared_context=shared_context,
        max_rounds=args.max_rounds,
        red_material=args.red_material,
        game_definition=resolved_game_definition,
    )
    contract = GameContract(
        id="play-game-001",
        subject=args.subject,
        goal=args.goal,
        target=Target(kind=args.target_kind, ref=args.target_ref),
        active_roles=["blue", "red", "referee"],
        max_rounds=args.max_rounds,
    )
    result = build_game_response(state, contract)

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
    print(f"game_type={args.game_type}")
    print(f"game_definition_id={resolved_game_definition.id}")
    print(f"game_definition_name={resolved_game_definition.name}")
    print(f"rounds_played={result.rounds_played}")
    print(f"max_rounds={result.max_rounds}")
    print(f"terminal_reason={result.terminal_reason}")
    print(f"blue_summary={blue.summary}")
    print(f"red_claim={red.claim}")
    print(f"red_block_integration={red.block_integration}")
    print(f"referee_decision={referee.decision if referee is not None else 'none'}")
    print(f"referee_rationale={referee.rationale if referee is not None else 'none'}")
    for summary in result.round_summaries:
        print(f"round_{summary.round_number}_decision={summary.referee_decision}")
        print(f"round_{summary.round_number}_blue_summary={_truncate_for_output(summary.blue_summary)}")
        print(f"round_{summary.round_number}_red_claim={_truncate_for_output(summary.red_claim)}")
        print(
            f"round_{summary.round_number}_referee_rationale="
            f"{_truncate_for_output(summary.referee_rationale)}"
        )
    print(f"blackboard_path={blackboard_path}")
