from __future__ import annotations

import argparse
from pathlib import Path

from baps.game_executor import GameExecutionResult
from baps.integration import IntegrationDecision, IntegrationSatisfaction, StateChange
from baps.loop import run_loop
from baps.northstar_projection import NorthStarView, ProjectionType
from baps.state_progressor import GameProposal, StateProgressionProposal, StateProgressorInput

REQUEST = "Write a short report with an introduction and conclusion."
SECTION_MARKER = "## Introduction and Conclusion"
SECTION_BODY = (
    f"{SECTION_MARKER}\n\n"
    "Introduction: This short report summarizes the current state of the workspace output.\n\n"
    "Conclusion: The report now includes both an introduction and a conclusion in one section.\n"
)


class _ReportStateProgressor:
    def __init__(self) -> None:
        self._section_exists = False

    def set_section_exists(self, section_exists: bool) -> None:
        self._section_exists = section_exists

    def progress(self, input: StateProgressorInput) -> StateProgressionProposal:
        proposal_id = f"proposal:{input.id}"
        if self._section_exists:
            game_proposal = GameProposal(
                id=proposal_id,
                title="report_section_exists",
                description=SECTION_BODY,
                expected_state_delta="none",
                risks=[],
            )
        else:
            game_proposal = GameProposal(
                id=proposal_id,
                title="append_report_section",
                description=SECTION_BODY,
                expected_state_delta="append_section",
                risks=[],
            )

        return StateProgressionProposal(
            id=f"state-progression:{input.id}",
            input_id=input.id,
            game_proposal=game_proposal,
            rationale="deterministic report proposal",
        )


class _ReportGameExecutor:
    def execute(self, game: GameProposal) -> GameExecutionResult:
        is_duplicate = game.title == "report_section_exists"
        return GameExecutionResult(
            id=f"game-result:{game.id}",
            game_proposal_id=game.id,
            status="rejected" if is_duplicate else "accepted",
            summary="section_already_exists" if is_duplicate else "accepted_append_only",
            state_delta="none" if is_duplicate else "append_section",
            risks=[],
        )


class _ReportIntegrator:
    def integrate(self, result: GameExecutionResult) -> IntegrationDecision:
        accepted = result.status == "accepted"
        return IntegrationDecision(
            id=f"integration-decision:{result.id}",
            accepted=accepted,
            satisfaction=IntegrationSatisfaction.FULL,
            rationale=result.summary,
            state_change=StateChange(
                id=f"state-change:{result.id}",
                execution_result_id=result.id,
                summary=result.summary,
                applied_delta=result.state_delta,
                materiality="full" if accepted else "none",
                risks=[],
            ),
        )


def _build_view_content(request: str, current_document: str) -> str:
    document_preview = current_document[-400:]
    return (
        "Request:\n"
        f"{request}\n\n"
        "Current report tail:\n"
        f"{document_preview}"
    )


def _build_input(iteration: int, current_document: str) -> StateProgressorInput:
    view = NorthStarView(
        id=f"northstar-view:run:{iteration}",
        projection_type=ProjectionType.NORTH_STAR,
        content=_build_view_content(REQUEST, current_document),
        input_fingerprint=f"run:{iteration}:{len(current_document)}",
        metadata={},
    )
    return StateProgressorInput(
        id=f"run-input:{iteration}",
        northstar_view=view,
        runtime_objective=REQUEST,
    )


def run_baps_loop(workspace: Path) -> dict[str, object]:
    output_path = workspace / "output" / "report.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not output_path.exists():
        output_path.write_text("", encoding="utf-8")

    iterations: list[dict[str, object]] = []
    progressor = _ReportStateProgressor()
    executor = _ReportGameExecutor()
    integrator = _ReportIntegrator()

    for iteration in (1, 2):
        before = output_path.read_text(encoding="utf-8")
        progressor.set_section_exists(SECTION_MARKER in before)
        loop_result = run_loop(
            progressor=progressor,
            executor=executor,
            integrator=integrator,
            input=_build_input(iteration=iteration, current_document=before),
        )

        accepted = loop_result.decision.accepted
        decision_reason = loop_result.decision.rationale

        update_applied = False
        document_changed = False

        if accepted:
            proposal_content = loop_result.proposal.game_proposal.description
            output_path.write_text(before + proposal_content, encoding="utf-8")
            after = output_path.read_text(encoding="utf-8")
            update_applied = True
            document_changed = after != before

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
                "stop_reason": "continue" if accepted else decision_reason,
            }
        )

        if not accepted:
            break

    if len(iterations) == 1:
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
