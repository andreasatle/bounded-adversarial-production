"""Tests for blackboard event writing in create_game and play_game."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from baps.adapters.project_adapter import VerificationResult
from baps.core.parsers import NoNewGameError
from baps.core.run import create_state
from baps.core.run_config import RunConfig
from baps.game.engine import VERIFICATION_SUMMARY_CAP, create_game, play_game
from baps.models.models import FakeModelClient, ToolCall
from baps.state.state import GameSpec


def _make_play_game_config(workspace: Path) -> RunConfig:
    return RunConfig(
        workspace=workspace,
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=workspace / "output" / "report.md",
        max_iterations=1,
        spec_path=None,
    )


def _make_document_game_spec(**kwargs) -> GameSpec:
    return GameSpec(
        objective="Add introduction section",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Introduction section must be present.",
        **kwargs,
    )


def test_create_game_writes_create_game_blackboard_event(tmp_path: Path) -> None:
    config = RunConfig(
        workspace=tmp_path / "ws-cg-bb",
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=tmp_path / "ws-cg-bb" / "output" / "report.md",
        max_iterations=1,
    )
    state = create_state(config)
    create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"kind":"game_spec","objective":"Close the gap","target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"Section present."}'
            ]
        ),
    )

    games_path = config["workspace"] / "blackboard" / "games.jsonl"
    assert games_path.exists(), "games.jsonl must be written by create_game"
    entry = json.loads(games_path.read_text(encoding="utf-8").strip())

    assert entry["event"] == "create_game"
    assert "created_at" in entry
    assert entry["depth"] == 0
    assert entry["context_chain"] == []
    assert "state_view_fingerprint" in entry
    assert entry["state_view_fingerprint"] != ""
    assert entry["result_type"] == "game_spec"
    assert entry["result"]["objective"] == "Close the gap"
    assert entry["result"]["target_artifact_id"] == "main-document"
    assert "model_used" in entry


def test_create_game_writes_no_new_game_event(tmp_path: Path) -> None:
    config = RunConfig(
        workspace=tmp_path / "ws-nng-bb",
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=tmp_path / "ws-nng-bb" / "output" / "report.md",
        max_iterations=1,
    )
    state = create_state(config)
    with pytest.raises(NoNewGameError):
        create_game(
            config,
            state,
            model_client=FakeModelClient(
                ['{"kind": "no_new_game", "reason": "All gaps closed."}']
            ),
        )

    games_path = config["workspace"] / "blackboard" / "games.jsonl"
    assert games_path.exists()
    entry = json.loads(games_path.read_text(encoding="utf-8").strip())
    assert entry["event"] == "create_game"
    assert entry["result_type"] == "no_new_game"
    assert entry["result"] is None
    assert "created_at" in entry


def test_create_game_writes_decompose_spec_event(tmp_path: Path) -> None:
    config = RunConfig(
        workspace=tmp_path / "ws-dc-bb",
        project_type="document",
        artifact_id="main-document",
        goal="Write a long report.",
        northstar_markdown="# Goal\n\nWrite a long report.",
        output_path=tmp_path / "ws-dc-bb" / "output" / "report.md",
        max_iterations=1,
    )
    state = create_state(config)
    create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"kind": "decompose", "rationale": "Too large", '
                '"sub_gaps": [{"description": "Part one"}, {"description": "Part two"}]}'
            ]
        ),
    )

    games_path = config["workspace"] / "blackboard" / "games.jsonl"
    assert games_path.exists()
    entry = json.loads(games_path.read_text(encoding="utf-8").strip())
    assert entry["event"] == "create_game"
    assert entry["result_type"] == "decompose_spec"
    assert entry["result"]["rationale"] == "Too large"
    assert len(entry["result"]["sub_gaps"]) == 2
    assert entry["result"]["sub_gaps"][0]["description"] == "Part one"


def test_play_game_writes_play_game_blackboard_event(tmp_path: Path) -> None:
    workspace = tmp_path / "ws-pg-bb"
    config = RunConfig(
        workspace=workspace,
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=workspace / "output" / "report.md",
        max_iterations=1,
    )
    state = create_state(config)
    game_spec = GameSpec(
        objective="Add introduction section",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Introduction section must be present.",
    )
    play_game(state, game_spec, config=config)

    games_path = workspace / "blackboard" / "games.jsonl"
    assert games_path.exists(), "games.jsonl must be written by play_game"
    entry = json.loads(games_path.read_text(encoding="utf-8").strip())

    assert entry["event"] == "play_game"
    assert "game_id" in entry
    assert "created_at" in entry
    assert entry["depth"] == 0
    assert entry["context_chain"] == []
    assert "game_spec" in entry
    assert entry["game_spec"]["objective"] == "Add introduction section"
    assert isinstance(entry["attempts"], list)
    assert len(entry["attempts"]) >= 1
    attempt = entry["attempts"][0]
    assert attempt["attempt_number"] == 1
    assert "blue_delta" in attempt
    assert "red_finding" in attempt
    assert "referee_decision" in attempt
    assert entry["final_disposition"] in ("accepted", "rejected", "no_delta")
    assert "current_best_delta" in entry
    assert "integration_eligible_delta" in entry


def test_integration_writes_integration_blackboard_event(
    monkeypatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-int-bb"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
            "--goal",
            "Write a short report.",
            "--output",
            "output/report.md",
            "--max-iterations",
            "1",
        ],
    )
    from baps.core.run import main as run_main

    run_main()

    games_path = workspace / "blackboard" / "games.jsonl"
    assert games_path.exists(), "games.jsonl must exist after a successful run"

    lines = [
        json.loads(line)
        for line in games_path.read_text(encoding="utf-8").strip().splitlines()
    ]
    integration_events = [e for e in lines if e["event"] == "integration"]
    assert len(integration_events) >= 1, (
        "at least one integration event must be written"
    )

    evt = integration_events[0]
    assert "created_at" in evt
    assert "depth" in evt
    assert "proposal_id" in evt
    assert evt["proposal_id"] != ""
    assert "proposal_summary" in evt
    assert isinstance(evt["state_changed"], bool)
    assert "delta_type" in evt
    assert evt["delta_type"] != ""


def test_play_game_blackboard_final_disposition_accepted(tmp_path: Path) -> None:
    workspace = tmp_path / "ws-accept"
    config = _make_play_game_config(workspace)
    state = create_state(config)
    play_game(state, _make_document_game_spec(), config=config)

    entry = json.loads(
        (workspace / "blackboard" / "games.jsonl").read_text(encoding="utf-8").strip()
    )
    assert entry["final_disposition"] == "accepted"
    attempt = entry["attempts"][0]
    assert attempt["blue_delta"] is not None
    assert attempt["red_finding"]["disposition"] == "accept"
    assert attempt["referee_decision"]["disposition"] == "accept"


def test_play_game_blackboard_final_disposition_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "ws-reject"
    config = _make_play_game_config(workspace)
    state = create_state(config)
    play_game(
        state,
        _make_document_game_spec(),
        config=config,
        referee_model_client=FakeModelClient(
            ['{"disposition":"reject","rationale":"not good enough"}']
        ),
        max_attempts=1,
    )

    entry = json.loads(
        (workspace / "blackboard" / "games.jsonl").read_text(encoding="utf-8").strip()
    )
    assert entry["final_disposition"] == "rejected"
    attempt = entry["attempts"][0]
    assert attempt["blue_delta"] is not None
    assert attempt["referee_decision"]["disposition"] == "reject"
    assert entry["integration_eligible_delta"] is None


def test_play_game_blackboard_revise_only_is_not_integration_eligible(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws-revise-only"
    config = _make_play_game_config(workspace)
    state = create_state(config)
    play_game(
        state,
        _make_document_game_spec(),
        config=config,
        referee_model_client=FakeModelClient(
            ['{"disposition":"revise","rationale":"needs changes"}']
        ),
        max_attempts=1,
    )

    entry = json.loads(
        (workspace / "blackboard" / "games.jsonl").read_text(encoding="utf-8").strip()
    )
    assert entry["final_disposition"] == "rejected"
    assert entry["current_best_delta"] is None
    assert entry["integration_eligible_delta"] is None


def test_play_game_blackboard_final_disposition_no_delta(tmp_path: Path) -> None:
    workspace = tmp_path / "ws-nodelta"
    config = _make_play_game_config(workspace)
    state = create_state(config)
    # Empty body fails Section._validate_body → tool_call_to_delta raises → blue_delta stays None
    play_game(
        state,
        _make_document_game_spec(),
        config=config,
        model_client=FakeModelClient(
            tool_responses=[
                ToolCall(
                    name="append_section",
                    arguments={
                        "artifact_id": "main-document",
                        "title": "Intro",
                        "body": "",
                    },
                )
            ]
        ),
        max_attempts=1,
    )

    entry = json.loads(
        (workspace / "blackboard" / "games.jsonl").read_text(encoding="utf-8").strip()
    )
    assert entry["final_disposition"] == "no_delta"
    assert all(r["blue_delta"] is None for r in entry["attempts"])


def test_create_game_blackboard_captures_depth_and_context_chain(
    tmp_path: Path,
) -> None:
    config = RunConfig(
        workspace=tmp_path / "ws-cg-depth",
        project_type="document",
        artifact_id="main-document",
        goal="Write a report.",
        northstar_markdown="# Goal\n\nWrite a report.",
        output_path=tmp_path / "ws-cg-depth" / "output" / "report.md",
        max_iterations=1,
    )
    state = create_state(config)
    chain = ("Top-level gap", "Sub-level concern")
    create_game(
        config,
        state,
        depth=2,
        context_chain=chain,
        model_client=FakeModelClient(
            [
                '{"kind":"game_spec","objective":"Close the gap","target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"Section present."}'
            ]
        ),
    )

    entry = json.loads(
        (config["workspace"] / "blackboard" / "games.jsonl")
        .read_text(encoding="utf-8")
        .strip()
    )
    assert entry["depth"] == 2
    assert entry["context_chain"] == list(chain)


def test_play_game_blackboard_captures_depth_and_context_chain(tmp_path: Path) -> None:
    workspace = tmp_path / "ws-pg-depth"
    config = _make_play_game_config(workspace)
    state = create_state(config)
    chain = ("Parent gap", "Child concern")
    game_spec = _make_document_game_spec(context_chain=chain)
    play_game(state, game_spec, config=config, depth=1)

    entry = json.loads(
        (workspace / "blackboard" / "games.jsonl").read_text(encoding="utf-8").strip()
    )
    assert entry["depth"] == 1
    assert entry["context_chain"] == list(chain)


def test_blackboard_verification_summary_truncated_to_cap(
    tmp_path: Path, monkeypatch
) -> None:

    long_stdout = "O" * 700
    long_stderr = "E" * 600
    mock_vr = VerificationResult(
        command="pytest",
        cwd="/tmp",
        exit_code=0,
        stdout=long_stdout,
        stderr=long_stderr,
        passed=True,
    )
    monkeypatch.setattr(
        "baps.game.engine._verify_candidate_with_adapter", lambda *a, **kw: mock_vr
    )

    workspace = tmp_path / "ws-trunc"
    config = _make_play_game_config(workspace)
    state = create_state(config)
    play_game(state, _make_document_game_spec(), config=config)

    entry = json.loads(
        (workspace / "blackboard" / "games.jsonl").read_text(encoding="utf-8").strip()
    )
    cap = VERIFICATION_SUMMARY_CAP
    vr_summary = entry["verification_result"]
    assert vr_summary["stdout_summary"] == "O" * cap
    assert vr_summary["stderr_summary"] == "E" * cap
    assert len(vr_summary["stdout_summary"]) == cap
    assert len(vr_summary["stderr_summary"]) == cap

    attempt_vr = entry["attempts"][0]["candidate_verification"]
    assert attempt_vr["stdout"] == long_stdout
    assert attempt_vr["stderr"] == long_stderr

    # Original VerificationResult object is not mutated
    assert mock_vr.stdout == long_stdout
    assert mock_vr.stderr == long_stderr


def test_blackboard_verification_feedback_loop_uses_full_text(
    tmp_path: Path, monkeypatch
) -> None:
    """When candidate verification fails and Blue retries, the full stdout/stderr
    must appear in Blue's next prompt — only the blackboard summary is truncated."""

    long_stdout = "F" * 700
    failing_vr = VerificationResult(
        command="pytest",
        cwd="/tmp",
        exit_code=1,
        stdout=long_stdout,
        stderr="",
        passed=False,
    )
    passing_vr = VerificationResult(
        command="pytest",
        cwd="/tmp",
        exit_code=0,
        stdout="ok",
        stderr="",
        passed=True,
    )
    call_count = {"n": 0}

    def _mock_verify(*a, **kw):
        call_count["n"] += 1
        return failing_vr if call_count["n"] == 1 else passing_vr

    monkeypatch.setattr("baps.game.engine._verify_candidate_with_adapter", _mock_verify)

    workspace = tmp_path / "ws-feedbackloop"
    config = _make_play_game_config(workspace)
    state = create_state(config)
    blue_client = FakeModelClient(
        tool_responses=[
            ToolCall(
                name="append_section",
                arguments={
                    "artifact_id": "main-document",
                    "title": "Intro",
                    "body": "first",
                },
            ),
            ToolCall(
                name="append_section",
                arguments={
                    "artifact_id": "main-document",
                    "title": "Intro2",
                    "body": "second",
                },
            ),
        ]
    )
    accept_response = '{"disposition":"accept","rationale":"ok"}'
    play_game(
        state,
        _make_document_game_spec(),
        config=config,
        model_client=blue_client,
        red_model_client=FakeModelClient([accept_response, accept_response]),
        referee_model_client=FakeModelClient([accept_response, accept_response]),
        max_attempts=2,
    )

    # Blue's second prompt must contain the full stdout, not the truncated version
    assert len(blue_client.tool_prompts) == 2
    second_prompt = blue_client.tool_prompts[1]
    assert long_stdout in second_prompt


