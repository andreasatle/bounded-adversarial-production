#!/usr/bin/env python3
"""Print a typical prompt for each baps agent role using placeholder inputs.

No workspace or live model required.  Free-text fields use angle-bracket
placeholders so the prompt structure is visible without fabricated content.

Usage:
    uv run scripts/show_prompts.py
    uv run scripts/show_prompts.py --output prompts/
"""

from __future__ import annotations

import argparse
from pathlib import Path

# ---------------------------------------------------------------------------
# Placeholder scenario
# ---------------------------------------------------------------------------

_GOAL = "<goal>"
_NORTHSTAR = "<northstar_markdown>"
_ARTIFACT_ID = "artifact-id"
_OBJECTIVE = "<objective>"
_SUCCESS_CONDITION = "<success_condition>"
_SECTION_TITLE = "Section Title"
_SECTION_BODY = "<section_body>"


def _make_config():
    from baps.core.run_config import RunConfig

    return RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id=_ARTIFACT_ID,
        northstar_markdown=_NORTHSTAR,
        goal=_GOAL,
        output_path=Path(".baps-workspace/output/spec.md"),
        max_iterations=10,
    )


def _make_state():
    from baps.state.state import DocumentArtifact, State

    return State(artifacts=(DocumentArtifact(id=_ARTIFACT_ID),))


def _make_game_spec():
    from baps.state.state import GameSpec

    return GameSpec(
        objective=_OBJECTIVE,
        target_artifact_id=_ARTIFACT_ID,
        allowed_delta_type="DeltaDocumentState",
        success_condition=_SUCCESS_CONDITION,
        max_words=400,
        target_entity="<target_entity>",
    )


def _make_delta():
    from baps.state.state import AppendSectionDelta, DeltaDocumentState, Section

    return DeltaDocumentState(
        artifact_id=_ARTIFACT_ID,
        operation="append_section",
        payload=AppendSectionDelta(
            section=Section(title=_SECTION_TITLE, body=_SECTION_BODY)
        ),
    )


def _make_red_finding():
    from baps.state.state import Disposition, RedFinding

    return RedFinding(
        disposition=Disposition.revise,
        rationale="<red_rationale>",
        success_condition_met=False,
        findings=("<red_finding_1>", "<red_finding_2>"),
    )


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def build_prompts() -> dict[str, str]:
    from baps.adapters.document_adapter import DocumentProjectAdapter
    from baps.core.prompts import (
        render_create_game_prompt,
        render_create_game_red_prompt,
        render_red_prompt,
        render_red_prompt_supplement_with_adapter,
        render_referee_prompt,
        render_referee_prompt_supplement_with_adapter,
    )

    config = _make_config()
    state = _make_state()
    spec = _make_game_spec()
    delta = _make_delta()
    red_finding = _make_red_finding()
    adapter = DocumentProjectAdapter()
    adapter_config = config.to_adapter_config()

    cg_view = adapter.build_create_game_state_view(state, adapter_config)
    play_view = adapter.build_state_view(state, spec)

    red_supplement = render_red_prompt_supplement_with_adapter(
        adapter, play_view, spec, delta, None
    )
    ref_supplement = render_referee_prompt_supplement_with_adapter(
        adapter, play_view, spec, delta, None
    )

    return {
        "create_game": render_create_game_prompt(
            config, state, cg_view, adapter=adapter
        ),
        "create_game_red": render_create_game_red_prompt(cg_view, spec, config),
        "blue": adapter.render_blue_prompt(
            play_view, spec, attempt_number=1, previous_feedback=None
        ),
        "red": render_red_prompt(
            play_view, spec, delta, prompt_supplement=red_supplement
        ),
        "referee": render_referee_prompt(
            play_view, spec, delta, red_finding, prompt_supplement=ref_supplement
        ),
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_ROLE_ORDER = ["create_game", "create_game_red", "blue", "red", "referee"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Write each prompt to <role>.txt in this directory (default: stdout)",
    )
    args = parser.parse_args()

    prompts = build_prompts()
    ordered = [(r, prompts[r]) for r in _ROLE_ORDER if r in prompts]

    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        for name, text in ordered:
            out_path = args.output / f"{name}.txt"
            out_path.write_text(text, encoding="utf-8")
            print(f"wrote {out_path}")
    else:
        sep = "=" * 72
        for name, text in ordered:
            print(f"\n{sep}")
            print(f"  ROLE: {name.upper()}")
            print(f"{sep}\n")
            print(text)


if __name__ == "__main__":
    main()
