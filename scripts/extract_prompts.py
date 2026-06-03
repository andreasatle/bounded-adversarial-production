#!/usr/bin/env python3
"""Extract and render agent prompts from a baps workspace.

Reads baps-config.json, state/state.json, and blackboard/games.jsonl from the
given workspace and reconstructs the prompts that would be sent to each role:
create_game, blue, red, and referee.

Red and referee prompts require a delta.  The script uses the current_best_delta
from the most recent play_game event; if that is absent it falls back to the last
attempt's blue_delta.  If no delta is found those two prompts are skipped.

Usage:
    uv run scripts/extract_prompts.py <workspace>
    uv run scripts/extract_prompts.py <workspace> --output prompts/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Workspace loading
# ---------------------------------------------------------------------------


def _load_workspace(workspace: Path) -> tuple[dict, dict, list[dict]]:
    config_path = workspace / "baps-config.json"
    state_path = workspace / "state" / "state.json"
    blackboard_path = workspace / "blackboard" / "games.jsonl"

    if not config_path.exists():
        sys.exit(f"error: no baps-config.json found in {workspace}")
    if not state_path.exists():
        sys.exit(f"error: no state/state.json found in {workspace}")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    state_raw = json.loads(state_path.read_text(encoding="utf-8"))

    events: list[dict] = []
    if blackboard_path.exists():
        for line in blackboard_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))

    return config, state_raw, events


def _last_event(events: list[dict], kind: str) -> dict | None:
    for event in reversed(events):
        if event.get("event") == kind:
            return event
    return None


# ---------------------------------------------------------------------------
# Delta reconstruction
# ---------------------------------------------------------------------------


def _reconstruct_delta(delta_dict: dict | None, project_type: str):
    if delta_dict is None:
        return None
    text = json.dumps(delta_dict)
    try:
        if project_type == "coding":
            from baps.adapters.coding.parsing import parse_coding_delta_json

            return parse_coding_delta_json(text)
        if project_type == "document":
            from baps.adapters.document_adapter import parse_document_delta_json

            return parse_document_delta_json(text)
    except Exception as exc:
        print(f"warning: could not reconstruct delta — {exc}", file=sys.stderr)
    return None


def _find_delta(play_event: dict, project_type: str):
    delta = _reconstruct_delta(play_event.get("current_best_delta"), project_type)
    if delta is not None:
        return delta
    for attempt in reversed(play_event.get("attempts", [])):
        delta = _reconstruct_delta(attempt.get("blue_delta"), project_type)
        if delta is not None:
            return delta
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render agent prompts from a baps workspace.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "workspace", type=Path, help="Workspace directory (contains baps-config.json)"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Write each prompt to <name>.txt in this directory (default: print to stdout)",
    )
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    config_dict, state_raw, events = _load_workspace(workspace)

    from baps.core.run_config import RunConfig
    from baps.adapters.project_adapter import resolve_project_type_adapter
    from baps.core.prompts import (
        render_create_game_prompt,
        render_red_prompt,
        render_referee_prompt,
        render_red_prompt_supplement_with_adapter,
        render_referee_prompt_supplement_with_adapter,
    )
    from baps.state.state import GameSpec, RedFinding, State

    project_type = config_dict.get("project_type", "coding")
    output_val = config_dict.get("output", str(workspace / "output" / "project"))

    config = RunConfig(
        workspace=workspace,
        project_type=project_type,
        artifact_id=config_dict.get("artifact_id", ""),
        language=config_dict.get("language", ""),
        northstar_markdown=config_dict.get("northstar_markdown", ""),
        goal=config_dict.get("goal", ""),
        output_path=Path(output_val),
        max_iterations=int(config_dict.get("max_iterations", 10)),
    )

    state = State.model_validate(state_raw)
    adapter = resolve_project_type_adapter(project_type)
    adapter_config = config.to_adapter_config()

    prompts: dict[str, str] = {}
    views: dict[str, str] = {}

    # --- create_game ---
    cg_view = adapter.build_create_game_state_view(state, adapter_config)
    views["create_game"] = cg_view.content
    prompts["create_game"] = render_create_game_prompt(config, state, cg_view)

    # --- blue / red / referee require a game_spec ---
    last_play = _last_event(events, "play_game")
    if last_play and last_play.get("game_spec"):
        game_spec = GameSpec.model_validate(last_play["game_spec"])
        play_view = adapter.build_state_view(state, game_spec)
        views["play_game"] = play_view.content

        prompts["blue"] = adapter.render_blue_prompt(
            play_view, game_spec, attempt_number=1, previous_feedback=None
        )

        delta = _find_delta(last_play, project_type)
        if delta is not None:
            red_supplement = render_red_prompt_supplement_with_adapter(
                adapter, play_view, game_spec, delta, None
            )
            prompts["red"] = render_red_prompt(
                play_view, game_spec, delta, prompt_supplement=red_supplement
            )

            red_finding = None
            for attempt in reversed(last_play.get("attempts", [])):
                if attempt.get("red_finding"):
                    red_finding = RedFinding.model_validate(attempt["red_finding"])
                    break

            if red_finding is not None:
                ref_supplement = render_referee_prompt_supplement_with_adapter(
                    adapter, play_view, game_spec, delta, None
                )
                prompts["referee"] = render_referee_prompt(
                    play_view,
                    game_spec,
                    delta,
                    red_finding,
                    prompt_supplement=ref_supplement,
                )
            else:
                print(
                    "note: no red_finding in blackboard — skipping referee prompt",
                    file=sys.stderr,
                )
        else:
            print(
                "note: no delta in blackboard — skipping red and referee prompts",
                file=sys.stderr,
            )
    else:
        print(
            "note: no play_game event in blackboard — skipping blue, red, and referee prompts",
            file=sys.stderr,
        )

    # --- emit ---
    _ROLE_ORDER = ["create_game", "blue", "red", "referee"]
    ordered_prompts = [(r, prompts[r]) for r in _ROLE_ORDER if r in prompts]
    ordered_views = [(k, views[k]) for k in ["create_game", "play_game"] if k in views]

    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        for name, text in ordered_prompts:
            out_path = args.output / f"prompt_{name}.txt"
            out_path.write_text(text, encoding="utf-8")
            print(f"wrote {out_path}")
        for name, text in ordered_views:
            out_path = args.output / f"view_{name}.txt"
            out_path.write_text(text, encoding="utf-8")
            print(f"wrote {out_path}")
    else:
        sep = "=" * 60
        for name, text in ordered_prompts:
            print(f"\n{sep}")
            print(f"  PROMPT: {name.upper()}")
            print(f"{sep}\n")
            print(text)
        for name, text in ordered_views:
            print(f"\n{sep}")
            print(f"  STATE VIEW: {name.upper()}")
            print(f"{sep}\n")
            print(text)


if __name__ == "__main__":
    main()
