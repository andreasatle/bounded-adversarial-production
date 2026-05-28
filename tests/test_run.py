import argparse
import ast
import inspect
import json
import logging
from pathlib import Path
import subprocess

import pytest

from baps.models import FakeModelClient, ToolCall
from baps.run import create_game, create_state, main, play_game
from baps.state import (
    DecomposeSpec,
    GameSpec,
    StateUpdateProposal,
)
from baps.northstar_projection import ProjectionType, StateView
from baps.parsers import NoNewGameError, NorthStarUpdateNeededError
from baps.project_adapter import VerificationResult
from baps.game import _derive_state_update_from_delta, _commit_export_with_adapter
from baps.orchestration import _run_project_iterations
from baps.document_adapter import DocumentProjectAdapter
from baps.coding_adapter import CodingProjectAdapter
import baps.run as _real_run
import baps.run as run_module
import baps.state as state_module




def test_main_prints_required_fields_and_no_legacy_iteration_output(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    workspace = tmp_path / "w"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace", str(workspace),
            "--project-type", "document",
            "--artifact-id", "main-document",
            "--goal", "Write a short report.",
            "--output", "output/report.md",
        ],
    )

    main()
    out = capsys.readouterr().out

    assert f"workspace={workspace}" in out
    assert "project_type=document" in out
    assert "goal=Write a short report." in out
    assert f"output_path={workspace / 'output' / 'report.md'}" in out
    assert "max_iterations=2" in out
    assert "update_applied=True" in out
    assert "state_changed=True" in out
    assert "output_exported=True" in out
    assert "output_changed=True" in out
    assert "iteration=" not in out
    assert "proposal=" not in out
    assert "section_already_exists" not in out
    assert "[DEBUG]" not in out


def test_main_cli_config_resolves_and_prints(monkeypatch, capsys, tmp_path: Path) -> None:
    workspace = tmp_path / "custom-ws"
    output = "custom/report.md"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id", "main-document", "--goal",
            "Custom goal",
            "--output",
            output,
            "--max-iterations",
            "3",
        ],
    )

    main()
    out = capsys.readouterr().out

    assert f"workspace={workspace}" in out
    assert "project_type=document" in out
    assert "goal=Custom goal" in out
    assert f"output_path={workspace / output}" in out
    assert "max_iterations=3" in out


def test_main_yaml_spec_resolves_and_prints(monkeypatch, capsys, tmp_path: Path) -> None:
    workspace = tmp_path / "ws-from-spec"
    spec = tmp_path / "config.yaml"
    spec.write_text(
        "\n".join(
            [
                f"workspace: {workspace}",
                "project_type: document",
                "artifact_id: main-document",
                "goal: Spec goal",
                "output: out/spec-report.md",
                "max_iterations: 3",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("sys.argv", ["baps-run", "start", "--spec", str(spec)])
    main()
    out = capsys.readouterr().out

    assert f"workspace={workspace}" in out
    assert "project_type=document" in out
    assert "goal=Spec goal" in out
    assert f"output_path={workspace / 'out/spec-report.md'}" in out
    assert "max_iterations=3" in out


def test_main_document_spec_without_artifact_id_fails_cleanly(
    monkeypatch, caplog, tmp_path: Path
) -> None:
    spec = tmp_path / "config-missing-artifact.yaml"
    spec.write_text(
        "\n".join(
            [
                f"workspace: {tmp_path / 'ws'}",
                "project_type: document",
                "goal: Spec goal",
                "output: output/report.md",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("sys.argv", ["baps-run", "start", "--spec", str(spec)])
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "artifact_id must be non-empty" in caplog.text


def test_main_cli_overrides_yaml(monkeypatch, capsys, tmp_path: Path) -> None:
    spec = tmp_path / "config.yaml"
    spec.write_text(
        "\n".join(
            [
                "workspace: from-spec",
                "project_type: document",
                "artifact_id: main-document",
                "goal: Spec goal",
                "output: from-spec.md",
                "max_iterations: 7",
            ]
        ),
        encoding="utf-8",
    )
    cli_workspace = tmp_path / "from-cli"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--spec",
            str(spec),
            "--workspace",
            str(cli_workspace),
            "--project-type",
            "document",
            "--artifact-id", "main-document", "--goal",
            "CLI goal",
            "--output",
            "from-cli.md",
            "--max-iterations",
            "2",
        ],
    )

    main()
    out = capsys.readouterr().out

    assert f"workspace={cli_workspace}" in out
    assert "project_type=document" in out
    assert "goal=CLI goal" in out
    assert f"output_path={cli_workspace / 'from-cli.md'}" in out
    assert "max_iterations=2" in out


def test_output_path_absolute_remains_absolute(monkeypatch, capsys, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    absolute_output = tmp_path / "abs" / "report.md"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id", "main-document",
            "--goal", "Write a report.",
            "--output", str(absolute_output),
        ],
    )

    main()
    out = capsys.readouterr().out
    assert f"output_path={absolute_output}" in out


@pytest.mark.parametrize(
    ("argv", "error_substring"),
    [
        (
            ["baps-run", "start", "--project-type", "document", "--artifact-id", "main-document",
             "--goal", "Write a report.", "--output", "output/report.md", "--max-iterations", "0"],
            "max_iterations must be >= 1",
        ),
        (["baps-run", "start"], "project_type must be non-empty"),
        (
            ["baps-run", "start", "--project-type", "document", "--artifact-id", "main-document",
             "--output", "output/report.md", "--goal", "   "],
            "goal must be non-empty",
        ),
        (
            ["baps-run", "start", "--project-type", "document", "--artifact-id", "main-document",
             "--goal", "Write a report.", "--output", "output/report.md", "--workspace", "   "],
            "workspace must be non-empty",
        ),
        (
            ["baps-run", "start", "--project-type", "document", "--artifact-id", "main-document",
             "--goal", "Write a report.", "--output", "   "],
            "output must be non-empty",
        ),
        (
            ["baps-run", "start", "--project-type", "document", "--artifact-id", "main-document",
             "--output", "output/report.md"],
            "goal is required",
        ),
        (
            ["baps-run", "start", "--project-type", "document", "--artifact-id", "main-document",
             "--goal", "Write a report."],
            "output is required",
        ),
    ],
)
def test_invalid_config_fails_cleanly(monkeypatch, caplog, tmp_path, argv: list[str], error_substring: str) -> None:
    # Inject a fresh --workspace so the test doesn't pick up real workspace config
    # when no workspace or spec is specified.
    if "--workspace" not in argv and "--spec" not in argv:
        argv = argv + ["--workspace", str(tmp_path / "clean-ws")]
    monkeypatch.setattr("sys.argv", argv)
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert error_substring in caplog.text


@pytest.mark.parametrize(
    ("argv", "error_substring"),
    [
        (
            ["baps-run", "start", "--project-type", "git", "--goal", "g", "--output", "o/o.md"],
            "project_type 'git' is not implemented",
        ),
        (
            ["baps-run", "start", "--project-type", "unknown", "--goal", "g", "--output", "o/o.md"],
            "unknown project_type: unknown",
        ),
    ],
)
def test_invalid_project_type_fails_cleanly(
    monkeypatch, caplog, argv: list[str], error_substring: str
) -> None:
    monkeypatch.setattr("sys.argv", argv)
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert error_substring in caplog.text


def test_project_type_document_creates_state_and_logs_when_debug_enabled(
    monkeypatch, caplog, tmp_path: Path
) -> None:
    workspace = tmp_path / "debug-doc-ws"
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
        "--artifact-id", "main-document", "--goal", "Write a report.", "--output", "output/report.md", ],
    )

    with caplog.at_level(logging.DEBUG):
        main()
    assert "create_state.input:" in caplog.text
    assert "project_type: document" in caplog.text
    assert "create_state.output:" in caplog.text
    assert "create_game.input:" in caplog.text
    assert "create_game.output:" in caplog.text
    assert "state:" in caplog.text
    assert "artifacts:" in caplog.text
    assert "id: main-document" in caplog.text
    assert "kind: document" in caplog.text
    assert "sections: []" in caplog.text


def test_document_type_is_not_stored_in_state_output(monkeypatch, caplog, tmp_path: Path) -> None:
    workspace = tmp_path / "doc-ws"
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
        "--artifact-id", "main-document", "--goal", "Write a report.", "--output", "output/report.md", ],
    )

    with caplog.at_level(logging.DEBUG):
        main()
    create_state_output_msg = next(
        r.getMessage() for r in caplog.records if "create_state.output:" in r.getMessage()
    )
    assert "project_type" not in create_state_output_msg


def test_create_state_output_flows_into_create_game(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "flow-ws"
    import baps.run as run_module

    captured: dict[str, object] = {}
    original_create_game = run_module.create_game

    def _capturing_create_game(config, state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        captured.setdefault("state", state)
        return original_create_game(
            config,
            state,
            adapter=adapter,
            verification_result=verification_result,
        )

    monkeypatch.setattr("baps.orchestration.create_game", _capturing_create_game)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
        "--artifact-id", "main-document", "--goal", "Write a report.", "--output", "output/report.md", ],
    )

    run_module.main()

    forwarded_state = captured.get("state")
    assert forwarded_state is not None
    assert forwarded_state.model_dump(mode="json") == {
        "artifacts": [{"id": "main-document", "kind": "document", "sections": []}],
    }


def test_derive_state_update_from_delta_converts_append_section() -> None:
    import baps.run as run_module

    delta = state_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=state_module.AppendSectionDelta(
            section=state_module.Section(title="Introduction", body="Body text")
        ),
    )
    proposal = _derive_state_update_from_delta(
        delta, adapter=DocumentProjectAdapter()
    )
    assert proposal.target.artifact_id == "main-document"
    assert proposal.payload.operation == "append_section"
    assert proposal.payload.section.title == "Introduction"
    assert proposal.payload.section.body == "Body text"


def test_main_integration_uses_state_service_apply_update(monkeypatch, tmp_path: Path) -> None:
    import baps.run as run_module

    called = {"value": False}
    original_apply = run_module.StateService.apply_delta

    def _capture_apply(self, delta):
        called["value"] = True
        return original_apply(self, delta)

    monkeypatch.setattr(run_module.StateService, "apply_delta", _capture_apply)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(tmp_path / "ws-service"),
            "--project-type",
            "document",
        "--artifact-id", "main-document", "--goal", "Write a report.", "--output", "output/report.md", ],
    )
    run_module.main()
    assert called["value"] is True


def test_main_persists_updated_state_with_appended_section(monkeypatch, tmp_path: Path) -> None:
    import baps.run as run_module

    workspace = tmp_path / "ws-persist"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
        "--artifact-id", "main-document", "--goal", "Write a report.", "--output", "output/report.md", ],
    )
    run_module.main()

    persisted = run_module.JsonStateStore(workspace / "state" / "state.json").load()
    doc = next(a for a in persisted.artifacts if a.id == "main-document")
    assert isinstance(doc, state_module.DocumentArtifact)
    assert len(doc.sections) == 2
    assert doc.sections[0].title == "Introduction"
    assert doc.sections[0].body == "Advance goal"


def test_main_unsupported_delta_operation_fails_explicitly(monkeypatch, capsys, caplog, tmp_path: Path) -> None:
    import baps.run as run_module

    monkeypatch.setattr(
        "baps.orchestration.play_game",
        lambda _state, _spec, adapter=None, verification_result=None, **_kwargs: state_module.DeltaCodingState(
            artifact_id="main-document",
            operation="write_file",
            payload=state_module.WriteFileDelta(
                file=state_module.CodeFile(path="foo.py", content="x")
            ),
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(tmp_path / "ws-unsupported-op"),
            "--project-type",
            "document",
        "--artifact-id", "main-document", "--goal", "Write a report.", "--output", "output/report.md", ],
    )
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
        run_module.main()
    assert exc.value.code == 2
    assert "DocumentArtifact does not support delta type" in caplog.text


def _make_doc_config(
    artifact_id: str = "main-document",
    goal: str = "Write a short report.",
) -> dict:
    return {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": artifact_id,
        "goal": goal,
        "northstar_markdown": f"# Goal\n\n{goal}",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }


def _make_document_spec_and_state(success_condition: str = "A section exists."):
    import baps.run as run_module
    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition=success_condition,
    )
    state = create_state(
        {
            "workspace": Path(".baps-workspace"),
            "project_type": "document",
            "artifact_id": "main-document",
            "goal": "Write a short report.",
            "northstar_markdown": "# Goal\n\nWrite a short report.",
            "output_path": Path(".baps-workspace/output/report.md"),
            "max_iterations": 2,
            "spec_path": None,
        }
    )
    return spec, state


def _make_blue_client(*titles: str):
    return FakeModelClient(
        tool_responses=[
            ToolCall(
                name="append_section",
                arguments={"artifact_id": "main-document", "title": t, "body": "Body text."},
            )
            for t in titles
        ]
    )


