from __future__ import annotations

import argparse
import logging
import os

from baps.core.lifecycle import reset_project, start_project
from baps.core.run_config import resolve_run_config
from baps.core.runtime import (
    RuntimeContext,
    _build_project_type_adapters,
    _initialize_project,
    _resolve_adapter_for_allowed_delta_type,
    _resolve_project_type_adapter,
    prepare_workspace as _prepare_workspace,
)
from baps.state.state_service import StateService
from baps.state.state_store import JsonStateStore


def _configure_runtime_logging() -> None:
    log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _add_start_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--spec", default=None, help="YAML spec path.")
    parser.add_argument(
        "--workspace", default=None,
        help="Workspace directory for runtime outputs.",
    )
    parser.add_argument(
        "--project-type", default=None,
        help="Project type (currently supported: document, coding, audit).",
    )
    parser.add_argument(
        "--artifact-id", default=None,
        help="Artifact id for project state.",
    )
    parser.add_argument(
        "--goal", default=None,
        help="Runtime goal text. Required if not set in spec or workspace config.",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output path (relative paths are resolved under workspace).",
    )
    parser.add_argument(
        "--max-iterations", type=int, default=None,
        help="Maximum loop iterations (must be >= 1).",
    )
    parser.add_argument(
        "--sandbox", default=None, choices=("docker", "none"),
        help="Sandbox mode for code execution: 'docker' (default) or 'none' (unsafe, prints warning).",
    )
    parser.add_argument(
        "--language", default=None,
        help="Language plugin for coding projects (e.g. python, zig). Required for coding project type.",
    )


def _build_cli_parser() -> argparse.ArgumentParser:
    from dotenv import load_dotenv

    load_dotenv()
    parser = argparse.ArgumentParser(
        description="baps — bounded adversarial production system.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run baps-run reset --spec examples/coding-project.yaml\n"
            "  uv run baps-run start --spec examples/coding-project.yaml\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    start_parser = subparsers.add_parser(
        "start",
        help=(
            "Initialize if needed, then run the game loop. "
            "Continues from existing state when present; "
            "initializes from scratch when the workspace is empty."
        ),
    )
    _add_start_args(start_parser)

    reset_parser = subparsers.add_parser(
        "reset",
        help=(
            "Wipe workspace state and output file, then exit. "
            "No model calls are made. "
            "Run 'start' afterwards to begin from a clean slate."
        ),
    )
    reset_parser.add_argument("--spec", default=None, help="YAML spec path.")
    reset_parser.add_argument("--workspace", default=None, help="Workspace directory.")
    reset_parser.add_argument(
        "--output", default=None,
        help="Output file to wipe (relative paths resolved under workspace).",
    )
    return parser


def main() -> None:
    _configure_runtime_logging()
    parser = _build_cli_parser()
    args = parser.parse_args()
    if args.command == "reset":
        reset_project(args)
        return
    start_project(args, create_state_fn=create_state, build_runtime_fn=_build_runtime)


def create_state(config):
    from baps.core.debug import _debug_print_create_state

    adapter = _resolve_project_type_adapter(config.project_type)
    state = adapter.create_initial_state(config.to_adapter_config())
    _debug_print_create_state(config=config, state=state)
    return state


def _build_runtime(config, create_state_fn=create_state) -> RuntimeContext:
    adapter = _resolve_project_type_adapter(config.project_type)
    state_service, current_state = _prepare_workspace(config, create_state_fn=create_state_fn)
    return RuntimeContext(
        config=config,
        adapter=adapter,
        state_service=state_service,
        initial_state=current_state,
    )


if __name__ == "__main__":
    main()
