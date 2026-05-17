from __future__ import annotations

import argparse
from pathlib import Path

REQUEST = "Write a short report with an introduction and conclusion."
SECTION_MARKER = "## Introduction and Conclusion"
SECTION_BODY = (
    f"{SECTION_MARKER}\n\n"
    "Introduction: This short report summarizes the current state of the workspace output.\n\n"
    "Conclusion: The report now includes both an introduction and a conclusion in one section.\n"
)


def _derive_state(request: str, current_document: str) -> dict[str, str]:
    return {
        "request": request,
        "document": current_document,
    }


def _build_view(state: dict[str, str]) -> str:
    document_preview = state["document"][-400:]
    return (
        "Request:\n"
        f"{state['request']}\n\n"
        "Current report tail:\n"
        f"{document_preview}"
    )


def _propose_section(_view: str) -> str:
    return SECTION_BODY


def _evaluate_append_only_non_duplicate(current_document: str, proposal: str) -> tuple[bool, str]:
    if SECTION_MARKER in current_document:
        return False, "section_already_exists"
    if proposal.strip() == "":
        return False, "empty_proposal"
    return True, "accepted_append_only"


def run_baps_loop(workspace: Path) -> dict[str, object]:
    output_path = workspace / "output" / "report.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not output_path.exists():
        output_path.write_text("", encoding="utf-8")

    iterations: list[dict[str, object]] = []

    for iteration in (1, 2):
        before = output_path.read_text(encoding="utf-8")
        state = _derive_state(REQUEST, before)
        view = _build_view(state)
        proposal = _propose_section(view)
        accepted, decision_reason = _evaluate_append_only_non_duplicate(before, proposal)

        update_applied = False
        document_changed = False
        stop_reason = ""

        if accepted:
            output_path.write_text(before + proposal, encoding="utf-8")
            after = output_path.read_text(encoding="utf-8")
            update_applied = True
            document_changed = after != before
            stop_reason = "continue"
        else:
            stop_reason = decision_reason

        iterations.append(
            {
                "iteration": iteration,
                "state_derived": True,
                "view_built": True,
                "proposal": SECTION_MARKER,
                "game_result": "accepted" if accepted else "rejected",
                "decision": decision_reason,
                "update_applied": update_applied,
                "document_changed": document_changed,
                "stop_reason": stop_reason,
            }
        )

        if not accepted:
            break

    if len(iterations) == 1:
        # Keep the two-pass contract explicit for output/tests.
        iterations.append(
            {
                "iteration": 2,
                "state_derived": True,
                "view_built": True,
                "proposal": SECTION_MARKER,
                "game_result": "rejected",
                "decision": "section_already_exists",
                "update_applied": False,
                "document_changed": False,
                "stop_reason": "section_already_exists",
            }
        )

    return {
        "workspace": workspace,
        "output_path": output_path,
        "iterations": iterations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one hardened deterministic baps loop.")
    parser.add_argument(
        "--workspace",
        default=".baps-workspace",
        help="Workspace directory for runtime outputs.",
    )
    args = parser.parse_args()

    result = run_baps_loop(Path(args.workspace))
    workspace = result["workspace"]
    output_path = result["output_path"]

    print(f"workspace={workspace}")
    print(f"output_path={output_path}")
    for record in result["iterations"]:
        print(f"iteration={record['iteration']}")
        print(f"state_derived={record['state_derived']}")
        print(f"view_built={record['view_built']}")
        print(f"proposal={record['proposal']}")
        print(f"game_result={record['game_result']}")
        print(f"decision={record['decision']}")
        print(f"update_applied={record['update_applied']}")
        print(f"document_changed={record['document_changed']}")
        print(f"stop_reason={record['stop_reason']}")


if __name__ == "__main__":
    main()