def test_resolve_config_reads_artifact_id_and_northstar_and_create_state_uses_artifact_id(
    tmp_path: Path,
) -> None:
    import baps.run as run_module

    spec = tmp_path / "config.yaml"
    spec.write_text(
        "\n".join(
            [
                "project_type: document",
                "artifact_id: doc-7",
                "goal: Write a short report.",
                "output: output/report.md",
                "northstar_markdown: |",
                "  # Goal",
                "  Write a short report.",
                f"workspace: {tmp_path / 'ws'}",
            ]
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace(
        spec=str(spec),
        workspace=None,
        project_type=None,
        artifact_id=None,
        goal=None,
        output=None,
        max_iterations=None,
    )
    config = run_module.resolve_run_config(args)
    assert config["artifact_id"] == "doc-7"
    assert "# Goal" in config["northstar_markdown"]
    state = run_module.create_state(config)
    assert state.artifacts[0].id == "doc-7"


def test_create_game_accepts_atomic_introduction_gamespec() -> None:
    import baps.run as run_module

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "northstar_markdown": (
            "# Goal\n\nWrite a short report.\n\n"
            "# Required structure\n\n"
            "The report must include these sections, in order:\n\n"
            "1. Introduction\n"
            "2. Conclusion\n"
        ),
        "goal": "Write a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = run_module.create_state(config)
    game_spec = run_module.create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Add Introduction section",'
                '"target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"Introduction section exists."}'
            ]
        ),
    )
    assert "Introduction" in game_spec.objective


def test_create_game_accepts_atomic_conclusion_gamespec() -> None:
    import baps.run as run_module

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "northstar_markdown": (
            "# Goal\n\nWrite a short report.\n\n"
            "# Required structure\n\n"
            "The report must include these sections, in order:\n\n"
            "1. Introduction\n"
            "2. Conclusion\n"
        ),
        "goal": "Write a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = run_module.create_state(config)
    game_spec = run_module.create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Add Conclusion section",'
                '"target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"Conclusion section exists."}'
            ]
        ),
    )
    assert "Conclusion" in game_spec.objective


def test_create_game_engine_does_not_compute_next_missing_section() -> None:
    import baps.run as run_module

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "northstar_markdown": (
            "# Goal\n\nWrite a short report.\n\n"
            "# Required structure\n\n"
            "The report must include these sections, in order:\n\n"
            "1. Introduction\n"
            "2. Conclusion\n"
        ),
        "goal": "Write a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.DocumentArtifact(
                id="main-document",
                sections=(
                    state_module.Section(title="Introduction", body="Intro"),
                    state_module.Section(title="Conclusion", body="Outro"),
                ),
            ),
        ),
    )
    game_spec = run_module.create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Add Abstract section",'
                '"target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"Abstract section exists."}'
            ]
        ),
    )
    assert game_spec.objective == "Add Abstract section"


def test_create_game_explicit_no_new_game_signal() -> None:
    import baps.run as run_module

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "goal": "Write a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = run_module.create_state(config)
    with pytest.raises(NoNewGameError):
        run_module.create_game(
            config,
            state,
            model_client=FakeModelClient(
                ['{"no_new_game": true, "reason": "all required sections already present"}']
            ),
        )


def test_create_game_extra_key_on_no_new_game_response_is_stripped() -> None:
    import baps.run as run_module

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "goal": "Write a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = run_module.create_state(config)
    with pytest.raises(NoNewGameError, match="all required sections already present"):
        run_module.create_game(
            config,
            state,
            model_client=FakeModelClient(
                ['{"no_new_game": true, "reason": "all required sections already present", "confidence": 0.9}']
            ),
        )


def test_create_game_extra_key_on_northstar_response_is_stripped() -> None:
    import baps.run as run_module

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "goal": "Write a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = run_module.create_state(config)
    with pytest.raises(NorthStarUpdateNeededError):
        run_module.create_game(
            config,
            state,
            model_client=FakeModelClient(
                [
                    '{"northstar_update_needed": true, "rationale": "trajectory drifted",'
                    ' "proposed_northstar": "new goal", "confidence": 0.8}'
                ]
            ),
        )


def test_create_game_extra_key_on_decompose_response_is_stripped() -> None:
    import baps.run as run_module

    valid_sub_game = (
        '{"objective":"Advance goal","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState","success_condition":"section exists"}'
    )
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "goal": "Write a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = run_module.create_state(config)
    decompose_response = (
        '{"decompose": true, "rationale": "split into parts",'
        ' "sub_gaps": [{"description": "part one"}], "confidence": 0.7}'
    )
    result = run_module.create_game(
        config,
        state,
        model_client=FakeModelClient([decompose_response, valid_sub_game]),
    )
    assert isinstance(result, DecomposeSpec)


def test_create_game_extra_key_on_gamespec_response_is_stripped() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "goal": "Write a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    response = (
        '{"objective":"Advance goal","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState","success_condition":"section exists",'
        '"confidence": 0.95}'
    )
    game_spec = create_game(config, state, model_client=FakeModelClient([response]))
    assert game_spec.target_artifact_id == "main-document"


def test_create_game_engine_does_not_parse_must_include_policy_literals() -> None:
    import baps.run as run_module

    src = inspect.getsource(run_module)
    active_prefix = src
    assert "mandatory_sections_json" not in active_prefix
    assert "_extract_mandatory_sections_from_northstar" not in active_prefix
    assert "_select_next_missing_required_section" not in active_prefix
    assert "must include" not in active_prefix


def test_required_sections_top_level_is_rejected_in_config(monkeypatch, caplog, tmp_path: Path) -> None:
    spec = tmp_path / "bad-required-sections.yaml"
    spec.write_text(
        "\n".join(
            [
                "project_type: document",
                "artifact_id: main-document",
                "required_sections:",
                "  - Introduction",
                "  - Conclusion",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["baps-run", "start", "--spec", str(spec)])
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "required_sections is no longer supported" in caplog.text


def test_spec_file_unknown_key_raises(monkeypatch, caplog, tmp_path: Path) -> None:
    spec = tmp_path / "bad-key.yaml"
    spec.write_text(
        "project_type: document\nartifact_id: main-document\nmax_iteration: 2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["baps-run", "start", "--spec", str(spec)])
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "unknown keys" in caplog.text
    assert "max_iteration" in caplog.text


def test_spec_file_multiple_unknown_keys_all_reported(monkeypatch, caplog, tmp_path: Path) -> None:
    spec = tmp_path / "multi-bad-keys.yaml"
    spec.write_text(
        "project_type: document\nartifact_id: main-document\ntypo_a: x\ntypo_b: y\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["baps-run", "start", "--spec", str(spec)])
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "typo_a" in caplog.text
    assert "typo_b" in caplog.text


def test_spec_file_all_known_keys_accepted(monkeypatch, capsys, tmp_path: Path) -> None:
    spec = tmp_path / "all-known-keys.yaml"
    spec.write_text(
        "\n".join([
            "workspace: " + str(tmp_path / "ws"),
            "project_type: document",
            "artifact_id: main-document",
            "northstar_markdown: '# Goal'",
            "goal: Write a report.",
            "output: output/report.md",
            "max_iterations: 1",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["baps-run", "start", "--spec", str(spec)])
    main()
    out = capsys.readouterr().out
    assert "project_type=document" in out


def test_spec_file_required_sections_still_gets_specific_error(
    monkeypatch, caplog, tmp_path: Path
) -> None:
    spec = tmp_path / "required-sections.yaml"
    spec.write_text(
        "project_type: document\nartifact_id: main-document\nrequired_sections:\n  - Intro\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["baps-run", "start", "--spec", str(spec)])
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "required_sections is no longer supported" in caplog.text


def test_state_view_is_derived_from_state_and_gamespec_with_existing_sections() -> None:
    import baps.run as run_module

    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.DocumentArtifact(
                id="main-document",
                sections=(state_module.Section(title="Existing", body="Already here"),),
            ),
        ),
    )
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    assert state_view.metadata["target_artifact_id"] == "main-document"
    assert state_view.metadata["sections"] == [{"title": "Existing", "body": "Already here"}]
    assert state_view.content.startswith("=== StateView Start ===")
    assert state_view.content.endswith("=== StateView End ===")
    assert "--- State Artifacts ---" in state_view.content
    assert "## Artifact: main-document" in state_view.content
    assert "kind: document" in state_view.content
    assert "### Current Sections" in state_view.content
    assert "### Existing" in state_view.content
    assert "Already here" in state_view.content
    assert '"sections"' not in state_view.content
    assert "target_artifact_id" not in state_view.content
    assert "metadata" not in state_view.content
    assert "input_fingerprint" not in state_view.content


def test_document_state_view_content_for_empty_document() -> None:
    import baps.run as run_module

    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Any success condition.",
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="main-document", sections=()),),
    )

    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    content = state_view.content
    assert content.startswith("=== StateView Start ===")
    assert content.endswith("=== StateView End ===")
    assert "--- State Artifacts ---" in content
    assert "## Artifact: main-document" in content
    assert "kind: document" in content
    assert "### Current Sections" in content
    assert "No sections." in content
    assert '"sections"' not in content
    assert "target_artifact_id" not in content
    assert "metadata" not in content
    assert "input_fingerprint" not in content


def test_create_game_state_view_content_is_markdown_for_empty_document() -> None:
    import baps.run as run_module

    state = state_module.State(
        artifacts=(state_module.DocumentArtifact(id="main-document", sections=()),),
    )

    state_view = DocumentProjectAdapter().build_create_game_state_view(
        state,
        {
            "artifact_id": "main-document",
            "northstar_markdown": "# Goal\n\nWrite a short report about bounded adversarial evaluation.",
        },
    )
    content = state_view.content
    assert content.startswith("=== StateView Start ===")
    assert content.endswith("=== StateView End ===")
    assert "--- NorthStar ---" in content
    assert "--- NorthStar ---\n\n# Goal" in content
    assert "Write a short report about bounded adversarial evaluation." in content
    assert "--- State Artifacts ---" in content
    assert "## Artifact: main-document" in content
    assert "kind: document" in content
    assert "### Current Sections" in content
    assert "No sections." in content
    assert "# StateView" not in content
    assert "## NorthStar" not in content
    assert "## Target Artifact" not in content
    assert "northstar_content" not in content
    assert "target_artifact" not in content
    assert not content.lstrip().startswith("{")


def test_create_game_state_view_content_includes_sections_as_markdown() -> None:
    import baps.run as run_module

    state = state_module.State(
        artifacts=(
            state_module.DocumentArtifact(
                id="main-document",
                sections=(state_module.Section(title="Introduction", body="Intro body text."),),
            ),
        ),
    )

    state_view = DocumentProjectAdapter().build_create_game_state_view(
        state,
        {
            "artifact_id": "main-document",
            "northstar_markdown": "# Goal\n\nWrite a short report about bounded adversarial evaluation.",
        },
    )
    content = state_view.content
    assert "### Current Sections" in content
    assert "### Introduction" in content
    assert "Intro body text." in content
    assert "northstar_content" not in content
    assert "target_artifact" not in content
    assert not content.lstrip().startswith("{")


def test_no_blueview_symbol_remains_in_run_or_run_tests() -> None:
    run_source = Path("src/baps/run.py").read_text(encoding="utf-8")
    test_source = Path("tests/test_run.py").read_text(encoding="utf-8")
    symbol = "Blue" + "View"
    assert symbol not in run_source
    assert symbol not in test_source.replace(symbol, "")


def test_start_clean_workspace_creates_report_from_spec(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    workspace = tmp_path / "ws-doc"
    spec = tmp_path / "document-project.yaml"
    spec.write_text(
        "\n".join(
            [
                "project_type: document",
                "artifact_id: main-document",
                f"workspace: {workspace}",
                "goal: Write a short report about bounded adversarial evaluation.",
                "output: output/report.md",
                "max_iterations: 2",
                "northstar_markdown: |",
                "  # Goal",
                "",
                "  Write a short report about bounded adversarial evaluation.",
                "",
                "  # Required structure",
                "",
                "  The report must include these sections, in order:",
                "",
                "  1. Introduction",
                "  2. Conclusion",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["baps-run", "start", "--spec", str(spec)],
    )
    main()
    out = capsys.readouterr().out
    assert (workspace / "output" / "report.md").exists()
    assert "output_exported=True" in out


def test_active_main_writes_output_path_from_state(tmp_path: Path, monkeypatch, capsys) -> None:
    workspace = tmp_path / "ws-export"
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
            "--goal", "Write a report.", "--output", "output/report.md",
            "--max-iterations",
            "1",
        ],
    )
    main()
    out = capsys.readouterr().out
    output_path = workspace / "output" / "report.md"
    assert output_path.exists()
    assert "output_exported=True" in out
    assert "output_changed=True" in out


def test_document_export_markdown_contains_sections_in_order(tmp_path: Path) -> None:
    import baps.run as run_module

    adapter = DocumentProjectAdapter()
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.DocumentArtifact(
                id="main-document",
                sections=(
                    state_module.Section(title="Introduction", body="Intro body"),
                    state_module.Section(title="Conclusion", body="Conclusion body"),
                ),
            ),
        ),
    )
    output_path = tmp_path / "nested" / "out" / "report.md"
    changed = adapter.export_state(state, output_path, "main-document")
    assert changed is True
    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8") == (
        "## Introduction\n\nIntro body\n\n## Conclusion\n\nConclusion body"
    )


