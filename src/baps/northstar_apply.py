from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_BLACKBOARD_DIR = "blackboard"
_NORTHSTAR_PROPOSALS_FILE = "northstar_proposals.jsonl"
_WORKSPACE_CONFIG_FILE = "baps-config.json"


def _load_proposals(workspace: Path) -> list[dict]:
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
    path = workspace / _WORKSPACE_CONFIG_FILE
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_workspace_config(workspace: Path, config: dict) -> None:
    path = workspace / _WORKSPACE_CONFIG_FILE
    resolved = path.resolve()
    if not resolved.is_relative_to(workspace.resolve()):
        raise ValueError(f"config path escapes workspace: {path}")
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def _apply_proposal(workspace: Path, proposal: dict, dry_run: bool) -> None:
    config = _load_workspace_config(workspace)
    if not config:
        print(f"[apply-northstar] no workspace config found at {workspace / _WORKSPACE_CONFIG_FILE}", file=sys.stderr)
        sys.exit(1)

    print(f"\n[apply-northstar] current NorthStar:\n{config.get('northstar_markdown', '(empty)')}\n")
    print(f"[apply-northstar] proposed NorthStar:\n{proposal['proposed_northstar']}\n")

    if dry_run:
        print("[apply-northstar] dry-run: no changes written.")
        return

    config["northstar_markdown"] = proposal["proposed_northstar"]
    _save_workspace_config(workspace, config)
    print(f"[apply-northstar] workspace config updated: {workspace / _WORKSPACE_CONFIG_FILE}")
    print("[apply-northstar] NOTE: re-run 'baps-run init' or manually update the spec YAML to persist this NorthStar change across fresh workspaces.")


def main() -> None:
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
        print(f"[apply-northstar] workspace not found: {workspace}", file=sys.stderr)
        sys.exit(1)

    proposals = _load_proposals(workspace)
    if not proposals:
        print("[apply-northstar] no NorthStar proposals found in blackboard.")
        sys.exit(0)

    print(f"[apply-northstar] found {len(proposals)} proposal(s):\n")
    for i, p in enumerate(proposals):
        created_at = p.get("created_at", "unknown")
        rationale = p.get("rationale", "")[:120].replace("\n", " ")
        print(f"  [{i}] {created_at}  —  {rationale}")

    if args.index is not None:
        idx = args.index
        if idx < 0 or idx >= len(proposals):
            print(f"[apply-northstar] index {idx} out of range (0–{len(proposals) - 1})", file=sys.stderr)
            sys.exit(1)
        chosen = proposals[idx]
    else:
        print()
        raw = input(f"Enter proposal index to apply [0–{len(proposals) - 1}], or 'q' to quit: ").strip()
        if raw.lower() in ("q", "quit", ""):
            print("[apply-northstar] aborted.")
            sys.exit(0)
        try:
            idx = int(raw)
        except ValueError:
            print(f"[apply-northstar] invalid input: {raw!r}", file=sys.stderr)
            sys.exit(1)
        if idx < 0 or idx >= len(proposals):
            print(f"[apply-northstar] index {idx} out of range", file=sys.stderr)
            sys.exit(1)
        chosen = proposals[idx]

    print(f"\n[apply-northstar] rationale: {chosen.get('rationale', '')}")

    if not args.dry_run and args.index is None:
        confirm = input("\nApply this proposal? [y/N] ").strip().lower()
        if confirm not in ("y", "yes"):
            print("[apply-northstar] aborted.")
            sys.exit(0)

    _apply_proposal(workspace, chosen, dry_run=args.dry_run)
