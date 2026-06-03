"""Top-level lifecycle orchestration: config resolution, runtime assembly, run loop, and result emission."""

from __future__ import annotations

import argparse
import datetime
import logging
from dataclasses import dataclass
from pathlib import Path

from baps.core.orchestration import IterationRunResult
from baps.core.run_config import RunConfig, resolve_reset_targets, resolve_run_config
from baps.core.runtime import (
    active_model_info,
    build_runtime,
    run_project,
)
from baps.core.workspace import wipe_workspace_state, write_run_result
from baps.state.state import StopReason

logger = logging.getLogger(__name__)


@dataclass  # internal only — no serialization boundary
class StartRunSummary:
    """Collects outcome fields from a completed baps start lifecycle run for reporting."""

    workspace: Path
    project_type: str
    command: str
    goal: str
    output_path: Path
    max_iterations: int
    update_applied: bool = False
    state_changed: bool = False
    output_exported: bool = False
    output_changed: bool = False
    northstar_proposal_written: bool = False
    verification_run: bool = False
    verification_passed: bool = False
    verification_exit_code: int | None = None
    verification_command: str | None = None
    verification_cwd: str | None = None
    iterations_completed: int = 0
    stop_reason: StopReason = StopReason.NOT_RUN
    failed: bool = False

    def record_iteration_result(self, result: "IterationRunResult") -> None:
        """Update summary fields from the completed IterationRunResult."""
        self.update_applied = result.update_applied
        self.state_changed = result.state_changed
        self.output_exported = result.output_exported
        self.output_changed = result.output_changed
        self.northstar_proposal_written = result.northstar_proposal_written
        verification_result = result.verification_result
        self.verification_run = verification_result is not None
        if verification_result is not None:
            self.verification_passed = verification_result.passed
            self.verification_exit_code = verification_result.exit_code
            self.verification_command = verification_result.command
            self.verification_cwd = verification_result.cwd
        self.iterations_completed = result.iterations_completed
        self.stop_reason = result.stop_reason


def resolve_start_config(args: argparse.Namespace) -> RunConfig:
    """Resolve CLI args into a RunConfig, exiting with code 2 on validation error."""
    try:
        return resolve_run_config(args)
    except ValueError as exc:
        logger.error("%s", exc)
        raise SystemExit(2) from exc


def run_start_lifecycle(runtime, command: str) -> StartRunSummary:
    """Run the project iteration loop and return a summary of the outcome."""
    summary = StartRunSummary(
        workspace=runtime.config.workspace,
        project_type=runtime.config.project_type,
        command=command,
        goal=runtime.config.goal,
        output_path=runtime.config.output_path,
        max_iterations=runtime.config.max_iterations,
    )
    try:
        iteration_result = run_project(runtime)
        summary.record_iteration_result(iteration_result)
    except (ValueError, RuntimeError) as exc:
        logger.error("%s", exc)
        summary.stop_reason = StopReason.ERROR
        summary.failed = True
    return summary


def _print_start_summary(summary: StartRunSummary) -> None:
    """Print all summary fields to stdout as key=value lines."""
    print(f"workspace={summary.workspace}")
    print(f"project_type={summary.project_type}")
    print(f"command={summary.command}")
    print(f"goal={summary.goal}")
    print(f"output_path={summary.output_path}")
    print(f"max_iterations={summary.max_iterations}")
    print(f"update_applied={summary.update_applied}")
    print(f"state_changed={summary.state_changed}")
    print(f"output_exported={summary.output_exported}")
    print(f"output_changed={summary.output_changed}")
    print(f"northstar_proposal_written={summary.northstar_proposal_written}")
    print(f"verification_run={summary.verification_run}")
    print(f"iterations_completed={summary.iterations_completed}")
    print(f"verification_passed={summary.verification_passed}")
    print(f"verification_exit_code={summary.verification_exit_code}")
    print(f"verification_command={summary.verification_command}")
    print(f"verification_cwd={summary.verification_cwd}")
    print(f"stop_reason={summary.stop_reason}")


def _write_start_result(config: RunConfig, summary: StartRunSummary) -> None:
    """Write a structured run-result.json to the workspace from the summary and active model info."""
    model_info = active_model_info(config)
    result_data: dict[str, object] = {
        "stop_reason": summary.stop_reason,
        "verification_passed": summary.verification_passed
        if summary.verification_run
        else None,
        "verification_exit_code": summary.verification_exit_code,
        "iterations_completed": summary.iterations_completed,
        "backend": model_info["backend"],
        "model": model_info["model"],
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    write_run_result(config.workspace, result_data)


def emit_start_result(config: RunConfig, summary: StartRunSummary) -> None:
    """Print the start summary and write run-result.json."""
    _print_start_summary(summary)
    _write_start_result(config, summary)


def build_start_runtime(config: RunConfig):
    """Build the RuntimeContext for a start run, exiting with code 2 on error."""
    try:
        return build_runtime(config)
    except ValueError as exc:
        logger.error("%s", exc)
        raise SystemExit(2) from exc


def exit_if_failed(summary: StartRunSummary) -> None:
    """Raise SystemExit(2) if the summary indicates a failed run."""
    if summary.failed:
        raise SystemExit(2)


def start_project(args: argparse.Namespace) -> None:
    """Resolve config, build runtime, run the lifecycle, emit result, and exit on failure."""
    config = resolve_start_config(args)
    runtime = build_start_runtime(config)
    summary = run_start_lifecycle(runtime, command=str(args.command))
    emit_start_result(config, summary)
    exit_if_failed(summary)


def reset_project(args: argparse.Namespace) -> None:
    """Wipe workspace state and output, then print the reset summary."""
    try:
        workspace, output_path = resolve_reset_targets(args)
    except ValueError as exc:
        logger.error("%s", exc)
        raise SystemExit(2) from exc
    wipe_workspace_state(workspace, output_path)
    print(f"workspace={workspace}")
    print("command=reset")
    print("wiped=True")