def test_document_export_creates_parent_directories(tmp_path: Path) -> None:
    import baps.run as run_module

    adapter = DocumentProjectAdapter()
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="main-document", sections=()),),
    )
    output_path = tmp_path / "a" / "b" / "c" / "report.md"
    adapter.export_state(state, output_path, "main-document")
    assert output_path.parent.exists()


def test_document_export_output_changed_false_when_unchanged(tmp_path: Path) -> None:
    import baps.run as run_module

    adapter = DocumentProjectAdapter()
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.DocumentArtifact(
                id="main-document",
                sections=(state_module.Section(title="Intro", body="Body"),),
            ),
        ),
    )
    output_path = tmp_path / "out" / "report.md"
    first = adapter.export_state(state, output_path, "main-document")
    second = adapter.export_state(state, output_path, "main-document")
    assert first is True
    assert second is False


def test_document_export_lives_behind_adapter_not_main_orchestration() -> None:
    import baps.run as run_module
    import baps.document_adapter as doc_adapter_module

    main_src = inspect.getsource(run_module.main)
    assert "output_path.write_text" not in main_src
    assert "run_baps_loop(" not in main_src
    # write_text lives in export_document_artifact, not directly in export_state
    free_fn_src = inspect.getsource(doc_adapter_module.export_document_artifact)
    assert "write_text" in free_fn_src


def test_baps_start_creates_state_file(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "ws-start"
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
            "--goal", "Write a report.",
            "--output", "output/report.md",
        ],
    )
    main()
    assert (workspace / "state" / "state.json").exists()


def test_baps_start_twice_continues(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "ws-start-twice"
    argv = [
        "baps-run",
        "start",
        "--workspace",
        str(workspace),
        "--project-type",
        "document",
        "--artifact-id",
        "main-document",
        "--goal", "Write a report.",
        "--output", "output/report.md",
        "--max-iterations", "1",
    ]
    monkeypatch.setattr("sys.argv", argv)
    main()
    # Second start continues without error — does not raise "already initialized"
    monkeypatch.setattr("sys.argv", argv)
    main()
    assert (workspace / "state" / "state.json").exists()


def test_baps_start_without_existing_state_initializes(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "ws-start-fresh"
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
            "--goal", "Write a report.",
            "--output", "output/report.md",
            "--max-iterations", "1",
        ],
    )
    main()
    assert (workspace / "state" / "state.json").exists()


def test_baps_start_loads_existing_state_without_create_state(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.run as run_module

    workspace = tmp_path / "ws-start-load"
    # First start — initializes
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
            "--goal", "Write a report.",
            "--output", "output/report.md",
        ],
    )
    main()

    # Second start — must NOT call create_state since state already exists
    monkeypatch.setattr(
        run_module,
        "create_state",
        lambda _config: (_ for _ in ()).throw(AssertionError("create_state should not be called when state exists")),
    )
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
            "--goal", "Write a report.", "--output", "output/report.md",
            "--max-iterations",
            "1",
        ],
    )
    main()


def test_baps_start_works(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "ws-start"
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
            "--goal", "Write a report.", "--output", "output/report.md",
            "--max-iterations",
            "1",
        ],
    )
    main()
    assert (workspace / "state" / "state.json").exists()
    assert (workspace / "output" / "report.md").exists()


def test_baps_reset_wipes_state_and_output_then_exits(monkeypatch, tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "ws-reset"

    # Create state and output via start
    monkeypatch.setattr("sys.argv", [
        "baps-run", "start",
        "--workspace", str(workspace),
        "--project-type", "document",
        "--artifact-id", "main-document",
        "--goal", "Write a report.", "--output", "output/report.md",
        "--max-iterations", "1",
    ])
    main()

    state_path = workspace / "state" / "state.json"
    output_path = workspace / "output" / "report.md"
    assert state_path.exists()
    assert output_path.exists()

    # Reset: wipe state and output, no game loop
    monkeypatch.setattr("sys.argv", [
        "baps-run", "reset",
        "--workspace", str(workspace),
        "--output", "output/report.md",
    ])
    main()

    assert not state_path.exists(), "reset must wipe state.json"
    assert not output_path.exists(), "reset must wipe output file"
    out = capsys.readouterr().out
    assert f"workspace={workspace}" in out
    assert "command=reset" in out
    assert "wiped=True" in out


def test_baps_reset_makes_no_model_calls(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "ws-reset-no-model"

    def _fail(*_a, **_kw):
        raise AssertionError("model client must not be built during reset")

    monkeypatch.setattr("baps.clients._build_model_client", _fail)
    monkeypatch.setattr("baps.clients._build_planner_model_client", _fail)
    monkeypatch.setattr("baps.clients._build_role_client", _fail)
    monkeypatch.setattr("baps.clients._build_client_for_role", _fail)

    monkeypatch.setattr("sys.argv", [
        "baps-run", "reset",
        "--workspace", str(workspace),
    ])
    main()  # must not raise


def test_baps_reset_without_existing_state_exits_cleanly(monkeypatch, tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "ws-reset-empty"
    monkeypatch.setattr("sys.argv", [
        "baps-run", "reset",
        "--workspace", str(workspace),
    ])
    main()
    out = capsys.readouterr().out
    assert "wiped=True" in out


def test_second_run_sees_previous_state(monkeypatch, tmp_path: Path) -> None:
    import baps.run as run_module

    workspace = tmp_path / "ws-second-run-state"
    seen_titles: list[list[str]] = []

    def _create_game(config, state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        del verification_result
        doc = next(a for a in state.artifacts if a.id == "main-document")
        titles = [s.title for s in doc.sections]
        seen_titles.append(titles)
        if "Introduction" not in titles:
            objective = "Add introduction section"
        else:
            objective = "Add conclusion section"
        return GameSpec(
            objective=objective,
            target_artifact_id="main-document",
            allowed_delta_type="DeltaDocumentState",
            success_condition=objective,
        )

    def _play_game(_state, spec, adapter=None, verification_result=None, **_kwargs):
        title = "Introduction" if "introduction" in spec.objective.lower() else "Conclusion"
        return state_module.DeltaDocumentState(
            artifact_id="main-document",
            operation="append_section",
            payload=state_module.AppendSectionDelta(
                section=state_module.Section(title=title, body=f"{title} body")
            ),
        )

    monkeypatch.setattr("baps.orchestration.create_game", _create_game)
    monkeypatch.setattr("baps.orchestration.play_game", _play_game)

    start_argv = [
        "baps-run",
        "start",
        "--workspace",
        str(workspace),
        "--project-type",
        "document",
        "--artifact-id",
        "main-document",
        "--goal", "Write a report.", "--output", "output/report.md",
        "--max-iterations",
        "1",
    ]
    monkeypatch.setattr("sys.argv", start_argv)
    main()
    monkeypatch.setattr("sys.argv", start_argv)
    main()
    monkeypatch.setattr("sys.argv", start_argv)
    main()
    assert seen_titles[0] == []
    assert seen_titles[1] == ["Introduction"]


def test_export_works_after_start_command(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "ws-export-after-start"
    start_argv = [
        "baps-run",
        "start",
        "--workspace",
        str(workspace),
        "--project-type",
        "document",
        "--artifact-id",
        "main-document",
        "--goal", "Write a report.", "--output", "output/report.md",
        "--max-iterations",
        "1",
    ]
    monkeypatch.setattr("sys.argv", start_argv)
    main()
    monkeypatch.setattr("sys.argv", start_argv)
    main()
    assert (workspace / "output" / "report.md").exists()


def test_spec_relative_path_resolves_from_cwd(monkeypatch, capsys, tmp_path: Path) -> None:
    spec = tmp_path / "config.yaml"
    workspace = tmp_path / "from-relative-spec"
    spec.write_text(
        "project_type: document\nartifact_id: main-document\n"
        f"workspace: {workspace}\ngoal: Write a report.\noutput: output/report.md\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["baps-run", "start", "--spec", "config.yaml"])

    main()
    out = capsys.readouterr().out
    assert f"workspace={workspace}" in out


def test_debug_enabled_prints_read_config_input_output(monkeypatch, caplog, tmp_path: Path) -> None:
    workspace = tmp_path / "debug-ws"
    spec = tmp_path / "debug-config.yaml"
    spec.write_text(
        "\n".join(
            [
                f"workspace: {workspace}",
                "project_type: document",
                "artifact_id: main-document",
                "goal: Debug spec goal",
                "output: out/debug.md",
                "max_iterations: 2",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setattr("sys.argv", ["baps-run", "start", "--spec", str(spec)])

    with caplog.at_level(logging.DEBUG):
        main()

    assert "read_config.input:" in caplog.text
    assert "cli_args:" in caplog.text
    assert "yaml_values:" in caplog.text
    assert f"workspace: {workspace}" in caplog.text
    assert "goal: Debug spec goal" in caplog.text
    assert "output: out/debug.md" in caplog.text
    assert "max_iterations: 2" in caplog.text
    assert "read_config.output:" in caplog.text
    assert "artifact_id: main-document" in caplog.text
    assert f"output_path: {workspace / 'out/debug.md'}" in caplog.text
    assert "{'cli_args':" not in caplog.text


def test_examples_document_project_yaml_still_passes(monkeypatch, capsys, tmp_path: Path) -> None:
    import baps.run as run_module
    workspace = tmp_path / "example-doc-ws"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--spec",
            "examples/document-project.yaml",
            "--workspace",
            str(workspace),
        ],
    )
    run_module.main()
    out = capsys.readouterr().out
    assert "project_type=document" in out
    assert "stop_reason=" in out


def _write_init_spec(tmp_path: Path, workspace: Path, goal: str = "Write a report.") -> Path:
    spec = tmp_path / "init-spec.yaml"
    spec.write_text(
        "\n".join([
            f"workspace: {workspace}",
            "project_type: document",
            "artifact_id: main-document",
            f"goal: {goal}",
            "northstar_markdown: '# NorthStar\\n\\nWrite a report.'",
            "output: output/report.md",
        ]),
        encoding="utf-8",
    )
    return spec


def test_init_saves_workspace_config(monkeypatch, capsys, tmp_path: Path) -> None:
    import baps.run as run_module

    workspace = tmp_path / "ws-config-save"
    spec = _write_init_spec(tmp_path, workspace, goal="Write a structured report.")
    monkeypatch.setattr("sys.argv", ["baps-run", "start", "--spec", str(spec)])
    run_module.main()
    capsys.readouterr()

    config_path = workspace / "baps-config.json"
    assert config_path.exists()
    saved = json.loads(config_path.read_text())
    assert saved["project_type"] == "document"
    assert saved["artifact_id"] == "main-document"
    assert saved["goal"] == "Write a structured report."
    assert "northstar_markdown" in saved
    assert "output" in saved


def test_start_loads_project_type_and_artifact_from_workspace_config(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    import baps.run as run_module

    workspace = tmp_path / "ws-resume"
    spec = _write_init_spec(tmp_path, workspace)
    monkeypatch.setattr("sys.argv", ["baps-run", "start", "--spec", str(spec)])
    run_module.main()
    capsys.readouterr()

    # Second start without --spec — loads config from workspace
    monkeypatch.setattr(
        "sys.argv",
        ["baps-run", "start", "--workspace", str(workspace), "--max-iterations", "1"],
    )
    run_module.main()
    out = capsys.readouterr().out
    assert "project_type=document" in out
    assert "stop_reason=" in out


def test_start_cli_args_override_workspace_config(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    import baps.run as run_module

    workspace = tmp_path / "ws-override"
    spec = _write_init_spec(tmp_path, workspace, goal="Original goal.")
    monkeypatch.setattr("sys.argv", ["baps-run", "start", "--spec", str(spec)])
    run_module.main()
    capsys.readouterr()

    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run", "start",
            "--workspace", str(workspace),
            "--goal", "Overridden goal.",
            "--max-iterations", "1",
        ],
    )
    run_module.main()
    out = capsys.readouterr().out
    assert "goal=Overridden goal." in out


def test_init_from_spec_persists_northstar_in_workspace_config(monkeypatch, tmp_path: Path) -> None:
    import baps.run as run_module

    workspace = tmp_path / "ws-init-northstar"
    spec = tmp_path / "config.yaml"
    spec.write_text(
        "\n".join(
            [
                "project_type: document",
                "artifact_id: main-document",
                f"workspace: {workspace}",
                "goal: Write a short report grounded in NorthStar intent.",
                "output: output/report.md",
                "northstar_markdown: |",
                "  # Goal",
                "",
                "  Write a short report grounded in NorthStar intent.",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("sys.argv", ["baps-run", "start", "--spec", str(spec)])
    run_module.main()

    import json as _json
    workspace_config = _json.loads((workspace / "baps-config.json").read_text())
    assert "northstar_markdown" in workspace_config
    assert "# Goal" in workspace_config["northstar_markdown"]
    assert "Write a short report grounded in NorthStar intent." in workspace_config["northstar_markdown"]

    persisted = run_module.JsonStateStore(workspace / "state" / "state.json").load()
    assert len(persisted.artifacts) == 1
    assert persisted.artifacts[0].id == "main-document"


def test_debug_formatter_renders_nested_list_of_dicts_without_python_repr(
    monkeypatch, caplog, tmp_path: Path
) -> None:
    workspace = tmp_path / "debug-structure-ws"
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
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
            "--goal", "Write a report.",
            "--output", "output/report.md",
        ],
    )

    with caplog.at_level(logging.DEBUG):
        main()
    assert "artifacts: [{'id':" not in caplog.text
    assert "id: main-document" in caplog.text
    assert "sections: []" in caplog.text


def test_debug_formatter_renders_tuple_as_yaml_list_and_empty_as_brackets(
    monkeypatch, caplog, tmp_path: Path
) -> None:
    workspace = tmp_path / "debug-tuple-ws"
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
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
            "--goal", "Write a report.",
            "--output", "output/report.md",
        ],
    )

    with caplog.at_level(logging.DEBUG):
        main()
    assert "id: main-document" in caplog.text
    assert "sections: []" in caplog.text


def test_main_uses_project_type_adapter_dispatch_for_document(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.run as run_module

    class _RecordingAdapter:
        project_type = "document"
        supported_delta_type = "DeltaDocumentState"

        def __init__(self) -> None:
            self.calls: list[str] = []
            self._delegate = DocumentProjectAdapter()

        def create_initial_state(self, config):
            self.calls.append("create_initial_state")
            return self._delegate.create_initial_state(config)

        def build_create_game_state_view(self, state, config):
            self.calls.append("build_create_game_state_view")
            return self._delegate.build_create_game_state_view(state, config)

        def render_create_game_prompt_supplement(
            self, state, config, state_view, verification_result
        ):
            self.calls.append("render_create_game_prompt_supplement")
            return self._delegate.render_create_game_prompt_supplement(
                state, config, state_view, verification_result
            )

        def build_state_view(self, state, game_spec):
            self.calls.append("build_state_view")
            return self._delegate.build_state_view(state, game_spec)

        def render_blue_prompt(self, state_view, game_spec, attempt_number, previous_feedback):
            self.calls.append("render_blue_prompt")
            return self._delegate.render_blue_prompt(
                state_view, game_spec, attempt_number, previous_feedback
            )

        def build_blue_output_format(self):
            self.calls.append("build_blue_output_format")
            return self._delegate.build_blue_output_format()

        def build_blue_tools(self):
            self.calls.append("build_blue_tools")
            return self._delegate.build_blue_tools()

        def tool_call_to_delta(self, tool_call):
            self.calls.append("tool_call_to_delta")
            return self._delegate.tool_call_to_delta(tool_call)

        def delta_to_state_update(self, delta_state):
            self.calls.append("delta_to_state_update")
            return self._delegate.delta_to_state_update(delta_state)

        def export_state(self, state, output_path, artifact_id):
            self.calls.append("export_state")
            return self._delegate.export_state(state, output_path, artifact_id)

    adapter = _RecordingAdapter()
    monkeypatch.setattr(run_module, "_resolve_project_type_adapter", lambda _ptype: adapter)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(tmp_path / "ws-adapter-dispatch"),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
            "--goal", "Write a report.", "--output", "output/report.md",
            "--max-iterations",
            "1",
        ],
    )
    run_module.main()
    assert "create_initial_state" in adapter.calls
    assert "build_create_game_state_view" in adapter.calls
    assert "render_create_game_prompt_supplement" in adapter.calls
    assert "build_state_view" in adapter.calls
    assert "render_blue_prompt" in adapter.calls
    assert "build_blue_output_format" in adapter.calls
    assert "build_blue_tools" in adapter.calls
    assert "tool_call_to_delta" in adapter.calls
    assert "export_state" in adapter.calls


def test_adapter_registry_includes_document_and_coding() -> None:
    import baps.run as run_module

    adapters = run_module._build_project_type_adapters()
    assert "document" in adapters
    assert "coding" in adapters


def test_core_orchestration_does_not_reference_concrete_project_adapters() -> None:
    import baps.run as run_module

    for fn in (
        run_module.create_game,
        _run_project_iterations,
    ):
        src = inspect.getsource(fn)
        assert "DocumentProjectAdapter" not in src
        assert "CodingProjectAdapter" not in src


def test_run_core_source_has_no_coding_file_policy_literals() -> None:
    run_source = Path("src/baps/run.py").read_text(encoding="utf-8")
    assert "src/fibonacci.py" not in run_source
    assert "tests/test_fibonacci.py" not in run_source


def test_coding_create_state_creates_coding_artifact() -> None:
    import baps.run as run_module

    state = run_module.create_state(
        {
            "workspace": Path(".baps-workspace"),
            "project_type": "coding",
            "artifact_id": "main-codebase",
            "language": "python",
            "goal": "Implement Fibonacci",
            "northstar_markdown": "# Goal\n\nImplement Fibonacci",
            "output_path": Path(".baps-workspace/output/project"),
            "max_iterations": 2,
            "spec_path": None,
        }
    )
    assert len(state.artifacts) == 1
    artifact = state.artifacts[0]
    assert isinstance(artifact, state_module.CodingArtifact)
    assert artifact.id == "main-codebase"
    assert artifact.files == ()


def test_coding_create_game_state_view_is_textual_with_delimiters() -> None:
    import baps.run as run_module

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "coding",
        "artifact_id": "main-codebase",
        "language": "python",
        "goal": "Implement Fibonacci",
        "northstar_markdown": "# Goal\n\nImplement Fibonacci",
        "output_path": Path(".baps-workspace/output/project"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = run_module.create_state(config)
    adapter = CodingProjectAdapter()
    view = adapter.build_create_game_state_view(state, config)
    assert view.content.startswith("=== StateView Start ===")
    assert view.content.endswith("=== StateView End ===")
    assert "--- NorthStar ---" in view.content
    assert "--- State Artifacts ---" in view.content
    assert "## Artifact: main-codebase" in view.content
    assert "kind: coding" in view.content
    assert "No files." in view.content


def test_coding_create_game_accepts_src_file_task_first_iteration() -> None:
    import baps.run as run_module

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "coding",
        "artifact_id": "main-codebase",
        "language": "python",
        "goal": "Implement Fibonacci with tests",
        "northstar_markdown": (
            "# Goal\n\nImplement Fibonacci with tests.\n"
            "- Production code in `src/fibonacci.py`\n"
            "- Pytest tests in `tests/test_fibonacci.py`\n"
        ),
        "output_path": Path(".baps-workspace/output/project"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = run_module.create_state(config)
    game_spec = run_module.create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Write src/fibonacci.py with fibonacci implementation",'
                '"target_artifact_id":"main-codebase",'
                '"allowed_delta_type":"DeltaCodingState",'
                '"success_condition":"Artifact contains src/fibonacci.py with a fibonacci function."}'
            ]
        ),
    )
    assert "src/fibonacci.py" in game_spec.objective
    assert game_spec.allowed_delta_type == "DeltaCodingState"


def test_coding_create_game_accepts_test_file_task_second_iteration() -> None:
    import baps.run as run_module

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "coding",
        "artifact_id": "main-codebase",
        "goal": "Implement Fibonacci with tests",
        "northstar_markdown": (
            "# Goal\n\nImplement Fibonacci with tests.\n"
            "- Production code in `src/fibonacci.py`\n"
            "- Pytest tests in `tests/test_fibonacci.py`\n"
        ),
        "output_path": Path(".baps-workspace/output/project"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = state_module.State(
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(
                    state_module.CodeFile(
                        path="src/fibonacci.py",
                        content="def fibonacci(n):\n    return n\n",
                    ),
                ),
            ),
        ),
    )
    game_spec = run_module.create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Write tests/test_fibonacci.py with pytest cases for fibonacci",'
                '"target_artifact_id":"main-codebase",'
                '"allowed_delta_type":"DeltaCodingState",'
                '"success_condition":"Artifact contains tests/test_fibonacci.py with pytest tests for fibonacci."}'
            ]
        ),
    )
    assert "tests/test_fibonacci.py" in game_spec.objective
    assert game_spec.allowed_delta_type == "DeltaCodingState"