def test_integration_event_all_required_fields_with_correct_types(
    monkeypatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-int-fields"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
            "--goal",
            "Write a short report.",
            "--output",
            "output/report.md",
            "--max-iterations",
            "1",
        ],
    )
    from baps.core.run import main as run_main

    run_main()

    lines = [
        json.loads(line)
        for line in (workspace / "blackboard" / "games.jsonl")
        .read_text(encoding="utf-8")
        .strip()
        .splitlines()
    ]
    evt = next(e for e in lines if e["event"] == "integration")

    assert evt["event"] == "integration"
    assert isinstance(evt["created_at"], str) and evt["created_at"] != ""
    assert isinstance(evt["depth"], int)
    assert isinstance(evt["proposal_id"], str) and len(evt["proposal_id"]) == 36  # UUID
    assert isinstance(evt["proposal_summary"], str) and evt["proposal_summary"] != ""
    assert isinstance(evt["state_changed"], bool)
    assert isinstance(evt["delta_type"], str) and evt["delta_type"] != ""
    # For a document project the only supported delta op is append_section
    assert evt["delta_type"] == "append_section"


def test_create_game_blackboard_no_new_game_with_failing_verification(
    tmp_path: Path,
) -> None:
    """create_game writes result_type=no_new_game even when a failing verification
    result is in context. Runtime-level rejection of no_new_game happens in
    _solve_gap, not inside create_game; the blackboard must faithfully record
    what the model actually returned."""

    config = RunConfig(
        workspace=tmp_path / "ws-nng-vr",
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=tmp_path / "ws-nng-vr" / "output" / "report.md",
        max_iterations=1,
    )
    state = create_state(config)
    failing_vr = VerificationResult(
        command="pytest",
        cwd="/tmp",
        exit_code=1,
        stdout="FAILED tests/test_foo.py::test_bar",
        stderr="",
        passed=False,
    )

    with pytest.raises(NoNewGameError):
        create_game(
            config,
            state,
            verification_result=failing_vr,
            model_client=FakeModelClient(
                ['{"kind": "no_new_game", "reason": "No gap identified."}']
            ),
        )

    games_path = config["workspace"] / "blackboard" / "games.jsonl"
    assert games_path.exists()
    entry = json.loads(games_path.read_text(encoding="utf-8").strip())
    assert entry["event"] == "create_game"
    assert entry["result_type"] == "no_new_game"
    assert entry["result"] is None
    assert "created_at" in entry
    assert entry["depth"] == 0
