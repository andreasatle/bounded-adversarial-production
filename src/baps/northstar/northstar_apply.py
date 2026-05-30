from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_BLACKBOARD_DIR = "blackboard"
_NORTHSTAR_PROPOSALS_FILE = "northstar_proposals.jsonl"
_WORKSPACE_CONFIG_FILE = "baps-config.json"


def _load_proposals(workspace: Path) -> list[dict]:
    """Load and parse all NorthStar proposals from the blackboard JSONL file."""
    path = workspace / _BLACKBOARD_DIR / _NORTHSTAR_PROPOSALS_FILE
    if not path.exists():
        return []
    proposals = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                proposals.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return proposals


def _load_workspace_config(workspace: Path) -> dict:
    """Load and return the baps-config.json from the workspace, or an empty dict if missing."""
    path = workspace / _WORKSPACE_CONFIG_FILE
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_workspace_config(workspace: Path, config: dict) -> None:
    """Write config to baps-config.json, raising ValueError if the path would escape the workspace."""
    path = workspace / _WORKSPACE_CONFIG_FILE
    resolved = path.resolve()
    if not resolved.is_relative_to(workspace.resolve()):
        raise ValueError(f"config path escapes workspace: {path}")
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def _apply_proposal(workspace: Path, proposal: dict, dry_run: bool) -> None:
    """Apply a NorthStar proposal to the workspace config, or log the proposal if dry_run is True."""
    config = _load_workspace_config(workspace)
    if not config:
        logger.error("[apply-northstar] no workspace config found at %s", workspace / _WORKSPACE_CONFIG_FILE)
        sys.exit(1)

    logger.info("[apply-northstar] current NorthStar:\n%s", config.get('northstar_markdown', '(empty)'))
    logger.info("[apply-northstar] proposed NorthStar:\n%s", proposal['proposed_northstar'])

    if dry_run:
        logger.info("[apply-northstar] dry-run: no changes written.")
        return

    config["northstar_markdown"] = proposal["proposed_northstar"]
    _save_workspace_config(workspace, config)
    logger.info("[apply-northstar] workspace config updated: %s", workspace / _WORKSPACE_CONFIG_FILE)
    logger.info("[apply-northstar] NOTE: re-run 'baps-run init' or manually update the spec YAML to persist this NorthStar change across fresh workspaces.")


def main() -> None:
    """CLI entry point for baps-apply-northstar: list proposals and apply a chosen one."""
    _log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(level=_log_level, format="%(asctime)s %(levelname)-5s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    parser = argparse.ArgumentParser(
        description="Review and apply a NorthStar update proposal from a workspace blackboard."
    )
    parser.add_argument(
        "workspace",
        help="Path to the baps workspace directory.",
    )
    parser.add_argument(
        "--index", "-i",
        type=int,
        default=None,
        help="Index of the proposal to apply (0-based). Omit to list proposals interactively.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the proposal without writing any changes.",
    )
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    if not workspace.exists():
        logger.error("[apply-northstar] workspace not found: %s", workspace)
        sys.exit(1)

    proposals = _load_proposals(workspace)
    if not proposals:
        logger.info("[apply-northstar] no NorthStar proposals found in blackboard.")
        sys.exit(0)

    logger.info("[apply-northstar] found %d proposal(s):", len(proposals))
    for i, p in enumerate(proposals):
        created_at = p.get("created_at", "unknown")
        rationale = p.get("rationale", "")[:120].replace("\n", " ")
        logger.info("  [%d] %s  —  %s", i, created_at, rationale)

    if args.index is not None:
        idx = args.index
        if idx < 0 or idx >= len(proposals):
            logger.error("[apply-northstar] index %d out of range (0–%d)", idx, len(proposals) - 1)
            sys.exit(1)
        chosen = proposals[idx]
    else:
        print()
        raw = input(f"Enter proposal index to apply [0–{len(proposals) - 1}], or 'q' to quit: ").strip()
        if raw.lower() in ("q", "quit", ""):
            logger.info("[apply-northstar] aborted.")
            sys.exit(0)
        try:
            idx = int(raw)
        except ValueError:
            logger.error("[apply-northstar] invalid input: %r", raw)
            sys.exit(1)
        if idx < 0 or idx >= len(proposals):
            logger.error("[apply-northstar] index %d out of range", idx)
            sys.exit(1)
        chosen = proposals[idx]

    logger.info("[apply-northstar] rationale: %s", chosen.get('rationale', ''))

    if not args.dry_run and args.index is None:
        confirm = input("\nApply this proposal? [y/N] ").strip().lower()
        if confirm not in ("y", "yes"):
            logger.info("[apply-northstar] aborted.")
            sys.exit(0)

    _apply_proposal(workspace, chosen, dry_run=args.dry_run)