def test_coding_normalize_passes_through_model_objective_and_success_condition() -> None:
    import baps.run as run_module

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "coding",
        "artifact_id": "main-codebase",
        "language": "python",
        "goal": "Implement a text similarity utility",
        "northstar_markdown": (
            "# Goal\n\nImplement a text similarity utility.\n"
            "- src/similarity.py\n"
            "- tests/test_similarity.py\n"
        ),
        "output_path": Path(".baps-workspace/output/project"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = run_module.create_state(config)
    game_spec = run_module.create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Write src/similarity.py with normalize and token_overlap",'
                '"target_artifact_id":"main-codebase",'
                '"allowed_delta_type":"DeltaCodingState",'
                '"success_condition":"Artifact contains src/similarity.py with all required functions."}'
            ]
        ),
    )
    assert game_spec.objective == "Write src/similarity.py with normalize and token_overlap"
    assert game_spec.success_condition == "Artifact contains src/similarity.py with all required functions."
    assert game_spec.target_artifact_id == "main-codebase"


def test_coding_normalize_does_not_inject_hardcoded_file_paths() -> None:
    import baps.run as run_module

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "coding",
        "artifact_id": "main-codebase",
        "language": "python",
        "goal": "Implement a text similarity utility",
        "northstar_markdown": "# Goal\n\nImplement a text similarity utility.",
        "output_path": Path(".baps-workspace/output/project"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = run_module.create_state(config)
    game_spec = run_module.create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Write src/similarity.py",'
                '"target_artifact_id":"main-codebase",'
                '"allowed_delta_type":"DeltaCodingState",'
                '"success_condition":"src/similarity.py exists with required functions"}'
            ]
        ),
    )
    assert "fibonacci" not in game_spec.objective.lower()
    assert "fibonacci" not in game_spec.success_condition.lower()
    assert game_spec.target_artifact_id == "main-codebase"


def test_coding_normalization_overrides_file_path_target_artifact_id() -> None:
    import baps.run as run_module

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "coding",
        "artifact_id": "main-codebase",
        "language": "python",
        "goal": "Implement Fibonacci with tests",
        "northstar_markdown": "# Goal\n\nImplement Fibonacci with tests.",
        "output_path": Path(".baps-workspace/output/project"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = run_module.create_state(config)
    game_spec = run_module.create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Write tests file",'
                '"target_artifact_id":"tests/test_fibonacci.py",'
                '"allowed_delta_type":"DeltaCodingState",'
                '"success_condition":"tests/test_fibonacci.py exists"}'
            ]
        ),
    )
    assert game_spec.target_artifact_id == "main-codebase"
    assert game_spec.target_artifact_id != "tests/test_fibonacci.py"


def test_document_adapter_normalize_game_spec_is_identity() -> None:
    import baps.run as run_module

    adapter = DocumentProjectAdapter()
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = run_module.create_state(config)
    original = GameSpec(
        objective="Any document objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Any document success condition",
    )
    normalized = adapter.normalize_game_spec(original, state, config)
    assert normalized == original


def test_coding_adapter_maps_file_write_delta_to_state_update() -> None:

    adapter = CodingProjectAdapter()
    delta = state_module.DeltaCodingState(
        artifact_id="main-codebase",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(
                path="src/fibonacci.py",
                content="def fibonacci(n):\n    return n\n",
            )
        ),
    )
    proposal = adapter.delta_to_state_update(delta)
    assert proposal.payload.operation == "write_file"
    assert proposal.payload.file.path == "src/fibonacci.py"


def test_coding_adapter_export_writes_files(tmp_path: Path) -> None:
    import baps.run as run_module

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(
                    state_module.CodeFile(
                        path="src/fibonacci.py",
                        content="def fibonacci(n):\n    return n\n",
                    ),
                    state_module.CodeFile(
                        path="tests/test_fibonacci.py",
                        content="def test_smoke():\n    assert True\n",
                    ),
                ),
            ),
        ),
    )
    adapter = CodingProjectAdapter()
    changed = adapter.export_state(
        state=state,
        output_path=tmp_path / "project",
        artifact_id="main-codebase",
    )
    assert changed is True
    assert (tmp_path / "project" / "src" / "fibonacci.py").exists()
    assert (tmp_path / "project" / "tests" / "test_fibonacci.py").exists()


