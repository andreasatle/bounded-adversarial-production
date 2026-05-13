from __future__ import annotations

import argparse
import os
from pathlib import Path

from baps.blackboard import Blackboard
from baps.example_roles import make_prompt_blue_role, make_prompt_red_role, make_prompt_referee_role
from baps.game_service import GameService
from baps.game_types import (
    GameDefinition,
    get_builtin_game_definition,
    load_game_definition,
)
from baps.models import OllamaClient
from baps.prompt_assembly import PromptSection, PromptSpec, assemble_prompt
from baps.run_specs import RunSpec, load_run_spec
from baps.runtime import RuntimeEngine, build_game_response
from baps.schemas import GameContract, GameRequest, GameState, Target
from baps.state_sources import (
    DirectoryStateSourceAdapter,
    GitRepoStateSourceAdapter,
    JsonlEventLogStateSourceAdapter,
    MarkdownFileStateSourceAdapter,
    RoutingStateSourceAdapter,
    load_state_manifest,
)


def _truncate_for_output(value: str, limit: int = 200) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _max_rounds_type(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("--max-rounds must be >= 1")
    return parsed


def _resolve_with_run_spec(
    *,
    args: argparse.Namespace,
    run_spec: RunSpec | None,
    parser: argparse.ArgumentParser,
) -> dict:
    game = run_spec.game if run_spec is not None else None
    model_cfg = run_spec.model if run_spec is not None else None
    state_cfg = run_spec.state if run_spec is not None else None

    subject = args.subject if args.subject is not None else (game.subject if game is not None else None)
    goal = args.goal if args.goal is not None else (game.goal if game is not None else None)
    target_kind = (
        args.target_kind if args.target_kind is not None else (game.target_kind if game is not None else None)
    )
    if subject is None:
        parser.error("--subject is required when not provided by --run-spec")
    if goal is None:
        parser.error("--goal is required when not provided by --run-spec")
    if target_kind is None:
        parser.error("--target-kind is required when not provided by --run-spec")

    target_ref = args.target_ref if args.target_ref is not None else (game.target_ref if game is not None else None)
    model = (
        args.model
        if args.model is not None
        else (
            model_cfg.name
            if model_cfg is not None and model_cfg.name
            else os.getenv("BAPS_OLLAMA_MODEL", "gemma3")
        )
    )
    base_url = (
        args.base_url
        if args.base_url is not None
        else (
            model_cfg.base_url
            if model_cfg is not None and model_cfg.base_url
            else os.getenv("BAPS_OLLAMA_BASE_URL", "http://localhost:11434")
        )
    )
    game_type = args.game_type if args.game_type is not None else (game.type if game is not None else "documentation-refinement")
    max_rounds = args.max_rounds if args.max_rounds is not None else (game.max_rounds if game is not None else 1)
    red_material = args.red_material if args.red_material is not None else (game.red_material if game is not None else True)
    game_definition_file = (
        args.game_definition_file
        if args.game_definition_file is not None
        else (run_spec.game_definition_file if run_spec is not None else None)
    )

    run_spec_context_files = run_spec.context_files if run_spec is not None else []
    context_files = [*run_spec_context_files, *args.context_file]

    run_spec_state_manifest = state_cfg.manifest if state_cfg is not None else None
    state_manifest = args.state_manifest if args.state_manifest is not None else run_spec_state_manifest
    run_spec_state_sources = state_cfg.sources if state_cfg is not None else []
    state_source = [*run_spec_state_sources, *args.state_source]

    return {
        "subject": subject,
        "goal": goal,
        "target_kind": target_kind,
        "target_ref": target_ref,
        "model": model,
        "base_url": base_url,
        "game_type": game_type,
        "max_rounds": max_rounds,
        "red_material": red_material,
        "game_definition_file": game_definition_file,
        "context_files": context_files,
        "state_manifest": state_manifest,
        "state_source": state_source,
    }


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
    parser.add_argument("--run-spec")
    parser.add_argument("--subject")
    parser.add_argument("--goal")
    parser.add_argument("--target-kind")
    parser.add_argument("--target-ref")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--blackboard-path", default="blackboard/play-game-events.jsonl")
    parser.add_argument("--context-file", action="append", default=[])
    parser.add_argument("--state-manifest")
    parser.add_argument("--state-source", action="append", default=[])
    parser.add_argument("--game-type")
    parser.add_argument("--game-definition-file")
    parser.add_argument("--max-rounds", type=_max_rounds_type)
    parser.add_argument("--red-material", action="store_true", default=None)
    parser.add_argument("--red-non-material", action="store_false", dest="red_material")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    blackboard_path = Path(args.blackboard_path)
    run_spec = load_run_spec(Path(args.run_spec)) if args.run_spec else None
    resolved = _resolve_with_run_spec(args=args, run_spec=run_spec, parser=parser)
    if resolved["state_source"] and not resolved["state_manifest"]:
        parser.error("--state-source requires --state-manifest")
    if resolved["state_manifest"] and not resolved["state_source"]:
        parser.error("--state-manifest requires at least one --state-source")

    shared_context = load_context_files(resolved["context_files"])
    state_manifest = (
        load_state_manifest(Path(resolved["state_manifest"]))
        if resolved["state_manifest"]
        else None
    )

    resolved_game_definition = (
        load_game_definition(Path(resolved["game_definition_file"]))
        if resolved["game_definition_file"]
        else get_builtin_game_definition(resolved["game_type"])
    )
    service = GameService(
        model_client=OllamaClient(model=resolved["model"], base_url=resolved["base_url"]),
        blackboard=Blackboard(blackboard_path),
        game_definition=resolved_game_definition,
        max_rounds=resolved["max_rounds"],
        shared_context=shared_context,
        red_material=resolved["red_material"],
        state_manifest=state_manifest,
        state_adapter=(
            RoutingStateSourceAdapter(
                [
                    MarkdownFileStateSourceAdapter(),
                    JsonlEventLogStateSourceAdapter(),
                    DirectoryStateSourceAdapter(),
                    GitRepoStateSourceAdapter(),
                ]
            )
            if state_manifest is not None
            else None
        ),
    )
    request = GameRequest(
        game_type=resolved["game_type"],
        subject=resolved["subject"],
        goal=resolved["goal"],
        target_kind=resolved["target_kind"],
        target_ref=resolved["target_ref"] or "",
        state_source_ids=resolved["state_source"],
    )
    result = service.play(request)

    print(f"game_id={result.game_id}")
    print(f"run_id={result.run_id}")
    print(f"subject={resolved['subject']}")
    print(f"goal={resolved['goal']}")
    print(f"target_kind={resolved['target_kind']}")
    print(f"target_ref={resolved['target_ref']}")
    print(f"game_type={resolved['game_type']}")
    print(f"game_definition_id={resolved_game_definition.id}")
    print(f"game_definition_name={resolved_game_definition.name}")
    print(f"rounds_played={result.rounds_played}")
    print(f"max_rounds={result.max_rounds}")
    print(f"terminal_reason={result.terminal_reason}")
    print(f"blue_summary={result.final_blue_summary}")
    print(f"red_claim={result.final_red_claim}")
    print(f"red_block_integration={result.final_decision.decision == 'reject'}")
    print(f"referee_decision={result.final_decision.decision}")
    print(f"referee_rationale={result.final_decision.rationale}")
    for summary in result.round_summaries:
        print(f"round_{summary.round_number}_decision={summary.referee_decision}")
        print(f"round_{summary.round_number}_blue_summary={_truncate_for_output(summary.blue_summary)}")
        print(f"round_{summary.round_number}_red_claim={_truncate_for_output(summary.red_claim)}")
        print(
            f"round_{summary.round_number}_referee_rationale="
            f"{_truncate_for_output(summary.referee_rationale)}"
        )
    print(f"blackboard_path={blackboard_path}")
