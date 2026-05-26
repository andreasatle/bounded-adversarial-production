from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from baps.northstar_apply import (
    _apply_proposal,
    _load_proposals,
    _save_workspace_config,
)


# ---------------------------------------------------------------------------
# _load_proposals
# ---------------------------------------------------------------------------

def test_load_proposals_returns_empty_when_file_missing(tmp_path: Path) -> None:
    assert _load_proposals(tmp_path) == []


def test_load_proposals_parses_valid_jsonl(tmp_path: Path) -> None:
    bb = tmp_path / "blackboard"
    bb.mkdir()
    (bb / "northstar_proposals.jsonl").write_text(
        '{"rationale": "r1", "proposed_northstar": "ns1"}\n'
        '{"rationale": "r2", "proposed_northstar": "ns2"}\n',
        encoding="utf-8",
    )
    proposals = _load_proposals(tmp_path)
    assert len(proposals) == 2
    assert proposals[0]["rationale"] == "r1"
    assert proposals[1]["proposed_northstar"] == "ns2"


def test_load_proposals_skips_malformed_lines(tmp_path: Path) -> None:
    bb = tmp_path / "blackboard"
    bb.mkdir()
    (bb / "northstar_proposals.jsonl").write_text(
        '{"rationale": "good"}\n'
        'NOT VALID JSON\n'
        '{"rationale": "also good"}\n',
        encoding="utf-8",
    )
    proposals = _load_proposals(tmp_path)
    assert len(proposals) == 2
    assert proposals[0]["rationale"] == "good"
    assert proposals[1]["rationale"] == "also good"


def test_load_proposals_skips_blank_lines(tmp_path: Path) -> None:
    bb = tmp_path / "blackboard"
    bb.mkdir()
    (bb / "northstar_proposals.jsonl").write_text(
        '{"rationale": "ok"}\n\n   \n',
        encoding="utf-8",
    )
    assert len(_load_proposals(tmp_path)) == 1


# ---------------------------------------------------------------------------
# _save_workspace_config
# ---------------------------------------------------------------------------

def test_save_workspace_config_writes_json(tmp_path: Path) -> None:
    config = {"northstar_markdown": "# Goal\nDo things.", "goal": "test"}
    _save_workspace_config(tmp_path, config)
    written = json.loads((tmp_path / "baps-config.json").read_text(encoding="utf-8"))
    assert written == config


def test_save_workspace_config_accepts_valid_workspace(tmp_path: Path) -> None:
    _save_workspace_config(tmp_path, {"key": "value"})
    assert (tmp_path / "baps-config.json").exists()


def test_save_workspace_config_rejects_escape_via_symlink(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.json"
    # baps-config.json inside workspace is a symlink pointing outside
    (workspace / "baps-config.json").symlink_to(outside)
    with pytest.raises(ValueError, match="escapes workspace"):
        _save_workspace_config(workspace, {"key": "value"})


def test_save_workspace_config_rejects_traversal_via_workspace_symlink(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    # workspace symlink points to outside directory, making baps-config.json
    # resolve outside the symlink target
    inner = outside / "inner"
    inner.mkdir()
    workspace = tmp_path / "workspace_link"
    workspace.symlink_to(inner)
    # baps-config.json is a symlink to real_dir/baps-config.json (outside inner)
    (inner / "baps-config.json").symlink_to(real_dir / "baps-config.json")
    with pytest.raises(ValueError, match="escapes workspace"):
        _save_workspace_config(workspace, {"key": "value"})


# ---------------------------------------------------------------------------
# _apply_proposal
# ---------------------------------------------------------------------------

def test_apply_proposal_dry_run_does_not_write(tmp_path: Path, caplog) -> None:
    config = {"northstar_markdown": "old northstar", "goal": "test"}
    (tmp_path / "baps-config.json").write_text(json.dumps(config), encoding="utf-8")
    with caplog.at_level(logging.INFO):
        _apply_proposal(tmp_path, {"proposed_northstar": "new northstar", "rationale": "better"}, dry_run=True)
    written = json.loads((tmp_path / "baps-config.json").read_text(encoding="utf-8"))
    assert written["northstar_markdown"] == "old northstar"
    assert "dry-run" in caplog.text


def test_apply_proposal_writes_northstar_to_config(tmp_path: Path) -> None:
    config = {"northstar_markdown": "old", "goal": "preserved"}
    (tmp_path / "baps-config.json").write_text(json.dumps(config), encoding="utf-8")
    _apply_proposal(tmp_path, {"proposed_northstar": "new northstar", "rationale": "r"}, dry_run=False)
    written = json.loads((tmp_path / "baps-config.json").read_text(encoding="utf-8"))
    assert written["northstar_markdown"] == "new northstar"
    assert written["goal"] == "preserved"


def test_apply_proposal_exits_when_config_missing(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _apply_proposal(tmp_path, {"proposed_northstar": "ns", "rationale": "r"}, dry_run=False)
    assert exc_info.value.code == 1