def test_coding_adapter_export_writes_src_and_tests_layout(tmp_path: Path) -> None:
    import baps.run as run_module

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(
                    state_module.CodeFile(
                        path="src/fibonacci.py",
                        content="def fibonacci(n):\n    return n\n",
                    ),
                    state_module.CodeFile(
                        path="tests/test_fibonacci.py",
                        content=(
                            "from src.fibonacci import fibonacci\n\n"
                            "def test_fibonacci_smoke():\n"
                            "    assert fibonacci(5) == 5\n"
                        ),
                    ),
                ),
            ),
        ),
    )
    adapter = CodingProjectAdapter()
    changed = adapter.export_state(
        state=state,
        output_path=tmp_path / "project",
        artifact_id="main-codebase",
    )
    assert changed is True
    assert (tmp_path / "project" / "src" / "fibonacci.py").exists()
    assert (tmp_path / "project" / "tests" / "test_fibonacci.py").exists()


def test_coding_export_normalizes_escaped_newline_content(tmp_path: Path) -> None:
    import baps.run as run_module

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(
                    state_module.CodeFile(
                        path="tests/test_fibonacci.py",
                        content="import pytest\\n\\ndef test_ok():\\n    assert 1 == 1\\n",
                    ),
                ),
            ),
        ),
    )
    adapter = CodingProjectAdapter()
    adapter.export_state(state, tmp_path / "project", "main-codebase")
    exported = (tmp_path / "project" / "tests" / "test_fibonacci.py").read_text(
        encoding="utf-8"
    )
    assert "\\n" not in exported
    assert "import pytest\n\ndef test_ok():" in exported


def test_coding_export_normalizes_escaped_quotes_content(tmp_path: Path) -> None:
    import baps.run as run_module

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(
                    state_module.CodeFile(
                        path="src/fibonacci.py",
                        content='def msg():\\n    return \\"ok\\"\\n',
                    ),
                ),
            ),
        ),
    )
    adapter = CodingProjectAdapter()
    adapter.export_state(state, tmp_path / "project", "main-codebase")
    exported = (tmp_path / "project" / "src" / "fibonacci.py").read_text(
        encoding="utf-8"
    )
    assert '\\"' not in exported
    assert 'return "ok"' in exported


def test_coding_export_normalizes_multiline_pytest_and_parses(tmp_path: Path) -> None:
    import baps.run as run_module

    escaped_pytest = (
        "import pytest\\n"
        "from src.fibonacci import fibonacci\\n\\n"
        "def test_fibonacci_base_cases():\\n"
        "    assert fibonacci(0) == 0\\n"
        "    assert fibonacci(1) == 1\\n\\n"
        "def test_fibonacci_negative_input():\\n"
        "    with pytest.raises(ValueError):\\n"
        "        fibonacci(-1)\\n"
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(state_module.CodeFile(path="tests/test_fibonacci.py", content=escaped_pytest),),
            ),
        ),
    )
    adapter = CodingProjectAdapter()
    adapter.export_state(state, tmp_path / "project", "main-codebase")
    exported = (tmp_path / "project" / "tests" / "test_fibonacci.py").read_text(
        encoding="utf-8"
    )
    ast.parse(exported)
    assert "def test_fibonacci_base_cases():" in exported
    assert "\\n" not in exported


def test_coding_adapter_verify_export_discovers_and_runs_pytest_tests(
    tmp_path: Path,
) -> None:
    import baps.run as run_module

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(
                    state_module.CodeFile(
                        path="src/fibonacci.py",
                        content=(
                            "def fibonacci(n):\n"
                            "    if n < 0:\n"
                            "        raise ValueError('n must be >= 0')\n"
                            "    if n < 2:\n"
                            "        return n\n"
                            "    a, b = 0, 1\n"
                            "    for _ in range(2, n + 1):\n"
                            "        a, b = b, a + b\n"
                            "    return b\n"
                        ),
                    ),
                    state_module.CodeFile(
                        path="tests/test_fibonacci.py",
                        content=(
                            "from pathlib import Path\n"
                            "import sys\n\n"
                            "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n\n"
                            "from src.fibonacci import fibonacci\n\n"
                            "def test_fibonacci_values():\n"
                            "    assert fibonacci(0) == 0\n"
                            "    assert fibonacci(1) == 1\n"
                            "    assert fibonacci(7) == 13\n"
                        ),
                    ),
                ),
            ),
        ),
    )
    adapter = CodingProjectAdapter()
    output_dir = tmp_path / "project"
    _ = adapter.export_state(state, output_dir, "main-codebase")
    result = adapter.verify_export(output_dir, state, "main-codebase", sandbox_mode="none")
    assert result is not None
    assert result.passed is True
    assert result.exit_code == 0
    assert "pytest" in result.command


def test_coding_export_creates_nested_parent_directories(tmp_path: Path) -> None:
    import baps.run as run_module

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(
                    state_module.CodeFile(
                        path="pkg/subpkg/fibonacci.py",
                        content="def fibonacci(n):\n    return n\n",
                    ),
                ),
            ),
        ),
    )
    adapter = CodingProjectAdapter()
    _ = adapter.export_state(
        state=state,
        output_path=tmp_path / "project",
        artifact_id="main-codebase",
    )
    assert (tmp_path / "project" / "pkg" / "subpkg" / "fibonacci.py").exists()


def test_coding_export_output_changed_false_when_unchanged(tmp_path: Path) -> None:
    import baps.run as run_module

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(
                    state_module.CodeFile(
                        path="src/fibonacci.py",
                        content="def fibonacci(n):\n    return n\n",
                    ),
                ),
            ),
        ),
    )
    adapter = CodingProjectAdapter()
    output_dir = tmp_path / "project"
    first = adapter.export_state(state, output_dir, "main-codebase")
    second = adapter.export_state(state, output_dir, "main-codebase")
    assert first is True
    assert second is False


def test_document_adapter_verify_export_passes_for_matching_export(tmp_path: Path) -> None:
    import baps.run as run_module

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.DocumentArtifact(
                id="main-document",
                sections=(
                    state_module.Section(title="Introduction", body="Hello"),
                    state_module.Section(title="Conclusion", body="World"),
                ),
            ),
        ),
    )
    adapter = DocumentProjectAdapter()
    output_path = tmp_path / "report.md"
    output_path.write_text("## Introduction\n\nHello\n\n## Conclusion\n\nWorld", encoding="utf-8")
    result = adapter.verify_export(output_path, state, "main-document")
    assert result is not None
    assert result.passed is True
    assert result.exit_code == 0


def test_document_adapter_verify_export_fails_when_section_content_missing(
    tmp_path: Path,
) -> None:
    import baps.run as run_module

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.DocumentArtifact(
                id="main-document",
                sections=(state_module.Section(title="Introduction", body="Hello"),),
            ),
        ),
    )
    adapter = DocumentProjectAdapter()
    output_path = tmp_path / "report.md"
    output_path.write_text("## Different\n\nBody", encoding="utf-8")
    result = adapter.verify_export(output_path, state, "main-document")
    assert result is not None
    assert result.passed is False
    assert result.exit_code == 1
    assert "missing section title: Introduction" in result.stderr


def test_coding_adapter_verify_export_runs_pytest_and_captures_success(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.sandbox as sandbox_module
    import baps.run as run_module

    captured: dict[str, object] = {}

    def _fake_run(args, cwd, capture_output, text, check):
        captured["args"] = args
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="2 passed\n", stderr="")

    monkeypatch.setattr(sandbox_module.subprocess, "run", _fake_run)
    adapter = CodingProjectAdapter()
    output_dir = tmp_path / "project"
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(id="main-codebase", files=()),),
    )
    result = adapter.verify_export(output_dir, state, "main-codebase", sandbox_mode="none")
    assert result is not None
    assert captured["args"] == ["uv", "run", "pytest"]
    assert captured["cwd"] == output_dir
    assert result.command == "uv run pytest"
    assert result.cwd == str(output_dir)
    assert result.exit_code == 0
    assert result.stdout == "2 passed\n"
    assert result.stderr == ""
    assert result.passed is True


def test_coding_adapter_verify_export_captures_failure(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.sandbox as sandbox_module
    import baps.run as run_module

    def _fake_run(args, cwd, capture_output, text, check):
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="1 failed\n", stderr="traceback\n")

    monkeypatch.setattr(sandbox_module.subprocess, "run", _fake_run)
    adapter = CodingProjectAdapter()
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(id="main-codebase", files=()),),
    )
    result = adapter.verify_export(tmp_path / "project", state, "main-codebase", sandbox_mode="none")
    assert result is not None
    assert result.exit_code == 1
    assert result.passed is False
    assert result.stdout == "1 failed\n"
    assert result.stderr == "traceback\n"


def test_coding_adapter_verify_export_fails_for_missing_state_file(tmp_path: Path) -> None:
    import baps.run as run_module

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(
                    state_module.CodeFile(path="src/fibonacci.py", content="def fibonacci(n): return n\n"),
                ),
            ),
        ),
    )
    adapter = CodingProjectAdapter()
    output_dir = tmp_path / "project"
    output_dir.mkdir()
    result = adapter.verify_export(output_dir, state, "main-codebase")
    assert result is not None
    assert result.passed is False
    assert result.exit_code == 1
    assert result.command == "file_presence_check"
    assert "src/fibonacci.py" in result.stderr
    assert "exported files missing from output" in result.stderr


def test_coding_adapter_verify_export_skips_pytest_when_files_missing(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.coding_adapter as coding_module
    import baps.run as run_module

    pytest_called = {"n": 0}

    def _fake_run(*_args, **_kwargs):
        pytest_called["n"] += 1
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(coding_module.subprocess, "run", _fake_run)
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(
                    state_module.CodeFile(path="src/fibonacci.py", content="def fibonacci(n): return n\n"),
                ),
            ),
        ),
    )
    adapter = CodingProjectAdapter()
    output_dir = tmp_path / "project"
    output_dir.mkdir()
    result = adapter.verify_export(output_dir, state, "main-codebase")
    assert result is not None
    assert result.passed is False
    assert pytest_called["n"] == 0


def test_coding_adapter_commit_export_inits_and_commits(monkeypatch, tmp_path: Path) -> None:
    import baps.coding_adapter as coding_module

    calls: list[list[str]] = []

    def _fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(coding_module.subprocess, "run", _fake_run)
    output_dir = tmp_path / "project"
    output_dir.mkdir()
    game_spec = state_module.GameSpec(
        objective="Add fibonacci function",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests pass",
    )
    adapter = CodingProjectAdapter()
    committed = adapter.commit_export(output_dir, game_spec)
    assert committed is True
    assert any(args[:2] == ["git", "init"] for args in calls)
    assert any(args[:3] == ["git", "commit", "-m"] for args in calls)
    commit_call = next(args for args in calls if args[:2] == ["git", "commit"])
    assert commit_call[3] == "baps: Add fibonacci function"


def test_coding_adapter_commit_export_skips_init_when_git_dir_exists(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.coding_adapter as coding_module

    calls: list[list[str]] = []

    def _fake_run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(coding_module.subprocess, "run", _fake_run)
    output_dir = tmp_path / "project"
    output_dir.mkdir()
    (output_dir / ".git").mkdir()
    game_spec = state_module.GameSpec(
        objective="Fix tests",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests pass",
    )
    adapter = CodingProjectAdapter()
    adapter.commit_export(output_dir, game_spec)
    assert not any(args[:2] == ["git", "init"] for args in calls)


def test_coding_adapter_commit_export_returns_false_when_git_unavailable(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.coding_adapter as coding_module

    def _fake_run(args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(coding_module.subprocess, "run", _fake_run)
    output_dir = tmp_path / "project"
    output_dir.mkdir()
    game_spec = state_module.GameSpec(
        objective="Add feature",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests pass",
    )
    adapter = CodingProjectAdapter()
    committed = adapter.commit_export(output_dir, game_spec)
    assert committed is False


def test_coding_adapter_commit_export_returns_false_when_commit_fails(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.coding_adapter as coding_module

    def _fake_run(args, **kwargs):
        returncode = 1 if args[:2] == ["git", "commit"] else 0
        return subprocess.CompletedProcess(args=args, returncode=returncode, stdout="", stderr="")

    monkeypatch.setattr(coding_module.subprocess, "run", _fake_run)
    output_dir = tmp_path / "project"
    output_dir.mkdir()
    (output_dir / ".git").mkdir()
    game_spec = state_module.GameSpec(
        objective="Fix tests",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests pass",
    )
    adapter = CodingProjectAdapter()
    committed = adapter.commit_export(output_dir, game_spec)
    assert committed is False


def test_commit_export_with_adapter_calls_adapter_method(monkeypatch, tmp_path: Path) -> None:
    import baps.run as run_module

    committed_args: list = []

    class _CommittingAdapter:
        project_type = "coding"

        def commit_export(self, output_path, game_spec):
            committed_args.append((output_path, game_spec))
            return True

    game_spec = state_module.GameSpec(
        objective="Add feature",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests pass",
    )
    output_dir = tmp_path / "project"
    output_dir.mkdir()
    result = _commit_export_with_adapter(_CommittingAdapter(), output_dir, game_spec)
    assert result is True
    assert committed_args == [(output_dir, game_spec)]


def test_commit_export_with_adapter_skips_adapter_without_method(tmp_path: Path) -> None:
    import baps.run as run_module

    class _NoCommitAdapter:
        project_type = "coding"

    game_spec = state_module.GameSpec(
        objective="Add feature",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests pass",
    )
    result = _commit_export_with_adapter(
        _NoCommitAdapter(), tmp_path / "project", game_spec
    )
    assert result is False


def test_document_adapter_render_create_game_prompt_supplement_includes_delta_guidance() -> None:
    import baps.run as run_module

    adapter = DocumentProjectAdapter()
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="main-document", sections=()),),
    )
    from baps.northstar_projection import ProjectionType, StateView
    state_view = StateView(
        id="sv:test",
        projection_type=ProjectionType.NORTH_STAR,
        content="state view content",
        input_fingerprint="x",
        metadata={},
    )
    result = adapter.render_create_game_prompt_supplement(
        state=state,
        config={"artifact_id": "main-document", "northstar_markdown": "goal"},
        state_view=state_view,
        verification_result=None,
    )
    assert "append_section" in result
    assert "modify_section" in result


def test_document_adapter_render_create_game_prompt_supplement_includes_guidance_on_failure() -> None:
    import baps.run as run_module

    adapter = DocumentProjectAdapter()
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="main-document", sections=()),),
    )
    from baps.northstar_projection import ProjectionType, StateView
    state_view = StateView(
        id="sv:test",
        projection_type=ProjectionType.NORTH_STAR,
        content="state view content",
        input_fingerprint="x",
        metadata={},
    )
    verification_result = VerificationResult(
        command="document_export_consistency_check",
        cwd="/tmp",
        exit_code=1,
        stdout="",
        stderr="missing section title: Introduction",
        passed=False,
    )
    result = adapter.render_create_game_prompt_supplement(
        state=state,
        config={"artifact_id": "main-document", "northstar_markdown": "goal"},
        state_view=state_view,
        verification_result=verification_result,
    )
    assert "Document CreateGame verification evidence" in result
    assert "missing sections" in result


def test_coding_run_no_files_keeps_output_exported_false(monkeypatch, tmp_path: Path, capsys) -> None:
    import baps.run as run_module

    workspace = tmp_path / "coding-empty-export"
    monkeypatch.setattr(
        "baps.orchestration.create_game",
        lambda *_args, **_kwargs: GameSpec(
            objective="No-op coding objective",
            target_artifact_id="main-codebase",
            allowed_delta_type="DeltaCodingState",
            success_condition="No file changes required",
        ),
    )
    monkeypatch.setattr("baps.orchestration.play_game", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "coding",
            "--artifact-id",
            "main-codebase",
            "--goal",
            "No-op coding objective",
            "--output",
            "output/project",
            "--max-iterations",
            "1",
            "--language",
            "python",
        ],
    )
    run_module.main()
    out = capsys.readouterr().out
    assert "output_exported=False" in out
    assert "output_changed=False" in out
    assert "verification_run=False" in out


def test_coding_run_summary_includes_verification_status(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    import baps.run as run_module

    workspace = tmp_path / "coding-verify-summary"

    monkeypatch.setattr(
        "baps.orchestration.create_game",
        lambda *_args, **_kwargs: GameSpec(
            objective="Write one file",
            target_artifact_id="main-codebase",
            allowed_delta_type="DeltaCodingState",
            success_condition="File exists",
        ),
    )
    monkeypatch.setattr(
        "baps.orchestration.play_game",
        lambda *_args, **_kwargs: state_module.DeltaCodingState(
            artifact_id="main-codebase",
            operation="write_file",
            payload=state_module.WriteFileDelta(
                file=state_module.CodeFile(
                    path="src/fibonacci.py",
                    content="def fibonacci(n):\n    return n\n",
                )
            ),
        ),
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "coding",
            "--artifact-id",
            "main-codebase",
            "--goal",
            "Implement Fibonacci with tests.",
            "--output",
            "output/project",
            "--max-iterations",
            "1",
            "--sandbox",
            "none",
            "--language",
            "python",
        ],
    )
    run_module.main()
    out = capsys.readouterr().out
    assert "verification_run=True" in out
    assert "verification_passed=" in out
    assert "verification_exit_code=" in out
    assert "verification_command=" in out
    assert "verification_cwd=" in out


def test_document_run_runs_verification(monkeypatch, tmp_path: Path, capsys) -> None:
    import baps.run as run_module

    workspace = tmp_path / "document-no-verify"
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
            "--goal", "Write a report.", "--output", "output/report.md",
            "--max-iterations",
            "1",
        ],
    )
    run_module.main()
    out = capsys.readouterr().out
    assert "verification_run=True" in out
    assert "verification_passed=True" in out
    assert "verification_command=document_export_consistency_check" in out


def test_coding_init_and_run_exports_fibonacci_files(monkeypatch, tmp_path: Path) -> None:
    import baps.run as run_module

    workspace = tmp_path / "coding-workspace"
    output_dir = workspace / "output" / "project"

    monkeypatch.setattr(
        "baps.orchestration.create_game",
        lambda *_args, **_kwargs: GameSpec(
            objective="Write fibonacci implementation file",
            target_artifact_id="main-codebase",
            allowed_delta_type="DeltaCodingState",
            success_condition="src/fibonacci.py and tests/test_fibonacci.py exist",
        ),
    )

    call_counter = {"count": 0}

    def _play_game(_state, _game_spec, adapter=None, verification_result=None, **_kwargs):
        call_counter["count"] += 1
        if call_counter["count"] == 1:
            return state_module.DeltaCodingState(
                artifact_id="main-codebase",
                operation="write_file",
                payload=state_module.WriteFileDelta(
                    file=state_module.CodeFile(
                        path="src/fibonacci.py",
                        content=(
                            "def fibonacci(n):\n"
                            "    if n < 0:\n"
                            "        raise ValueError('n must be >= 0')\n"
                            "    if n < 2:\n"
                            "        return n\n"
                            "    a, b = 0, 1\n"
                            "    for _ in range(2, n + 1):\n"
                            "        a, b = b, a + b\n"
                            "    return b\n"
                        ),
                    )
                ),
            )
        if call_counter["count"] == 2:
            return state_module.DeltaCodingState(
                artifact_id="main-codebase",
                operation="write_file",
                payload=state_module.WriteFileDelta(
                    file=state_module.CodeFile(
                        path="tests/test_fibonacci.py",
                        content=(
                            "from src.fibonacci import fibonacci\n\n"
                            "def test_fibonacci_base_cases():\n"
                            "    assert fibonacci(0) == 0\n"
                            "    assert fibonacci(1) == 1\n\n"
                            "def test_fibonacci_sequence():\n"
                            "    assert fibonacci(7) == 13\n"
                        ),
                    )
                ),
            )
        return None

    monkeypatch.setattr("baps.orchestration.play_game", _play_game)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "coding",
            "--artifact-id",
            "main-codebase",
            "--goal",
            "Implement Fibonacci with tests.",
            "--output",
            str(output_dir),
            "--max-iterations",
            "2",
            "--sandbox",
            "none",
            "--language",
            "python",
        ],
    )

    run_module.main()
    assert (output_dir / "src" / "fibonacci.py").exists()
    assert (output_dir / "tests" / "test_fibonacci.py").exists()


def test_coding_example_output_path_resolves_under_workspace() -> None:
    import baps.run as run_module

    args = argparse.Namespace(
        command="start",
        spec="examples/coding-project.yaml",
        workspace=None,
        project_type=None,
        artifact_id=None,
        goal=None,
        output=None,
        max_iterations=None,
    )
    config = run_module.resolve_run_config(args)
    assert config["workspace"] == Path(".baps-workspace/coding-project")
    assert config["output_path"] == Path(".baps-workspace/coding-project/output/project").resolve()

def test_play_game_uses_adapter_provided_state_view_prompt_and_parser() -> None:
    import baps.run as run_module
    from baps.models import ToolDefinition

    class _PlayAdapter:
        project_type = "document"
        supported_delta_type = "DeltaDocumentState"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def create_initial_state(self, _config):
            raise NotImplementedError

        def build_state_view(self, _state, _game_spec):
            self.calls.append("build_state_view")
            return StateView(
                id="state-view:test",
                projection_type=ProjectionType.NORTH_STAR,
                content="{}",
                input_fingerprint="x",
                metadata={},
            )

        def render_blue_prompt(
            self, _state_view, _game_spec, _attempt_number, _previous_feedback
        ):
            self.calls.append("render_blue_prompt")
            return "blue-prompt"

        def build_blue_output_format(self):
            return None

        def build_blue_tools(self):
            self.calls.append("build_blue_tools")
            return [ToolDefinition(name="append_section", description="Append", parameters={})]

        def tool_call_to_delta(self, _tool_call):
            self.calls.append("tool_call_to_delta")
            return state_module.DeltaDocumentState(
                artifact_id="main-document",
                operation="append_section",
                payload=state_module.AppendSectionDelta(
                    section=state_module.Section(title="Intro", body="Body")
                ),
            )

        def delta_to_state_update(self, _delta_state):
            raise NotImplementedError

    adapter = _PlayAdapter()
    spec = GameSpec(
        objective="Add section",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="section exists",
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="main-document", sections=()),),
    )
    delta = run_module.play_game(
        state,
        spec,
        adapter=adapter,
        model_client=FakeModelClient(
            tool_responses=[ToolCall("append_section", {"artifact_id": "main-document", "title": "Intro", "body": "Body"})]
        ),
        red_model_client=FakeModelClient(['{"disposition":"accept","rationale":"ok"}']),
        referee_model_client=FakeModelClient(['{"disposition":"accept","rationale":"ok"}']),
    )
    assert isinstance(delta, state_module.DeltaDocumentState)
    assert adapter.calls == ["build_state_view", "render_blue_prompt", "build_blue_tools", "tool_call_to_delta"]


def test_integration_uses_adapter_delta_to_update_mapper() -> None:
    import baps.run as run_module

    class _MapperAdapter:
        project_type = "document"
        supported_delta_type = "DeltaDocumentState"

        def create_initial_state(self, _config):
            raise NotImplementedError

        def build_state_view(self, _state, _game_spec):
            raise NotImplementedError

        def render_blue_prompt(
            self, _state_view, _game_spec, _attempt_number, _previous_feedback
        ):
            raise NotImplementedError

        def parse_blue_delta(self, _text):
            raise NotImplementedError

        def delta_to_state_update(self, delta_state):
                return StateUpdateProposal(
                    id="mapped",
                    target=state_module.StateUpdateTarget(artifact_id=delta_state.artifact_id),
                    summary="mapped",
                    payload={
                        "operation": "replace_artifact",
                    "artifact": {"id": delta_state.artifact_id, "kind": "document"},
                },
            )

    delta = state_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=state_module.AppendSectionDelta(
            section=state_module.Section(title="T", body="B")
        ),
    )
    proposal = _derive_state_update_from_delta(delta, adapter=_MapperAdapter())
    assert proposal.id == "mapped"


def test_run_module_has_no_legacy_compatibility_shim_wrappers() -> None:
    import baps.run as run_module

    assert not hasattr(run_module, "_build_blue_state_view")
    assert not hasattr(run_module, "_parse_blue_delta_json")
    assert not hasattr(run_module, "_create_game_with_adapter")
    assert not hasattr(run_module, "_play_game_with_adapter")
    src = inspect.getsource(_run_project_iterations)
    assert "TypeError" not in src


def test_run_module_has_no_global_verification_fallback() -> None:
    run_source = Path("src/baps/run.py").read_text(encoding="utf-8")
    assert "_LAST_VERIFICATION_RESULT" not in run_source


def test_run_module_does_not_import_deleted_legacy_modules() -> None:
    import baps.run as run_module

    src = inspect.getsource(run_module)
    forbidden = (
        "baps.runtime",
        "baps.game_service",
        "baps.runtime_integration",
        "baps.autonomous",
        "baps.planner",
        "baps.projections",
    )
    for item in forbidden:
        assert item not in src


def test_coding_iteration_two_does_not_receive_stale_verification_result(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.run as run_module

    workspace = tmp_path / "coding-no-stale-verification"
    verification_seen: list[object] = []
    call_counter = {"count": 0}

    def _create_game(_config, _state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        del verification_result
        call_counter["count"] += 1
        if call_counter["count"] == 1:
            return GameSpec(
                objective="Write src/fibonacci.py containing implementation",
                target_artifact_id="main-codebase",
                allowed_delta_type="DeltaCodingState",
                success_condition="src/fibonacci.py exists",
            )
        if call_counter["count"] == 2:
            return GameSpec(
                objective="Write tests/test_fibonacci.py containing tests",
                target_artifact_id="main-codebase",
                allowed_delta_type="DeltaCodingState",
                success_condition="tests/test_fibonacci.py exists",
            )
        raise NoNewGameError("done")

    def _play_game(_state, spec, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        verification_seen.append(verification_result)
        if "src/fibonacci.py" in spec.objective:
            return state_module.DeltaCodingState(
                artifact_id="main-codebase",
                operation="write_file",
                payload=state_module.WriteFileDelta(
                    file=state_module.CodeFile(
                        path="src/fibonacci.py",
                        content="def fibonacci(n):\n    return n\n",
                    )
                ),
            )
        if "tests/test_fibonacci.py" in spec.objective:
            return state_module.DeltaCodingState(
                artifact_id="main-codebase",
                operation="write_file",
                payload=state_module.WriteFileDelta(
                    file=state_module.CodeFile(
                        path="tests/test_fibonacci.py",
                        content="def test_smoke():\n    assert True\n",
                    )
                ),
            )
        return None

    monkeypatch.setattr("baps.orchestration.create_game", _create_game)
    monkeypatch.setattr("baps.orchestration.play_game", _play_game)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "coding",
            "--artifact-id",
            "main-codebase",
            "--goal",
            "Implement Fibonacci with tests.",
            "--output",
            "output/project",
            "--max-iterations",
            "2",
            "--sandbox",
            "none",
            "--language",
            "python",
        ],
    )
    run_module.main()
    assert verification_seen[0] is None  # first iteration: no prior export yet
    assert isinstance(verification_seen[1], VerificationResult)  # second iteration: receives prior export result


def test_coding_create_game_receives_previous_verification_result_second_iteration(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.run as run_module

    workspace = tmp_path / "coding-create-game-verification-input"
    seen: list[VerificationResult | None] = []
    create_count = {"n": 0}

    def _create_game(_config, _state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        del adapter
        seen.append(verification_result)
        create_count["n"] += 1
        if create_count["n"] == 1:
            return GameSpec(
                objective="Write src/fibonacci.py containing implementation",
                target_artifact_id="main-codebase",
                allowed_delta_type="DeltaCodingState",
                success_condition="src/fibonacci.py exists",
            )
        if create_count["n"] == 2:
            return GameSpec(
                objective="Write tests/test_fibonacci.py containing tests",
                target_artifact_id="main-codebase",
                allowed_delta_type="DeltaCodingState",
                success_condition="tests/test_fibonacci.py exists",
            )
        raise NoNewGameError("done")

    def _play_game(_state, spec, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        del adapter, verification_result
        if "src/fibonacci.py" in spec.objective:
            return state_module.DeltaCodingState(
                artifact_id="main-codebase",
                operation="write_file",
                payload=state_module.WriteFileDelta(
                    file=state_module.CodeFile(
                        path="src/fibonacci.py",
                        content="def fibonacci(n):\n    return n\n",
                    )
                ),
            )
        return state_module.DeltaCodingState(
            artifact_id="main-codebase",
            operation="write_file",
            payload=state_module.WriteFileDelta(
                file=state_module.CodeFile(
                    path="tests/test_fibonacci.py",
                    content="def test_smoke():\n    assert True\n",
                )
            ),
        )

    verify_calls = {"n": 0}

    def _verify_export(_adapter, _output_path, _state, _artifact_id, **_kwargs):
        verify_calls["n"] += 1
        if verify_calls["n"] == 1:
            return VerificationResult(
                command="uv run pytest",
                cwd=str(workspace / "output" / "project"),
                exit_code=2,
                stdout="ModuleNotFoundError: No module named 'src'",
                stderr="",
                passed=False,
            )
        return VerificationResult(
            command="uv run pytest",
            cwd=str(workspace / "output" / "project"),
            exit_code=0,
            stdout="1 passed",
            stderr="",
            passed=True,
        )

    monkeypatch.setattr("baps.orchestration.create_game", _create_game)
    monkeypatch.setattr("baps.orchestration.play_game", _play_game)
    monkeypatch.setattr("baps.orchestration._verify_export_with_adapter", _verify_export)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "coding",
            "--artifact-id",
            "main-codebase",
            "--goal",
            "Implement Fibonacci with tests.",
            "--output",
            "output/project",
            "--max-iterations",
            "2",
            "--language",
            "python",
        ],
    )
    run_module.main()

    assert len(seen) >= 2
    assert seen[0] is None
    assert seen[1] is not None
    assert seen[1].exit_code == 2


def test_active_main_and_play_game_orchestration_have_no_direct_document_mechanics() -> None:
    import baps.run as run_module

    main_src = inspect.getsource(run_module.main)
    play_src = inspect.getsource(run_module.play_game)
    for token in ("DocumentArtifact", "DeltaDocumentState", "append_section", "sections"):
        assert token not in main_src
        assert token not in play_src


def test_run_py_adapter_boundary_regression_guards() -> None:
    run_source = Path("src/baps/run.py").read_text(encoding="utf-8")

    forbidden_helpers = (
        "_build_document_state_view",
        "_build_coding_state_view",
        "_build_create_game_state_view",
    )
    for name in forbidden_helpers:
        assert name not in run_source

    forbidden_symbols = (
        "DocumentArtifact",
        "CodingArtifact",
        "Section",
        "CodeFile",
    )
    for symbol in forbidden_symbols:
        assert symbol not in run_source

    assert ".sections" not in run_source
    assert ".files" not in run_source


# ---------------------------------------------------------------------------
# NorthStarUpdateNeededError — parse, prompt, and lifecycle tests
# ---------------------------------------------------------------------------


def test_create_game_northstar_update_needed_signal_raises_error() -> None:
    import baps.run as run_module

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "goal": "Write a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = run_module.create_state(config)
    response = json.dumps({
        "northstar_update_needed": True,
        "rationale": "State has drifted from NorthStar goal.",
        "proposed_northstar": "# Revised Goal\n\nNew direction.",
    })
    with pytest.raises(NorthStarUpdateNeededError) as exc_info:
        run_module.create_game(
            config, state, model_client=FakeModelClient([response])
        )

    assert "drifted" in exc_info.value.rationale
    assert "Revised" in exc_info.value.proposed_northstar


def test_coding_adapter_maps_write_files_batch_delta_to_state_update() -> None:

    adapter = CodingProjectAdapter()
    delta = state_module.DeltaCodingBatchState(
        artifact_id="main-codebase",
        operation="write_files",
        payload=state_module.WriteFilesDelta(
            files=(
                state_module.CodeFile(path="src/a.py", content="a"),
                state_module.CodeFile(path="src/b.py", content="b"),
            )
        ),
    )
    proposal = adapter.delta_to_state_update(delta)
    assert proposal.payload.operation == "write_files"
    assert len(proposal.payload.files) == 2
    assert proposal.payload.files[0].path == "src/a.py"


def test_coding_adapter_tool_call_write_files_returns_batch_delta() -> None:
    from baps.models import ToolCall

    adapter = CodingProjectAdapter()
    tool_call = ToolCall(
        name="write_files",
        arguments={
            "artifact_id": "main-codebase",
            "files": [
                {"path": "src/a.py", "content": "a"},
                {"path": "src/b.py", "content": "b"},
            ],
        },
    )
    delta = adapter.tool_call_to_delta(tool_call)
    assert isinstance(delta, state_module.DeltaCodingBatchState)
    assert len(delta.payload.files) == 2


# --- modify_section adapter tests ---

def test_document_adapter_maps_modify_section_delta_to_state_update() -> None:

    adapter = DocumentProjectAdapter()
    delta = state_module.DeltaModifyDocumentState(
        artifact_id="main-document",
        operation="modify_section",
        payload=state_module.ModifySectionDelta(
            section_title="Intro",
            new_body="Updated intro.",
        ),
    )
    proposal = adapter.delta_to_state_update(delta)
    assert proposal.payload.operation == "modify_section"
    assert proposal.payload.section_title == "Intro"
    assert proposal.payload.new_body == "Updated intro."


def test_document_adapter_tool_call_modify_section_returns_correct_delta() -> None:
    from baps.models import ToolCall

    adapter = DocumentProjectAdapter()
    tool_call = ToolCall(
        name="modify_section",
        arguments={
            "artifact_id": "main-document",
            "section_title": "Intro",
            "new_body": "New body.",
        },
    )
    delta = adapter.tool_call_to_delta(tool_call)
    assert isinstance(delta, state_module.DeltaModifyDocumentState)
    assert delta.payload.section_title == "Intro"


def test_coding_adapter_maps_delete_file_delta_to_state_update() -> None:

    adapter = CodingProjectAdapter()
    delta = state_module.DeltaDeleteCodingState(
        artifact_id="main-codebase",
        operation="delete_file",
        payload=state_module.DeleteFileDelta(path="src/old.py"),
    )
    proposal = adapter.delta_to_state_update(delta)
    assert proposal.payload.operation == "delete_file"
    assert proposal.payload.path == "src/old.py"


def test_coding_adapter_tool_call_delete_file_returns_correct_delta() -> None:
    from baps.models import ToolCall

    adapter = CodingProjectAdapter()
    tool_call = ToolCall(
        name="delete_file",
        arguments={"artifact_id": "main-codebase", "path": "src/old.py"},
    )
    delta = adapter.tool_call_to_delta(tool_call)
    assert isinstance(delta, state_module.DeltaDeleteCodingState)
    assert delta.payload.path == "src/old.py"


# --- delete_section adapter tests ---

def test_document_adapter_maps_delete_section_delta_to_state_update() -> None:

    adapter = DocumentProjectAdapter()
    delta = state_module.DeltaDeleteDocumentState(
        artifact_id="main-document",
        operation="delete_section",
        payload=state_module.DeleteSectionDelta(section_title="Obsolete"),
    )
    proposal = adapter.delta_to_state_update(delta)
    assert proposal.payload.operation == "delete_section"
    assert proposal.payload.section_title == "Obsolete"


def test_document_adapter_tool_call_delete_section_returns_correct_delta() -> None:
    from baps.models import ToolCall

    adapter = DocumentProjectAdapter()
    tool_call = ToolCall(
        name="delete_section",
        arguments={"artifact_id": "main-document", "section_title": "Obsolete"},
    )
    delta = adapter.tool_call_to_delta(tool_call)
    assert isinstance(delta, state_module.DeltaDeleteDocumentState)
    assert delta.payload.section_title == "Obsolete"


# --- CreateGame coding state view shows file contents ---

def test_coding_create_game_state_view_includes_file_contents() -> None:
    import baps.run as run_module

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(
            id="main-codebase",
            files=(
                state_module.CodeFile(path="src/hello.py", content="def hello():\n    return 'hi'\n"),
            ),
        ),),
    )
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "coding",
        "artifact_id": "main-codebase",
        "goal": "Build something",
        "northstar_markdown": "# Goal",
        "output_path": Path(".baps-workspace/output"),
        "max_iterations": 1,
        "spec_path": None,
    }
    adapter = CodingProjectAdapter()
    view = adapter.build_create_game_state_view(state, config)
    assert "src/hello.py" in view.content
    assert "def hello():" in view.content


def test_coding_create_game_state_view_truncates_long_files() -> None:
    import baps.run as run_module

    long_content = "\n".join(f"line_{i} = {i}" for i in range(100))
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(
            id="main-codebase",
            files=(state_module.CodeFile(path="src/big.py", content=long_content),),
        ),),
    )
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "coding",
        "artifact_id": "main-codebase",
        "goal": "Build something",
        "northstar_markdown": "# Goal",
        "output_path": Path(".baps-workspace/output"),
        "max_iterations": 1,
        "spec_path": None,
    }
    adapter = CodingProjectAdapter()
    view = adapter.build_create_game_state_view(state, config)
    assert "more lines" in view.content
    assert "line_0 = 0" in view.content
    assert "line_99 = 99" not in view.content


# ---------------------------------------------------------------------------
# Multiscale / decompose tests
# ---------------------------------------------------------------------------

def test_resolve_run_config_max_sub_gaps_defaults_to_5(tmp_path: Path) -> None:
    import argparse
    import baps.run as run_module

    (tmp_path / "ns.md").write_text("NorthStar")
    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_path": str(tmp_path / "ns.md"),
        "goal": "write a doc",
        "output": "out/doc.md",
    }
    import yaml
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path),
        workspace=str(tmp_path / "ws"),
        artifact_id=None,
        goal=None,
        output=None,
        max_iterations=None,
        project_type=None,
        sandbox=None,
        command=None,
    )
    config = run_module.resolve_run_config(args)
    assert config["max_sub_gaps"] == 5


def test_resolve_run_config_max_sub_gaps_from_spec(tmp_path: Path) -> None:
    import argparse
    import baps.run as run_module

    (tmp_path / "ns.md").write_text("NorthStar")
    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_path": str(tmp_path / "ns.md"),
        "goal": "write a doc",
        "output": "out/doc.md",
        "max_sub_gaps": 3,
    }
    import yaml
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path),
        workspace=str(tmp_path / "ws"),
        artifact_id=None,
        goal=None,
        output=None,
        max_iterations=None,
        project_type=None,
        sandbox=None,
        command=None,
    )
    config = run_module.resolve_run_config(args)
    assert config["max_sub_gaps"] == 3


def test_resolve_run_config_max_sub_gaps_zero_raises(tmp_path: Path) -> None:
    import argparse
    import pytest
    import baps.run as run_module

    (tmp_path / "ns.md").write_text("NorthStar")
    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_path": str(tmp_path / "ns.md"),
        "goal": "write a doc",
        "output": "out/doc.md",
        "max_sub_gaps": 0,
    }
    import yaml
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path),
        workspace=str(tmp_path / "ws"),
        artifact_id=None,
        goal=None,
        output=None,
        max_iterations=None,
        project_type=None,
        sandbox=None,
        command=None,
    )
    with pytest.raises(ValueError, match="max_sub_gaps must be >= 1"):
        run_module.resolve_run_config(args)


def test_resolve_run_config_max_sub_gaps_non_integer_raises(tmp_path: Path) -> None:
    import argparse
    import pytest
    import baps.run as run_module

    (tmp_path / "ns.md").write_text("NorthStar")
    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_path": str(tmp_path / "ns.md"),
        "goal": "write a doc",
        "output": "out/doc.md",
        "max_sub_gaps": "lots",
    }
    import yaml
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path),
        workspace=str(tmp_path / "ws"),
        artifact_id=None,
        goal=None,
        output=None,
        max_iterations=None,
        project_type=None,
        sandbox=None,
        command=None,
    )
    with pytest.raises(ValueError, match="max_sub_gaps must be an integer"):
        run_module.resolve_run_config(args)


def test_resolve_run_config_language_zig_propagates_to_config(tmp_path: Path) -> None:
    import argparse
    import yaml
    import baps.run as run_module

    spec = {
        "project_type": "coding",
        "artifact_id": "mycode",
        "northstar_markdown": "Build a stack",
        "language": "zig",
        "goal": "implement a stack",
        "output": "output/zig-proj",
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path),
        workspace=str(tmp_path / "ws"),
        artifact_id=None,
        goal=None,
        output=None,
        max_iterations=None,
        project_type=None,
        sandbox=None,
        command=None,
    )
    config = run_module.resolve_run_config(args)
    assert config["language"] == "zig"


def test_resolve_run_config_language_absent_leaves_empty_string(tmp_path: Path) -> None:
    import argparse
    import yaml
    import baps.run as run_module

    spec = {
        "project_type": "coding",
        "artifact_id": "mycode",
        "northstar_markdown": "Build a thing",
        "goal": "implement something",
        "output": "output/proj",
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path),
        workspace=str(tmp_path / "ws"),
        artifact_id=None,
        goal=None,
        output=None,
        max_iterations=None,
        project_type=None,
        sandbox=None,
        command=None,
    )
    config = run_module.resolve_run_config(args)
    assert config["language"] == ""


def test_coding_blue_prompt_includes_prior_export_failures() -> None:
    from baps.coding_adapter import render_coding_blue_prompt
    from baps.language_python import PythonLanguagePlugin
    from baps.northstar_projection import ProjectionType, StateView
    import baps.run as run_module

    state_view = StateView(
        id="sv:test",
        projection_type=ProjectionType.NORTH_STAR,
        content="=== StateView Start ===\n=== StateView End ===",
        input_fingerprint="abc",
        metadata={},
    )
    game_spec = GameSpec(
        objective="Fix failing tests",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests pass",
    )
    previous_feedback = {
        "prior_export_verification": {
            "exit_code": 1,
            "passed": False,
            "stdout": "FAILED tests/test_foo.py::test_bar - AssertionError: wrong\n",
            "stderr": "",
        }
    }
    prompt = render_coding_blue_prompt(
        state_view=state_view,
        game_spec=game_spec,
        attempt_number=1,
        previous_feedback=previous_feedback,
        plugin=PythonLanguagePlugin(),
    )
    assert "tests/test_foo.py::test_bar" in prompt
    assert "AssertionError: wrong" in prompt
    assert "Fix these specific test failures" in prompt


def test_coding_blue_prompt_no_verification_section_when_feedback_is_none() -> None:
    from baps.coding_adapter import render_coding_blue_prompt
    from baps.language_python import PythonLanguagePlugin
    from baps.northstar_projection import ProjectionType, StateView
    import baps.run as run_module

    state_view = StateView(
        id="sv:test",
        projection_type=ProjectionType.NORTH_STAR,
        content="=== StateView Start ===\n=== StateView End ===",
        input_fingerprint="abc",
        metadata={},
    )
    game_spec = GameSpec(
        objective="Write code",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="code written",
    )
    prompt = render_coding_blue_prompt(
        state_view=state_view,
        game_spec=game_spec,
        attempt_number=1,
        previous_feedback=None,
        plugin=PythonLanguagePlugin(),
    )
    assert "Prior export verification" not in prompt
    assert "Fix these specific test failures" not in prompt


def test_play_game_pre_seeds_verification_result_as_previous_feedback(monkeypatch) -> None:
    import baps.run as run_module

    captured_feedback: list[object] = []

    class _CapturingAdapter:
        project_type = "coding"
        supported_delta_type = "DeltaCodingState"

        def build_state_view(self, state, game_spec):
            from baps.northstar_projection import ProjectionType, StateView
            return StateView(
                id="sv", projection_type=ProjectionType.NORTH_STAR,
                content="view", input_fingerprint="fp", metadata={}
            )

        def render_blue_prompt(self, state_view, game_spec, attempt_number, previous_feedback):
            captured_feedback.append(previous_feedback)
            return "blue prompt"

        def build_blue_output_format(self):
            return None

        def build_blue_tools(self):
            return []

        def parse_blue_delta(self, text):
            raise ValueError("no delta — max_attempts=1 so this exhausts attempts")

        def render_red_prompt_supplement(self, *a, **kw):
            return ""

        def render_referee_prompt_supplement(self, *a, **kw):
            return ""

        def delta_to_state_update(self, delta):
            raise ValueError("unused")

    vr = VerificationResult(
        command="uv run pytest", cwd="/tmp", exit_code=1,
        stdout="FAILED tests/test_foo.py::test_x - AssertionError\n",
        stderr="", passed=False,
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(id="main-codebase", files=()),),
    )
    game_spec = GameSpec(
        objective="Fix tests",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests pass",
    )

    # tool_responses=[None] makes generate_with_tools return None → falls through to generate().
    # parse_blue_delta raises ValueError → attempt exhausted → returns None.
    result = run_module.play_game(
        state, game_spec,
        adapter=_CapturingAdapter(),
        model_client=FakeModelClient(tool_responses=[None], responses=["not valid json"]),
        red_model_client=FakeModelClient(responses=[]),
        referee_model_client=FakeModelClient(responses=[]),
        verification_result=vr,
        max_attempts=1,
    )

    assert result is None
    assert len(captured_feedback) >= 1
    fb = captured_feedback[0]
    assert fb is not None
    assert "prior_export_verification" in fb
    assert fb["prior_export_verification"]["exit_code"] == 1
    assert fb["prior_export_verification"]["passed"] is False


# ---------------------------------------------------------------------------
# Phase 2: Candidate verification within PlayGame
# ---------------------------------------------------------------------------

def test_apply_delta_to_files_write_file() -> None:
    from baps.coding_adapter import _apply_delta_to_files

    existing = (
        state_module.CodeFile(path="src/a.py", content="old"),
    )
    delta = state_module.DeltaCodingState(
        artifact_id="art",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(path="src/a.py", content="new")
        ),
    )
    result = _apply_delta_to_files(existing, delta)
    assert len(result) == 1
    assert result[0].content == "new"


def test_apply_delta_to_files_write_files_adds_and_replaces() -> None:
    from baps.coding_adapter import _apply_delta_to_files

    existing = (
        state_module.CodeFile(path="src/a.py", content="old_a"),
    )
    delta = state_module.DeltaCodingBatchState(
        artifact_id="art",
        operation="write_files",
        payload=state_module.WriteFilesDelta(files=[
            state_module.CodeFile(path="src/a.py", content="new_a"),
            state_module.CodeFile(path="src/b.py", content="b_content"),
        ]),
    )
    result = _apply_delta_to_files(existing, delta)
    paths = {f.path for f in result}
    assert paths == {"src/a.py", "src/b.py"}
    a = next(f for f in result if f.path == "src/a.py")
    assert a.content == "new_a"


def test_apply_delta_to_files_delete_file() -> None:
    from baps.coding_adapter import _apply_delta_to_files

    existing = (
        state_module.CodeFile(path="src/a.py", content="a"),
        state_module.CodeFile(path="src/b.py", content="b"),
    )
    delta = state_module.DeltaDeleteCodingState(
        artifact_id="art",
        operation="delete_file",
        payload=state_module.DeleteFileDelta(path="src/a.py"),
    )
    result = _apply_delta_to_files(existing, delta)
    assert len(result) == 1
    assert result[0].path == "src/b.py"


def test_verify_candidate_returns_none_when_no_test_files() -> None:
    from baps.coding_adapter import CodingProjectAdapter

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(
            id="art",
            files=(state_module.CodeFile(path="src/foo.py", content="x = 1"),),
        ),),
    )
    delta = state_module.DeltaCodingState(
        artifact_id="art",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(path="src/bar.py", content="y = 2")
        ),
    )
    result = CodingProjectAdapter().verify_candidate(delta, state, "art")
    assert result is None


def test_verify_candidate_passes_when_tests_pass(tmp_path) -> None:
    from baps.coding_adapter import CodingProjectAdapter

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(
            id="art",
            files=(state_module.CodeFile(path="src/calc.py", content="def add(a, b):\n    return a + b\n"),),
        ),),
    )
    delta = state_module.DeltaCodingState(
        artifact_id="art",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(
                path="tests/test_calc.py",
                content=(
                    "import sys, os\n"
                    "sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))\n"
                    "from calc import add\n"
                    "def test_add():\n"
                    "    assert add(1, 2) == 3\n"
                ),
            )
        ),
    )
    result = CodingProjectAdapter().verify_candidate(delta, state, "art", sandbox_mode="none")
    assert result is not None
    assert result.passed is True
    assert result.exit_code == 0


def test_verify_candidate_fails_when_tests_fail() -> None:
    from baps.coding_adapter import CodingProjectAdapter

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(
            id="art",
            files=(state_module.CodeFile(path="src/calc.py", content="def add(a, b):\n    return 99\n"),),
        ),),
    )
    delta = state_module.DeltaCodingState(
        artifact_id="art",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(
                path="tests/test_calc.py",
                content=(
                    "import sys, os\n"
                    "sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))\n"
                    "from calc import add\n"
                    "def test_add():\n"
                    "    assert add(1, 2) == 3\n"
                ),
            )
        ),
    )
    result = CodingProjectAdapter().verify_candidate(delta, state, "art", sandbox_mode="none")
    assert result is not None
    assert result.passed is False
    assert result.exit_code == 1


def test_coding_blue_prompt_includes_candidate_verification_failures() -> None:
    from baps.coding_adapter import render_coding_blue_prompt
    from baps.language_python import PythonLanguagePlugin
    from baps.northstar_projection import ProjectionType, StateView
    import baps.run as run_module

    state_view = StateView(
        id="sv:test",
        projection_type=ProjectionType.NORTH_STAR,
        content="=== StateView Start ===\n=== StateView End ===",
        input_fingerprint="abc",
        metadata={},
    )
    game_spec = GameSpec(
        objective="Fix failing tests",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests pass",
    )
    previous_feedback = {
        "candidate_verification": {
            "exit_code": 1,
            "passed": False,
            "stdout": "FAILED tests/test_calc.py::test_add - AssertionError: assert 99 == 3\n",
            "stderr": "",
        }
    }
    prompt = render_coding_blue_prompt(
        state_view=state_view,
        game_spec=game_spec,
        attempt_number=2,
        previous_feedback=previous_feedback,
        plugin=PythonLanguagePlugin(),
    )
    assert "tests/test_calc.py::test_add" in prompt
    assert "Candidate verification failed" in prompt
    assert "Repair these test failures" in prompt


# ---------------------------------------------------------------------------
# Blackboard auditability: CREATE_GAME / PLAY_GAME / INTEGRATION events
# ---------------------------------------------------------------------------

def _make_play_game_config(workspace: Path) -> dict:
    return {
        "workspace": workspace,
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": workspace / "output" / "report.md",
        "max_iterations": 1,
        "spec_path": None,
    }


def _make_document_game_spec(**kwargs) -> "GameSpec":
    return GameSpec(
        objective="Add introduction section",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Introduction section must be present.",
        **kwargs,
    )

