import argparse
import ast
import inspect
import json
import logging
from pathlib import Path
import subprocess

import pytest

from baps.models import AnthropicClient, FakeModelClient, OllamaClient, OpenAIClient, ToolCall
from baps.run import create_game, create_state, main, play_game
from baps.document_adapter import DocumentProjectAdapter
from baps.coding_adapter import CodingProjectAdapter
import baps.run as _real_run
import baps.state as state_module

# Captured before autouse fixtures patch them — used by backend dispatch tests.
_real_build_model_client = _real_run._build_model_client
_real_build_planner_model_client = _real_run._build_planner_model_client
_real_build_role_client = _real_run._build_role_client
_real_build_fallback_chain_for_role = _real_run._build_fallback_chain_for_role


@pytest.fixture(autouse=True)
def _patch_create_game_model_client(monkeypatch):
    create_game_response = (
        '{"objective":"Advance goal","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}'
    )
    blue_tool_response = ToolCall(
        name="append_section",
        arguments={"artifact_id": "main-document", "title": "Introduction", "body": "Advance goal"},
    )
    red_response = '{"disposition":"accept","rationale":"deterministic test path"}'

    def _fake_create_game_builder():
        return FakeModelClient([create_game_response])

    # Each factory call returns a fresh client that works for any role:
    # generate_with_tools → blue_tool_response; generate → accept_response (red/referee share the same text).
    def _fake_model_client_builder():
        return FakeModelClient(
            responses=[red_response],
            tool_responses=[blue_tool_response],
        )

    # Primary patch: _build_client_for_role is the new call site used by create_game, play_game,
    # and _solve_gap.  Route create_game/decompose/create_game_red to the planner fake and all
    # other roles (blue/red/referee) to the play-game fake.
    def _fake_build_client_for_role(role, config):
        if role in ("create_game", "decompose", "create_game_red"):
            return _fake_create_game_builder()
        return _fake_model_client_builder()

    monkeypatch.setattr("baps.run._build_client_for_role", _fake_build_client_for_role)
    monkeypatch.setattr("baps.game._build_client_for_role", _fake_build_client_for_role)
    monkeypatch.setattr("baps.orchestration._build_client_for_role", _fake_build_client_for_role)
    # Keep legacy patches so tests that call the old builders directly still work.
    monkeypatch.setattr("baps.run._build_planner_model_client", _fake_create_game_builder)
    monkeypatch.setattr("baps.run._build_model_client", _fake_model_client_builder)
    # _build_role_client must delegate to the live _build_model_client so per-test
    # overrides of _build_model_client (e.g. fallback tests) continue to work.
    monkeypatch.setattr("baps.run._build_role_client", lambda _role: _real_run._build_model_client())
    monkeypatch.setattr("baps.game._build_role_client", lambda _role: _fake_model_client_builder())
    # Fallback resolution returns no chain by default (no fallback configured in tests).
    monkeypatch.setattr("baps.run._build_fallback_chain_for_role", lambda role, config: [])
    monkeypatch.setattr("baps.run._build_fallback_client_for_role", lambda role, config: None)
    monkeypatch.setattr("baps.game._build_fallback_chain_for_role", lambda role, config: [])


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
    proposal = run_module._derive_state_update_from_delta(
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


def test_create_game_receives_input_and_state_and_outputs_game_spec() -> None:
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
    state = create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Advance report objective","target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}'
            ]
        ),
    )

    assert game_spec.target_artifact_id == "main-document"
    assert game_spec.allowed_delta_type == "DeltaDocumentState"
    assert "DeltaDocumentState" in game_spec.success_condition


def test_create_game_target_artifact_exists_in_state() -> None:
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
    state = create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Advance report objective","target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}'
            ]
        ),
    )
    assert any(artifact.id == game_spec.target_artifact_id for artifact in state.artifacts)


def test_create_game_invalid_json_fails_cleanly() -> None:
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
    state = create_state(config)
    # Provide one response per attempt (initial + 2 retries) so FakeModelClient doesn't run dry.
    with pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient(["not-json", "not-json", "not-json"]))


def test_create_game_invalid_json_with_debug_prints_raw_model_output(
    monkeypatch, caplog
) -> None:
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
    state = create_state(config)

    with caplog.at_level(logging.DEBUG), pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient(["not-json-output", "not-json-output", "not-json-output"]))
    assert "create_game.prompt:" in caplog.text
    assert "create_game.raw_model_output:" in caplog.text
    assert "not-json-output" in caplog.text
    assert "retrying with correction prompt" in caplog.text


def test_create_game_invalid_json_without_debug_does_not_print_raw_model_output(caplog) -> None:
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
    state = create_state(config)

    with caplog.at_level(logging.INFO), pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient(["not-json-output", "not-json-output", "not-json-output"]))
    assert "create_game.prompt:" not in caplog.text
    assert "create_game.raw_model_output:" not in caplog.text


def test_create_game_json_retry_with_correction_prompt_succeeds() -> None:
    valid_response = (
        '{"objective":"Advance goal","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"section exists"}'
    )
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
    state = create_state(config)

    # First response is invalid JSON; the retry with the correction prompt returns valid JSON.
    game_spec = create_game(config, state, model_client=FakeModelClient(["not-json", valid_response]))

    assert game_spec.target_artifact_id == "main-document"


def test_create_game_explicit_model_client_retries_on_invalid_json() -> None:
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
    state = create_state(config)

    # Explicit model_client — correction-prompt retries still apply (same model, not a fallback).
    with pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient(["not-json", "not-json", "not-json"]))


def test_create_game_structural_validation_failure_debug_prints_raw_output(
    monkeypatch, caplog
) -> None:
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
    state = create_state(config)
    payload = (
        '{"objective":" ","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"Add introduction and conclusion"}'
    )
    with caplog.at_level(logging.DEBUG), pytest.raises(ValueError, match="create_game model output failed GameSpec validation"):
        create_game(config, state, model_client=FakeModelClient([payload]))
    assert "create_game.prompt:" in caplog.text
    assert "create_game.raw_model_output:" in caplog.text
    assert "create_game.validation_input:" not in caplog.text
    assert "create_game.validation_failure:" not in caplog.text
    assert payload in caplog.text


def test_create_game_validation_input_debug_enabled(caplog) -> None:
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
    state = create_state(config)

    with caplog.at_level(logging.DEBUG):
        create_game(
            config,
            state,
            model_client=FakeModelClient(
                [
                    '{"objective":"Advance report objective","target_artifact_id":"main-document",'
                    '"allowed_delta_type":"DeltaDocumentState",'
                    '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}'
                ]
            ),
        )
    assert "create_game.validation_input:" in caplog.text
    assert "objective: Advance report objective" in caplog.text
    assert "success_condition: PlayGame must return a valid DeltaDocumentState targeting main-document." in caplog.text
    assert "target_artifact_id: main-document" in caplog.text
    assert "allowed_delta_type: DeltaDocumentState" in caplog.text


def test_create_game_semantic_refinement_objective_is_accepted(caplog) -> None:
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
    state = create_state(config)

    with caplog.at_level(logging.DEBUG):
        game_spec = create_game(
            config,
            state,
            model_client=FakeModelClient(
                [
                    '{"objective":"Add a Conclusion section to artifact main-document, summarizing bounded adversarial evaluation outcomes and reiterating relevance to software project improvement.",'
                    '"target_artifact_id":"main-document",'
                    '"allowed_delta_type":"DeltaDocumentState",'
                    '"success_condition":"Artifact contains a Conclusion section summarizing bounded adversarial evaluation outcomes and reiterating relevance to software project improvement."}'
                ]
            ),
        )
    assert game_spec.target_artifact_id == "main-document"
    assert "create_game.validation_input:" in caplog.text


def test_create_game_objective_with_multiple_tasks_is_accepted_by_structural_validation() -> None:
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
    state = create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Update report and create appendix",'
                '"target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"Report is updated and appendix is created."}'
            ]
        ),
    )
    assert game_spec.objective == "Update report and create appendix"


def test_create_game_validation_debug_disabled_prints_nothing(caplog) -> None:
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
    state = create_state(config)

    with caplog.at_level(logging.INFO):
        create_game(
            config,
            state,
            model_client=FakeModelClient(
                [
                    '{"objective":"Advance report objective","target_artifact_id":"main-document",'
                    '"allowed_delta_type":"DeltaDocumentState",'
                    '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}'
                ]
            ),
        )
    assert "create_game.validation_input:" not in caplog.text
    assert "create_game.validation_failure:" not in caplog.text


def test_create_game_raw_json_still_accepted() -> None:
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
    state = create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Advance report objective","target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}'
            ]
        ),
    )
    assert game_spec.target_artifact_id == "main-document"


def test_create_game_exact_json_fence_accepted() -> None:
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
    state = create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                "```json\n"
                '{"objective":"Advance report objective","target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}\n'
                "```"
            ]
        ),
    )
    assert game_spec.target_artifact_id == "main-document"


def test_create_game_exact_plain_fence_accepted() -> None:
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
    state = create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                "```\n"
                '{"objective":"Advance report objective","target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}\n'
                "```"
            ]
        ),
    )
    assert game_spec.target_artifact_id == "main-document"


def test_create_game_prose_before_fence_extracted_and_parsed() -> None:
    # Pipeline extracts JSON from prose — prose wrapper is now handled correctly.
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
    state = create_state(config)
    response = (
        "Here is the result:\n```json\n"
        '{"objective":"Advance report objective","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}\n'
        "```"
    )
    game_spec = create_game(config, state, model_client=FakeModelClient([response]))
    assert game_spec.objective == "Advance report objective"


def test_create_game_prose_after_fence_extracted_and_parsed() -> None:
    # Pipeline extracts JSON via brace search when fence anchoring fails — handled correctly.
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
    state = create_state(config)
    response = (
        "```json\n"
        '{"objective":"Advance report objective","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}\n'
        "```\nDone."
    )
    game_spec = create_game(config, state, model_client=FakeModelClient([response]))
    assert game_spec.objective == "Advance report objective"


def test_create_game_multiple_fenced_blocks_rejected() -> None:
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
    state = create_state(config)
    bad = (
        "```json\n"
        '{"objective":"Advance report objective","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}\n'
        "```\n```json\n{}\n```"
    )
    with pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient([bad, bad, bad]))


def test_create_game_invalid_json_inside_fence_rejected() -> None:
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
    state = create_state(config)
    bad = "```json\n{not valid json}\n```"
    with pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient([bad, bad, bad]))


def test_create_game_missing_gamespec_fields_fails_cleanly() -> None:
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
    state = create_state(config)
    with pytest.raises(ValueError, match="must contain exactly keys"):
        create_game(
            config,
            state,
            model_client=FakeModelClient(['{"objective":"only-objective"}']),
        )


def test_create_game_target_artifact_not_in_state_fails_cleanly() -> None:
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
    state = create_state(config)
    with pytest.raises(ValueError, match="target artifact must match configured artifact_id"):
        create_game(
            config,
            state,
            model_client=FakeModelClient(
                [
                    '{"objective":"Advance report objective","target_artifact_id":"missing-document",'
                    '"allowed_delta_type":"DeltaDocumentState",'
                    '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting missing-document."}'
                ]
            ),
        )


def test_create_game_uses_adapter_build_create_game_state_view(monkeypatch) -> None:

    class _CapturingAdapter(DocumentProjectAdapter):
        def __init__(self):
            super().__init__()
            self.called = False

        def build_create_game_state_view(self, state, config):
            self.called = True
            return super().build_create_game_state_view(state, config)

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
    state = create_state(config)
    adapter = _CapturingAdapter()
    _ = create_game(
        config,
        state,
        adapter=adapter,
        model_client=FakeModelClient(
            [
                '{"objective":"Advance report objective","target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}'
            ]
        ),
    )
    assert adapter.called is True


def test_create_game_core_source_has_no_document_specific_refs() -> None:
    import baps.run as run_module

    src = inspect.getsource(run_module.create_game)
    assert "DocumentArtifact" not in src
    assert "_document_artifact_from_state" not in src
    assert ".sections" not in src


def test_create_game_prompt_forbids_markdown_fences_and_lists_required_shape() -> None:
    import baps.run as run_module

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
    state = create_state(config)
    adapter = DocumentProjectAdapter()
    prompt = run_module._render_create_game_prompt(
        config,
        state,
        adapter.build_create_game_state_view(state, config),
        adapter=adapter,
    )

    assert "Return only a JSON object" in prompt
    assert "Do not wrap output in markdown" in prompt
    assert "Do not use triple-backtick fences" in prompt
    assert '"objective"' in prompt
    assert '"target_artifact_id"' in prompt
    assert '"allowed_delta_type"' in prompt
    assert '"success_condition"' in prompt
    assert "Do not artificially split a coherent gap into multiple games" in prompt
    assert "All files or sections that must change together to close a gap belong in one game" in prompt
    assert "decompose" in prompt


def test_create_game_broad_goal_accepts_decomposed_atomic_gamespec() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "add introduction and conclusion",
        "northstar_markdown": "# Goal\n\nadd introduction and conclusion",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"add introduction section",'
                '"target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"Introduction section exists in main-document."}'
            ]
        ),
    )
    assert game_spec.objective == "add introduction section"
    assert game_spec.success_condition == "Introduction section exists in main-document."


def test_create_game_bundled_objective_and_success_condition_are_structurally_valid() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "add introduction and conclusion",
        "northstar_markdown": "# Goal\n\nadd introduction and conclusion",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"add introduction and conclusion",'
                '"target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"Introduction and conclusion sections both exist."}'
            ]
        ),
    )
    assert game_spec.objective == "add introduction and conclusion"


def test_create_game_multi_feature_wording_is_structurally_valid() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "implement parser and tests",
        "northstar_markdown": "# Goal\n\nimplement parser and tests",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"implement parser and tests",'
                '"target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"Parser and tests are implemented."}'
            ]
        ),
    )
    assert game_spec.objective == "implement parser and tests"


def test_create_game_red_accepts_game_spec_immediately() -> None:
    config = _make_doc_config()
    state = create_state(config)
    game_spec_json = (
        '{"objective":"Write introduction","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState","success_condition":"Introduction present."}'
    )
    red_accept_json = '{"disposition":"accept","rationale":"Good scope.","success_condition_met":null,"findings":[]}'
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient([game_spec_json]),
        create_game_red_client=FakeModelClient([red_accept_json]),
    )
    assert game_spec.objective == "Write introduction"


def test_create_game_red_reject_triggers_retry_with_feedback() -> None:
    config = _make_doc_config()
    state = create_state(config)
    first_spec = (
        '{"objective":"Write everything","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState","success_condition":"All done."}'
    )
    second_spec = (
        '{"objective":"Write introduction section","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState","success_condition":"Introduction present."}'
    )
    red_reject = (
        '{"disposition":"reject","rationale":"Too broad.","success_condition_met":null,'
        '"findings":["Objective spans multiple concerns"]}'
    )
    # CreateGame is called twice; Red is called once (only on attempt 1)
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient([first_spec, second_spec]),
        create_game_red_client=FakeModelClient([red_reject]),
        max_create_game_attempts=2,
    )
    assert game_spec.objective == "Write introduction section"


def test_create_game_red_feedback_appears_in_retry_prompt() -> None:
    config = _make_doc_config()
    state = create_state(config)
    spec_json = (
        '{"objective":"Write everything","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState","success_condition":"All done."}'
    )
    red_reject = (
        '{"disposition":"reject","rationale":"Too broad.","success_condition_met":null,'
        '"findings":["Scope too wide"]}'
    )
    prompts_seen: list[str] = []
    real_generate = FakeModelClient([spec_json, spec_json]).generate

    class CapturingClient:
        responses = iter([spec_json, spec_json])

        def generate(self, prompt: str, format=None) -> str:
            prompts_seen.append(prompt)
            return next(self.responses)

        def generate_with_tools(self, prompt, tools):
            return None

    create_game(
        config,
        state,
        model_client=CapturingClient(),
        create_game_red_client=FakeModelClient([red_reject]),
        max_create_game_attempts=2,
    )
    assert len(prompts_seen) == 2
    assert "Too broad" in prompts_seen[1]
    assert "Scope too wide" in prompts_seen[1]


def test_create_game_red_client_none_skips_challenge() -> None:
    config = _make_doc_config()
    state = create_state(config)
    spec_json = (
        '{"objective":"Write introduction","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState","success_condition":"Introduction present."}'
    )
    # No create_game_red_client — should return immediately after one CreateGame call
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient([spec_json]),
        create_game_red_client=None,
    )
    assert game_spec.objective == "Write introduction"


def test_create_game_red_unparseable_output_falls_back_to_accept() -> None:
    config = _make_doc_config()
    state = create_state(config)
    spec_json = (
        '{"objective":"Write introduction","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState","success_condition":"Introduction present."}'
    )
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient([spec_json]),
        create_game_red_client=FakeModelClient(["not valid json at all"]),
    )
    assert game_spec.objective == "Write introduction"


def test_create_game_red_revise_triggers_retry() -> None:
    config = _make_doc_config()
    state = create_state(config)
    first_spec = (
        '{"objective":"Write intro","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState","success_condition":"Vague."}'
    )
    second_spec = (
        '{"objective":"Write introduction section","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"Introduction section present with title and 2+ paragraphs."}'
    )
    red_revise = (
        '{"disposition":"revise","rationale":"Success condition too vague.","success_condition_met":null,'
        '"findings":["success_condition lacks specificity"]}'
    )
    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient([first_spec, second_spec]),
        create_game_red_client=FakeModelClient([red_revise]),
        max_create_game_attempts=2,
    )
    assert "2+ paragraphs" in game_spec.success_condition


def test_play_game_returns_delta_document_state() -> None:
    game_spec = {
        "objective": "Write an introduction section",
        "target_artifact_id": "main-document",
        "allowed_delta_type": "DeltaDocumentState",
        "success_condition": "PlayGame must return a valid DeltaDocumentState targeting main-document.",
    }
    import baps.run as run_module

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
    delta = play_game(state, run_module.GameSpec.model_validate(game_spec))
    assert delta is not None
    assert delta.model_dump(mode="json")["operation"] == "append_section"
    assert delta.model_dump(mode="json")["artifact_id"] == "main-document"


def test_play_game_accepted_candidate_becomes_current_best_delta() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Write an introduction section",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    delta = play_game(state, spec)
    assert delta is not None
    dumped = delta.model_dump(mode="json")
    assert dumped["payload"]["section"]["title"] == "Introduction"
    assert dumped["payload"]["section"]["body"] == "Advance goal"


def test_play_game_valid_blue_tool_call_returns_delta() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    delta = play_game(
        state,
        spec,
        model_client=FakeModelClient(
            tool_responses=[
                ToolCall(
                    name="append_section",
                    arguments={
                        "artifact_id": "main-document",
                        "title": "Introduction",
                        "body": "Any objective",
                    },
                )
            ]
        ),
    )
    assert delta is not None
    assert delta.model_dump(mode="json")["artifact_id"] == "main-document"


def test_play_game_no_tool_call_rejected() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    delta = play_game(
        state,
        spec,
        model_client=FakeModelClient(tool_responses=[None], responses=["not-json"]),
        max_attempts=1,
    )
    assert delta is None


def test_play_game_tool_call_with_empty_body_rejected() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    delta = play_game(
        state,
        spec,
        model_client=FakeModelClient(
            tool_responses=[
                ToolCall(
                    name="append_section",
                    arguments={"artifact_id": "main-document", "title": "Intro", "body": ""},
                )
            ]
        ),
        max_attempts=1,
    )
    assert delta is None


def test_play_game_valid_red_json_parses() -> None:
    import baps.run as run_module

    red = run_module._parse_red_finding_json(
        '{"disposition":"accept","rationale":"looks good"}'
    )
    assert red.disposition == "accept"
    assert red.rationale == "looks good"


def test_play_game_fenced_red_json_accepted() -> None:
    import baps.run as run_module

    red = run_module._parse_red_finding_json(
        "```json\n"
        '{"disposition":"revise","rationale":"tighten section body"}\n'
        "```"
    )
    assert red.disposition == "revise"


def test_play_game_invalid_red_json_rejected() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    with pytest.raises(ValueError, match="red: model output must be valid JSON"):
        play_game(
            state,
            spec,
            model_client=FakeModelClient(
                tool_responses=[
                    ToolCall(
                        name="append_section",
                        arguments={
                            "artifact_id": "main-document",
                            "title": "Introduction",
                            "body": "Any objective",
                        },
                    )
                ]
            ),
            red_model_client=FakeModelClient(["not-json"]),
        )


def test_play_game_valid_referee_json_parses() -> None:
    import baps.run as run_module

    decision = run_module._parse_referee_decision_json(
        '{"disposition":"accept","rationale":"looks good"}'
    )
    assert decision.disposition == "accept"
    assert decision.rationale == "looks good"


def test_play_game_fenced_referee_json_accepted() -> None:
    import baps.run as run_module

    decision = run_module._parse_referee_decision_json(
        "```json\n"
        '{"disposition":"revise","rationale":"tighten acceptance criteria"}\n'
        "```"
    )
    assert decision.disposition == "revise"


def test_play_game_invalid_referee_json_rejected() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    with pytest.raises(ValueError, match="referee: model output must be valid JSON"):
        play_game(
            state,
            spec,
            model_client=FakeModelClient(
                tool_responses=[
                    ToolCall(
                        name="append_section",
                        arguments={
                            "artifact_id": "main-document",
                            "title": "Introduction",
                            "body": "Any objective",
                        },
                    )
                ]
            ),
            red_model_client=FakeModelClient(
                ['{"disposition":"accept","rationale":"deterministic test path"}']
            ),
            referee_model_client=FakeModelClient(["not-json"]),
        )


def test_red_finding_optional_fields_parse_when_present() -> None:
    import baps.run as run_module

    red = run_module._parse_red_finding_json(
        '{"disposition":"revise","rationale":"needs work",'
        '"success_condition_met":false,'
        '"findings":["section body is too short","title duplicates existing section"]}'
    )
    assert red.disposition == "revise"
    assert red.success_condition_met is False
    assert red.findings == ("section body is too short", "title duplicates existing section")


def test_red_finding_defaults_when_optional_fields_absent() -> None:
    import baps.run as run_module

    red = run_module._parse_red_finding_json(
        '{"disposition":"accept","rationale":"looks good"}'
    )
    assert red.success_condition_met is None
    assert red.findings == ()


def test_red_finding_unexpected_key_stripped() -> None:
    import baps.run as run_module

    red = run_module._parse_red_finding_json(
        '{"disposition":"accept","rationale":"ok","confidence":0.9}'
    )
    assert red.disposition == "accept"
    assert not hasattr(red, "confidence")


def test_red_finding_missing_required_key_rejected() -> None:
    import baps.run as run_module

    with pytest.raises(ValueError, match="missing required keys"):
        run_module._parse_red_finding_json('{"disposition":"accept"}')


def test_referee_decision_optional_fields_parse_when_present() -> None:
    import baps.run as run_module

    decision = run_module._parse_referee_decision_json(
        '{"disposition":"revise","rationale":"override Red",'
        '"red_override":true,'
        '"improvement_hints":["add concrete section body","cite NorthStar goal"]}'
    )
    assert decision.disposition == "revise"
    assert decision.red_override is True
    assert decision.improvement_hints == ("add concrete section body", "cite NorthStar goal")


def test_referee_decision_defaults_when_optional_fields_absent() -> None:
    import baps.run as run_module

    decision = run_module._parse_referee_decision_json(
        '{"disposition":"accept","rationale":"approved"}'
    )
    assert decision.red_override is None
    assert decision.improvement_hints == ()


def test_referee_decision_unexpected_key_stripped() -> None:
    import baps.run as run_module

    decision = run_module._parse_referee_decision_json(
        '{"disposition":"accept","rationale":"ok","confidence":0.9}'
    )
    assert decision.disposition == "accept"
    assert not hasattr(decision, "confidence")


def test_referee_decision_missing_required_key_rejected() -> None:
    import baps.run as run_module

    with pytest.raises(ValueError, match="missing required keys"):
        run_module._parse_referee_decision_json('{"rationale":"ok"}')


def test_improvement_hints_appear_in_previous_feedback_for_blue() -> None:
    """improvement_hints from Referee flow into Blue's previous_feedback via model_dump."""
    import baps.run as run_module

    captured_feedback: list[dict | None] = []
    original_debug = run_module._debug_print_blue_input

    def _capture(state_view, game_spec, attempt, previous_feedback):
        captured_feedback.append(previous_feedback)
        original_debug(state_view, game_spec, attempt, previous_feedback)

    import baps.game as game_module

    spec, state = _make_document_spec_and_state()

    from unittest.mock import patch
    with patch.object(game_module, "_debug_print_blue_input", _capture):
        play_game(
            state,
            spec,
            model_client=_make_blue_client("Attempt One", "Attempt Two"),
            red_model_client=FakeModelClient(
                [
                    '{"disposition":"accept","rationale":"ok"}',
                    '{"disposition":"accept","rationale":"ok"}',
                ]
            ),
            referee_model_client=FakeModelClient(
                [
                    '{"disposition":"revise","rationale":"needs work",'
                    '"red_override":false,'
                    '"improvement_hints":["make body longer","cite NorthStar"]}',
                    '{"disposition":"accept","rationale":"approved"}',
                ]
            ),
            max_attempts=2,
        )

    assert len(captured_feedback) >= 2
    feedback = captured_feedback[1]
    assert feedback is not None
    assert "referee_decision" in feedback
    hints = feedback["referee_decision"]["improvement_hints"]
    assert hints == ["make body longer", "cite NorthStar"]


def test_red_prompt_includes_success_condition_met_and_findings_fields() -> None:
    import baps.run as run_module
    import baps.game as game_module

    captured: dict[str, object] = {}
    original = run_module._render_red_prompt

    def _capture(*args, **kwargs):
        result = original(*args, **kwargs)
        captured["prompt"] = result
        return result

    from unittest.mock import patch
    spec, state = _make_document_spec_and_state()
    with patch.object(game_module, "_render_red_prompt", _capture):
        play_game(state, spec, model_client=_make_blue_client("Introduction"))
    prompt = str(captured["prompt"])
    assert "success_condition_met" in prompt
    assert "findings" in prompt


def test_referee_prompt_includes_red_override_and_improvement_hints_fields() -> None:
    import baps.run as run_module
    import baps.game as game_module

    captured: dict[str, object] = {}
    original = run_module._render_referee_prompt

    def _capture(*args, **kwargs):
        result = original(*args, **kwargs)
        captured["prompt"] = result
        return result

    from unittest.mock import patch
    spec, state = _make_document_spec_and_state()
    with patch.object(game_module, "_render_referee_prompt", _capture):
        play_game(state, spec, model_client=_make_blue_client("Introduction"))
    prompt = str(captured["prompt"])
    assert "red_override" in prompt
    assert "improvement_hints" in prompt


def test_play_game_referee_receives_gamespec_state_view_delta_and_red(monkeypatch) -> None:
    import baps.run as run_module

    captured: dict[str, object] = {}

    def _capture_referee_input(state_view, game_spec, delta_state, red_finding):
        captured["state_view"] = state_view
        captured["game_spec"] = game_spec
        captured["delta_state"] = delta_state
        captured["red_finding"] = red_finding

    monkeypatch.setattr("baps.game._debug_print_referee_input", _capture_referee_input)
    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    delta = play_game(state, spec)
    assert delta is not None
    assert captured["game_spec"] is spec
    assert captured["state_view"] is not None
    assert captured["delta_state"] is not None
    assert captured["red_finding"] is not None


def test_play_game_referee_revise_promotes_candidate_as_fallback() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    delta = play_game(
        state,
        spec,
        model_client=FakeModelClient(
            tool_responses=[
                ToolCall(
                    name="append_section",
                    arguments={
                        "artifact_id": "main-document",
                        "title": "Introduction",
                        "body": "Any objective",
                    },
                )
            ]
        ),
        red_model_client=FakeModelClient(
            ['{"disposition":"accept","rationale":"deterministic test path"}']
        ),
        referee_model_client=FakeModelClient(
            ['{"disposition":"revise","rationale":"needs changes"}']
        ),
        max_attempts=1,
    )
    assert delta is not None
    assert delta.artifact_id == "main-document"


def test_play_game_referee_accept_sets_current_best_delta() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    delta = play_game(
        state,
        spec,
        model_client=FakeModelClient(
            tool_responses=[
                ToolCall(
                    name="append_section",
                    arguments={
                        "artifact_id": "main-document",
                        "title": "Introduction",
                        "body": "Any objective",
                    },
                )
            ]
        ),
        red_model_client=FakeModelClient(
            ['{"disposition":"accept","rationale":"deterministic test path"}']
        ),
        referee_model_client=FakeModelClient(
            ['{"disposition":"accept","rationale":"approved"}']
        ),
    )
    assert delta is not None


def test_play_game_red_receives_gamespec_state_view_and_delta_state(monkeypatch) -> None:
    import baps.run as run_module

    captured: dict[str, object] = {}

    def _capture_red_input(state_view, game_spec, delta_state):
        captured["state_view"] = state_view
        captured["game_spec"] = game_spec
        captured["delta_state"] = delta_state

    monkeypatch.setattr("baps.game._debug_print_red_input", _capture_red_input)
    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    delta = play_game(state, spec)
    assert delta is not None
    assert captured["game_spec"] is spec
    assert captured["state_view"] is not None
    assert captured["delta_state"] is not None


def _make_document_spec_and_state(success_condition: str = "A section exists."):
    import baps.run as run_module
    spec = run_module.GameSpec(
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


def test_red_prompt_includes_success_condition(monkeypatch) -> None:
    import baps.run as run_module

    captured: dict[str, object] = {}
    original = run_module._render_red_prompt

    def _capture(*args, **kwargs):
        result = original(*args, **kwargs)
        captured["prompt"] = result
        return result

    monkeypatch.setattr("baps.game._render_red_prompt", _capture)
    success_condition = "Unique success_condition string for red prompt contract test."
    spec, state = _make_document_spec_and_state(success_condition)
    play_game(state, spec, model_client=_make_blue_client("Introduction"))
    assert "prompt" in captured
    assert success_condition in str(captured["prompt"])


def test_referee_prompt_includes_success_condition_and_red_rationale(monkeypatch) -> None:
    import baps.run as run_module

    captured: dict[str, object] = {}
    original = run_module._render_referee_prompt

    def _capture(*args, **kwargs):
        result = original(*args, **kwargs)
        captured["prompt"] = result
        return result

    monkeypatch.setattr("baps.game._render_referee_prompt", _capture)
    success_condition = "Unique success_condition string for referee prompt contract test."
    spec, state = _make_document_spec_and_state(success_condition)
    red_rationale = "Unique red rationale for referee prompt test."
    play_game(
        state,
        spec,
        model_client=_make_blue_client("Introduction"),
        red_model_client=FakeModelClient(
            [f'{{"disposition":"accept","rationale":"{red_rationale}"}}']
        ),
    )
    prompt = str(captured["prompt"])
    assert success_condition in prompt
    assert red_rationale in prompt


def test_play_game_referee_revise_retries_and_second_attempt_accepted() -> None:

    spec, state = _make_document_spec_and_state()
    delta = play_game(
        state,
        spec,
        model_client=_make_blue_client("Attempt One", "Attempt Two"),
        red_model_client=FakeModelClient(
            [
                '{"disposition":"accept","rationale":"ok"}',
                '{"disposition":"accept","rationale":"ok"}',
            ]
        ),
        referee_model_client=FakeModelClient(
            [
                '{"disposition":"revise","rationale":"needs work"}',
                '{"disposition":"accept","rationale":"approved"}',
            ]
        ),
        max_attempts=2,
    )
    assert delta is not None
    assert delta.artifact_id == "main-document"
    assert isinstance(delta, state_module.DeltaDocumentState)
    assert delta.payload.section.title == "Attempt Two"


def test_play_game_referee_reject_retries_and_second_attempt_accepted() -> None:

    spec, state = _make_document_spec_and_state()
    delta = play_game(
        state,
        spec,
        model_client=_make_blue_client("Bad Attempt", "Good Attempt"),
        red_model_client=FakeModelClient(
            [
                '{"disposition":"accept","rationale":"ok"}',
                '{"disposition":"accept","rationale":"ok"}',
            ]
        ),
        referee_model_client=FakeModelClient(
            [
                '{"disposition":"reject","rationale":"wrong direction"}',
                '{"disposition":"accept","rationale":"approved"}',
            ]
        ),
        max_attempts=2,
    )
    assert delta is not None
    assert isinstance(delta, state_module.DeltaDocumentState)
    assert delta.payload.section.title == "Good Attempt"


def test_play_game_previous_feedback_on_retry_contains_red_and_referee(monkeypatch) -> None:
    import baps.run as run_module


    captured_feedback: list[dict | None] = []
    original_debug = run_module._debug_print_blue_input

    def _capture(state_view, game_spec, attempt, previous_feedback):
        captured_feedback.append(previous_feedback)
        original_debug(state_view, game_spec, attempt, previous_feedback)

    monkeypatch.setattr("baps.game._debug_print_blue_input", _capture)
    spec, state = _make_document_spec_and_state()
    play_game(
        state,
        spec,
        model_client=_make_blue_client("Attempt One", "Attempt Two"),
        red_model_client=FakeModelClient(
            [
                '{"disposition":"accept","rationale":"red rationale for feedback test"}',
                '{"disposition":"accept","rationale":"ok"}',
            ]
        ),
        referee_model_client=FakeModelClient(
            [
                '{"disposition":"revise","rationale":"referee rationale for feedback test"}',
                '{"disposition":"accept","rationale":"approved"}',
            ]
        ),
        max_attempts=2,
    )
    assert len(captured_feedback) >= 2
    assert captured_feedback[0] is None
    feedback = captured_feedback[1]
    assert feedback is not None
    assert "red_finding" in feedback
    assert "referee_decision" in feedback
    assert feedback["red_finding"]["rationale"] == "red rationale for feedback test"
    assert feedback["referee_decision"]["rationale"] == "referee rationale for feedback test"
    assert feedback["referee_decision"]["disposition"] == "revise"


def test_play_game_red_reject_with_referee_accept_returns_delta() -> None:
    """Red is advisory: a Red reject must not prevent acceptance when Referee accepts."""
    spec, state = _make_document_spec_and_state()
    delta = play_game(
        state,
        spec,
        model_client=_make_blue_client("Introduction"),
        red_model_client=FakeModelClient(
            ['{"disposition":"reject","rationale":"red says no"}']
        ),
        referee_model_client=FakeModelClient(
            ['{"disposition":"accept","rationale":"referee overrides"}']
        ),
    )
    assert delta is not None
    assert delta.artifact_id == "main-document"


def test_play_game_all_referee_rejects_returns_none() -> None:
    spec, state = _make_document_spec_and_state()
    delta = play_game(
        state,
        spec,
        model_client=_make_blue_client("Attempt One", "Attempt Two"),
        red_model_client=FakeModelClient(
            [
                '{"disposition":"accept","rationale":"ok"}',
                '{"disposition":"accept","rationale":"ok"}',
            ]
        ),
        referee_model_client=FakeModelClient(
            [
                '{"disposition":"reject","rationale":"wrong"}',
                '{"disposition":"reject","rationale":"still wrong"}',
            ]
        ),
        max_attempts=2,
    )
    assert delta is None


def test_blue_prompt_includes_state_view_and_gamespec() -> None:
    import baps.project_adapter as project_adapter_module
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    prompt = project_adapter_module.render_blue_prompt_core(
        state_view=state_view,
        game_spec=spec,
        attempt_number=1,
        previous_feedback=None,
    )
    assert "- state_view:" in prompt
    assert "=== StateView Start ===" in prompt
    assert "--- State Artifacts ---" in prompt
    assert "attempt_number: 1" in prompt
    assert "previous_feedback_json: null" in prompt
    assert "objective:" in prompt
    assert "target_artifact_id:" in prompt
    assert "allowed_delta_type:" in prompt
    assert "success_condition:" in prompt
    assert "Produce exactly one delta JSON object allowed by GameSpec.allowed_delta_type." in prompt
    assert "Use StateView as the current artifact context." in prompt
    assert "Do not duplicate existing artifact content." in prompt
    assert "Do not rewrite unrelated existing state." in prompt
    assert "Do not emit placeholder or filler content." in prompt
    assert (
        "If previous_feedback_json contains validation errors, repair those exact errors in this attempt."
        in prompt
    )
    assert "Do not repeat outputs that fail previously reported validation constraints." in prompt
    assert (
        "When attempt_number > 1, treat previous_feedback_json as mandatory correction requirements."
        in prompt
    )
    assert "Document delta rules:" not in prompt
    assert "append_section" not in prompt
    assert "Introduction" not in prompt
    assert "Conclusion" not in prompt
    assert "blue_view_json:" not in prompt
    assert "state_json:" not in prompt


def test_red_prompt_intro_only_guides_revise_for_intro_and_conclusion_success_condition() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Write a short report.",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Document must include both an Introduction section and a Conclusion section.",
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
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=state_module.AppendSectionDelta(
            section=state_module.Section(title="Introduction", body="Intro only")
        ),
    )
    prompt = run_module._render_red_prompt(state_view, spec, delta)
    assert "success_condition:" in prompt
    assert "Document must include both an Introduction section and a Conclusion section." in prompt
    assert "Use revise only when the candidate is promising but needs improvement" in prompt
    assert "Do NOT reject or revise merely because state differs from the original state." in prompt


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
    state = run_module.State(
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
    with pytest.raises(run_module.NoNewGameError):
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
    with pytest.raises(run_module.NoNewGameError, match="all required sections already present"):
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
    with pytest.raises(run_module.NorthStarUpdateNeededError):
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
    assert isinstance(result, run_module.DecomposeSpec)


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


def test_create_game_prompt_includes_northstar_context() -> None:
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
    adapter = DocumentProjectAdapter()
    state_view = adapter.build_create_game_state_view(state, config)
    prompt = run_module._render_create_game_prompt(
        config,
        state,
        adapter.build_create_game_state_view(state, config),
        adapter=adapter,
    )
    assert "- state_view:" in prompt
    assert prompt.count("=== StateView Start ===") == 1
    assert prompt.count("=== StateView End ===") == 1
    assert state_view.content in prompt
    assert "must include these sections" in prompt
    assert "metadata" not in prompt
    assert "input_fingerprint" not in prompt
    assert "projection_type" not in prompt
    assert "northstar_content" not in prompt
    assert "state_view_json:" not in prompt
    assert "GAP ANALYSIS" in prompt
    assert "PRIORITIZE" in prompt
    assert "DECIDE" in prompt
    assert "SELF-CONTAIN" in prompt
    assert "decompose" in prompt
    assert "name the gap being closed" in prompt
    assert "verifiable from the artifact alone" in prompt
    assert "Do not artificially split a coherent gap into multiple games" in prompt
    assert '{\"no_new_game\": true, \"reason\": \"...\"}' in prompt
    assert "state_json:" not in prompt
    assert "mandatory_sections_json" not in prompt
    assert "next_missing_required_section" not in prompt


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


def test_blue_prompt_and_source_do_not_hardcode_project_policy_literals() -> None:
    import baps.project_adapter as project_adapter_module
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Add Overview section",
        target_artifact_id="doc-a",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Overview section exists.",
    )
    state = run_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="doc-a", sections=()),),
    )
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    prompt = project_adapter_module.render_blue_prompt_core(
        state_view=state_view, game_spec=spec, attempt_number=1, previous_feedback=None
    )
    assert '"artifact_id": "<game_spec.target_artifact_id>"' not in prompt
    assert '"title": "<section title>"' not in prompt
    assert "Do not duplicate existing artifact content." in prompt
    assert "Do not emit placeholder or filler content." in prompt
    src = inspect.getsource(project_adapter_module.render_blue_prompt_core)
    assert '"artifact_id": "main-document"' not in src
    assert '"title": "Introduction"' not in src


def test_document_blue_prompt_contains_document_specific_shape_rules() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Add Overview section",
        target_artifact_id="doc-a",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Overview section exists.",
    )
    state = run_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="doc-a", sections=()),),
    )
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    prompt = DocumentProjectAdapter().render_blue_prompt(state_view, spec, 1, None)
    assert "Document delta rules:" in prompt
    assert "section.title and section.body must be non-empty strings." in prompt
    assert '"artifact_id": "<game_spec.target_artifact_id>"' in prompt
    assert '"operation": "append_section"' in prompt
    assert 'Invalid example, do not output: "body": ""' in prompt


def test_referee_prompt_intro_and_conclusion_guides_accept_policy() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Write a short report.",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Document must include both an Introduction section and a Conclusion section.",
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
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=state_module.AppendSectionDelta(
            section=state_module.Section(
                title="Introduction and Conclusion",
                body="Introduction... Conclusion...",
            )
        ),
    )
    red = run_module.RedFinding(disposition="accept", rationale="satisfies success condition")
    prompt = run_module._render_referee_prompt(state_view, spec, delta, red)
    assert (
        "accept: objective/success_condition are satisfied enough for this game AND Red has no unresolved material findings."
        in prompt
    )
    assert (
        "revise: objective/success_condition are only partially satisfied OR Red has unresolved improvements that should be addressed."
        in prompt
    )
    assert "reject: candidate is invalid, harmful, incoherent, or wrong direction." in prompt
    assert "Do NOT choose revise merely because state changed." in prompt


def test_referee_prompt_declares_game_local_authority_and_not_final_integration() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Any success condition.",
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
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=state_module.AppendSectionDelta(
            section=state_module.Section(title="Introduction", body="Body")
        ),
    )
    red = run_module.RedFinding(disposition="accept", rationale="ok")
    prompt = run_module._render_referee_prompt(state_view, spec, delta, red)
    assert "You are the game-local authority for this PlayGame decision." in prompt
    assert "You do NOT decide final State integration; integration is decided later by Integrator." in prompt


def test_referee_prompt_uses_red_material_findings_in_decision_policy() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Any success condition.",
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
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=state_module.AppendSectionDelta(
            section=state_module.Section(title="Introduction", body="Body")
        ),
    )
    red = run_module.RedFinding(disposition="revise", rationale="missing conclusion")
    prompt = run_module._render_referee_prompt(state_view, spec, delta, red)
    assert "Red has no unresolved material findings" in prompt
    assert "Red has unresolved improvements that should be addressed." in prompt


def test_red_and_referee_prompts_do_not_treat_state_mutation_alone_as_failure() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Any success condition.",
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
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=state_module.AppendSectionDelta(
            section=state_module.Section(title="Introduction", body="Body")
        ),
    )
    red_prompt = run_module._render_red_prompt(state_view, spec, delta)
    referee_prompt = run_module._render_referee_prompt(
        state_view,
        spec,
        delta,
        run_module.RedFinding(disposition="accept", rationale="ok"),
    )
    assert "Do NOT reject or revise merely because state differs from the original state." in red_prompt
    assert "Do NOT choose revise merely because state changed." in referee_prompt
    assert "candidate DeltaDocumentState" not in red_prompt
    assert "pytest discovered tests" not in red_prompt
    assert "pytest discovered tests" not in referee_prompt
    assert "Evaluate the candidate DeltaState" in red_prompt


def test_coding_red_prompt_includes_verification_evidence_when_provided() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Write tests/test_fibonacci.py",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="Tests pass",
    )
    state = run_module.State(
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
    state_view = CodingProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaCodingState(
        artifact_id="main-codebase",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(
                path="tests/test_fibonacci.py",
                content="def test_smoke():\n    assert True\n",
            )
        ),
    )
    verification = run_module.VerificationResult(
        command="uv run pytest",
        cwd="/tmp/project",
        exit_code=0,
        stdout="1 passed",
        stderr="",
        passed=True,
    )
    adapter = CodingProjectAdapter()
    supplement = adapter.render_red_prompt_supplement(state_view, spec, delta, verification)
    prompt = run_module._render_red_prompt(
        state_view, spec, delta, verification_result=verification, prompt_supplement=supplement
    )
    assert "verification_result_json:" in prompt
    assert "\"exit_code\": 0" in prompt
    assert "\"passed\": true" in prompt
    assert "If verification passed, treat that as strong evidence toward accept." in prompt
    assert "If pytest discovered tests, do not claim test files are empty." in prompt


def test_coding_referee_prompt_includes_failing_verification_evidence() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Write tests/test_fibonacci.py",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="Tests pass",
    )
    state = run_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(id="main-codebase", files=()),),
    )
    state_view = CodingProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaCodingState(
        artifact_id="main-codebase",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(
                path="tests/test_fibonacci.py",
                content="def test_smoke():\n    assert False\n",
            )
        ),
    )
    red = run_module.RedFinding(disposition="revise", rationale="needs fix")
    verification = run_module.VerificationResult(
        command="uv run pytest",
        cwd="/tmp/project",
        exit_code=1,
        stdout="1 failed",
        stderr="traceback",
        passed=False,
    )
    prompt = run_module._render_referee_prompt(
        state_view, spec, delta, red, verification_result=verification
    )
    assert "verification_result_json:" in prompt
    assert "\"exit_code\": 1" in prompt
    assert "\"stdout\": \"1 failed\"" in prompt
    assert "\"stderr\": \"traceback\"" in prompt
    assert "If verification failed, reason from exit_code/stdout/stderr evidence." in prompt


def test_document_prompts_do_not_include_verification_evidence_by_default() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Any success condition",
    )
    state = run_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="main-document", sections=()),),
    )
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=state_module.AppendSectionDelta(
            section=state_module.Section(title="Intro", body="Body")
        ),
    )
    red = run_module.RedFinding(disposition="accept", rationale="ok")
    red_prompt = run_module._render_red_prompt(state_view, spec, delta)
    referee_prompt = run_module._render_referee_prompt(state_view, spec, delta, red)
    assert "verification_result_json:" not in red_prompt
    assert "verification_result_json:" not in referee_prompt


def test_document_red_referee_prompts_do_not_include_coding_guidance() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Any success condition",
    )
    state = run_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="main-document", sections=()),),
    )
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=state_module.AppendSectionDelta(
            section=state_module.Section(title="Intro", body="Body")
        ),
    )
    red = run_module.RedFinding(disposition="accept", rationale="ok")
    red_prompt = run_module._render_red_prompt(state_view, spec, delta)
    referee_prompt = run_module._render_referee_prompt(state_view, spec, delta, red)
    for prompt in (red_prompt, referee_prompt):
        assert "target_artifact_id is the artifact id, not a file path." not in prompt
        assert "Pytest tests containing assert statements are not empty." not in prompt
        assert "Do not reject tests as empty if assertions are present." not in prompt


def test_coding_red_referee_prompts_include_coding_guidance() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Write tests",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="tests exist",
    )
    state = run_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(id="main-codebase", files=()),),
    )
    adapter = CodingProjectAdapter()
    state_view = adapter.build_state_view(state, spec)
    delta = state_module.DeltaCodingState(
        artifact_id="main-codebase",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(path="tests/test_fibonacci.py", content="assert True")
        ),
    )
    red = run_module.RedFinding(disposition="accept", rationale="ok")
    red_supplement = adapter.render_red_prompt_supplement(
        state_view, spec, delta, verification_result=None
    )
    referee_supplement = adapter.render_referee_prompt_supplement(
        state_view, spec, delta, verification_result=None
    )
    red_prompt = run_module._render_red_prompt(
        state_view, spec, delta, prompt_supplement=red_supplement
    )
    referee_prompt = run_module._render_referee_prompt(
        state_view, spec, delta, red, prompt_supplement=referee_supplement
    )
    for prompt in (red_prompt, referee_prompt):
        assert "target_artifact_id is the artifact id, not a file path." in prompt
        assert "Pytest tests containing assert statements are not empty." in prompt
        assert "Do not reject tests as empty if assertions are present." in prompt
        assert (
            "If success_condition only requires non-empty tests, basic asserted tests satisfy that condition."
            in prompt
        )


def test_red_referee_prompts_forbid_goalpost_drift_language() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Write tests/test_example.py with non-empty pytest tests.",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="Artifact contains tests/test_example.py with non-empty pytest tests.",
    )
    state = run_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(id="main-codebase", files=()),),
    )
    state_view = CodingProjectAdapter().build_state_view(state, spec)
    delta = state_module.DeltaCodingState(
        artifact_id="main-codebase",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(
                path="tests/test_example.py",
                content="def test_smoke():\n    assert True\n",
            )
        ),
    )
    red = run_module.RedFinding(disposition="accept", rationale="ok")
    red_prompt = run_module._render_red_prompt(state_view, spec, delta)
    referee_prompt = run_module._render_referee_prompt(state_view, spec, delta, red)
    for prompt in (red_prompt, referee_prompt):
        assert "Treat GameSpec.success_condition as authoritative acceptance contract." in prompt
        assert "Do not invent stronger requirements than objective/success_condition." in prompt
        assert (
            "Do not add stricter standards such as 'more comprehensive', 'better coverage', "
            "'stronger tests', or 'more complete' unless those words (or equivalent requirements) "
            "are explicit in GameSpec."
        ) in prompt


def test_run_core_prompt_source_has_no_coding_specific_red_referee_guidance() -> None:
    run_source = Path("src/baps/run.py").read_text(encoding="utf-8")
    assert "target_artifact_id is the artifact id, not a file path." not in run_source
    assert "Pytest tests containing assert statements are not empty." not in run_source
    assert "Do not reject tests as empty if assertions are present." not in run_source


def test_state_view_is_derived_from_state_and_gamespec_with_existing_sections() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
    )
    state = run_module.State(
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

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Any success condition.",
    )
    state = run_module.State(
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

    state = run_module.State(
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

    state = run_module.State(
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


def test_play_game_returns_none_if_referee_rejects() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Write an introduction section",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    delta = play_game(
        state,
        spec,
        referee_model_client=FakeModelClient(
            ['{"disposition":"reject","rationale":"deterministic test path"}']
        ),
        max_attempts=1,
    )
    assert delta is None


def test_play_game_accept_first_attempt_returns_immediately() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    blue_client = FakeModelClient(
        tool_responses=[
            ToolCall("append_section", {"artifact_id": "main-document", "title": "Introduction", "body": "first"}),
            ToolCall("append_section", {"artifact_id": "main-document", "title": "Introduction", "body": "second"}),
        ]
    )
    red_client = FakeModelClient(
        [
            '{"disposition":"accept","rationale":"ok"}',
            '{"disposition":"accept","rationale":"ok"}',
        ]
    )
    referee_client = FakeModelClient(
        [
            '{"disposition":"accept","rationale":"approved"}',
            '{"disposition":"accept","rationale":"approved"}',
        ]
    )
    delta = play_game(
        state,
        spec,
        model_client=blue_client,
        red_model_client=red_client,
        referee_model_client=referee_client,
        max_attempts=3,
    )
    assert delta is not None
    assert len(blue_client.tool_prompts) == 1
    assert len(red_client.prompts) == 1
    assert len(referee_client.prompts) == 1


def test_play_game_revise_then_accept_uses_second_attempt() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    blue_client = FakeModelClient(
        tool_responses=[
            ToolCall("append_section", {"artifact_id": "main-document", "title": "Introduction", "body": "first"}),
            ToolCall("append_section", {"artifact_id": "main-document", "title": "Introduction", "body": "second"}),
        ]
    )
    delta = play_game(
        state,
        spec,
        model_client=blue_client,
        red_model_client=FakeModelClient(
            [
                '{"disposition":"accept","rationale":"ok"}',
                '{"disposition":"accept","rationale":"ok"}',
            ]
        ),
        referee_model_client=FakeModelClient(
            [
                '{"disposition":"revise","rationale":"needs revision"}',
                '{"disposition":"accept","rationale":"approved"}',
            ]
        ),
        max_attempts=3,
    )
    assert delta is not None
    assert delta.model_dump(mode="json")["payload"]["section"]["body"] == "second"
    assert len(blue_client.tool_prompts) == 2


def test_play_game_reject_then_accept_uses_second_attempt() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    blue_client = FakeModelClient(
        tool_responses=[
            ToolCall("append_section", {"artifact_id": "main-document", "title": "Introduction", "body": "first"}),
            ToolCall("append_section", {"artifact_id": "main-document", "title": "Introduction", "body": "second"}),
        ]
    )
    delta = play_game(
        state,
        spec,
        model_client=blue_client,
        red_model_client=FakeModelClient(
            [
                '{"disposition":"accept","rationale":"ok"}',
                '{"disposition":"accept","rationale":"ok"}',
            ]
        ),
        referee_model_client=FakeModelClient(
            [
                '{"disposition":"reject","rationale":"no"}',
                '{"disposition":"accept","rationale":"approved"}',
            ]
        ),
        max_attempts=3,
    )
    assert delta is not None
    assert delta.model_dump(mode="json")["payload"]["section"]["body"] == "second"
    assert len(blue_client.tool_prompts) == 2


def test_play_game_attempts_exhausted_all_rejected_returns_none() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    delta = play_game(
        state,
        spec,
        model_client=FakeModelClient(
            tool_responses=[
                ToolCall("append_section", {"artifact_id": "main-document", "title": "Introduction", "body": "first"}),
                ToolCall("append_section", {"artifact_id": "main-document", "title": "Introduction", "body": "second"}),
            ]
        ),
        red_model_client=FakeModelClient(
            [
                '{"disposition":"accept","rationale":"ok"}',
                '{"disposition":"accept","rationale":"ok"}',
            ]
        ),
        referee_model_client=FakeModelClient(
            [
                '{"disposition":"reject","rationale":"no"}',
                '{"disposition":"reject","rationale":"still no"}',
            ]
        ),
        max_attempts=2,
    )
    assert delta is None


def test_play_game_attempts_exhausted_last_revised_returned_as_fallback() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    delta = play_game(
        state,
        spec,
        model_client=FakeModelClient(
            tool_responses=[
                ToolCall("append_section", {"artifact_id": "main-document", "title": "Introduction", "body": "first"}),
                ToolCall("append_section", {"artifact_id": "main-document", "title": "Introduction", "body": "second"}),
            ]
        ),
        red_model_client=FakeModelClient(
            [
                '{"disposition":"accept","rationale":"ok"}',
                '{"disposition":"accept","rationale":"ok"}',
            ]
        ),
        referee_model_client=FakeModelClient(
            [
                '{"disposition":"reject","rationale":"no"}',
                '{"disposition":"revise","rationale":"needs work"}',
            ]
        ),
        max_attempts=2,
    )
    assert delta is not None
    assert delta.payload.section.body == "second"


def test_play_game_previous_feedback_passed_to_later_blue_prompt() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    blue_client = FakeModelClient(
        tool_responses=[
            ToolCall("append_section", {"artifact_id": "main-document", "title": "Introduction", "body": "first"}),
            ToolCall("append_section", {"artifact_id": "main-document", "title": "Introduction", "body": "second"}),
        ]
    )
    _ = play_game(
        state,
        spec,
        model_client=blue_client,
        red_model_client=FakeModelClient(
            [
                '{"disposition":"accept","rationale":"ok"}',
                '{"disposition":"accept","rationale":"ok"}',
            ]
        ),
        referee_model_client=FakeModelClient(
            [
                '{"disposition":"revise","rationale":"needs revision"}',
                '{"disposition":"accept","rationale":"approved"}',
            ]
        ),
        max_attempts=2,
    )
    assert len(blue_client.tool_prompts) == 2
    second_prompt = blue_client.tool_prompts[1]
    assert "previous_feedback_json:" in second_prompt
    assert (
        "When attempt_number > 1, treat previous_feedback_json as mandatory correction requirements."
        in second_prompt
    )
    assert (
        "If previous_feedback_json contains validation errors, repair those exact errors in this attempt."
        in second_prompt
    )
    assert '"red_finding"' in second_prompt
    assert '"disposition": "accept"' in second_prompt
    assert '"rationale": "ok"' in second_prompt
    assert '"referee_decision"' in second_prompt
    assert '"disposition": "revise"' in second_prompt
    assert '"rationale": "needs revision"' in second_prompt


def test_play_game_invalid_blue_first_attempt_retries_second_attempt() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    blue_client = FakeModelClient(
        tool_responses=[
            ToolCall("append_section", {"artifact_id": "main-document", "title": "Introduction", "body": ""}),
            ToolCall("append_section", {"artifact_id": "main-document", "title": "Introduction", "body": "second"}),
        ]
    )
    delta = play_game(
        state,
        spec,
        model_client=blue_client,
        red_model_client=FakeModelClient(
            ['{"disposition":"accept","rationale":"ok"}']
        ),
        referee_model_client=FakeModelClient(
            ['{"disposition":"accept","rationale":"approved"}']
        ),
        max_attempts=2,
    )
    assert delta is not None
    assert delta.payload.section.body == "second"
    assert len(blue_client.tool_prompts) == 2
    second_prompt = blue_client.tool_prompts[1]
    assert "previous_feedback_json:" in second_prompt
    assert (
        "When attempt_number > 1, treat previous_feedback_json as mandatory correction requirements."
        in second_prompt
    )
    assert (
        "If previous_feedback_json contains validation errors, repair those exact errors in this attempt."
        in second_prompt
    )
    assert '"stage": "blue"' in second_prompt
    assert "payload.section.body" in second_prompt
    assert "must be a non-empty string" in second_prompt


def test_play_game_invalid_blue_all_attempts_returns_none() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    delta = play_game(
        state,
        spec,
        model_client=FakeModelClient(
            tool_responses=[
                ToolCall("append_section", {"artifact_id": "main-document", "title": "Introduction", "body": ""}),
                ToolCall("append_section", {"artifact_id": "main-document", "title": "Introduction", "body": ""}),
            ]
        ),
        max_attempts=2,
    )
    assert delta is None


def test_play_game_invalid_blue_debug_and_non_debug_output(caplog) -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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

    with caplog.at_level(logging.INFO):
        _ = play_game(
            state,
            spec,
            model_client=FakeModelClient(
                tool_responses=[ToolCall("append_section", {"artifact_id": "main-document", "title": "Introduction", "body": ""})]
            ),
            max_attempts=1,
        )
    assert "blue.failed_tool_call:" not in caplog.text
    caplog.clear()

    with caplog.at_level(logging.DEBUG):
        _ = play_game(
            state,
            spec,
            model_client=FakeModelClient(
                tool_responses=[ToolCall("append_section", {"artifact_id": "main-document", "title": "Introduction", "body": ""})]
            ),
            max_attempts=1,
        )
    assert "blue.failed_tool_call:" in caplog.text
    assert "play_game.attempt_rejected:" in caplog.text
    assert "reason: blue output failed DeltaState validation:" in caplog.text
    assert "payload.section.body" in caplog.text
    assert "must be a non-empty string" in caplog.text


def test_runtime_preserves_accepted_delta_after_later_reject_in_helper_flow() -> None:
    import baps.run as run_module

    first_delta = state_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=state_module.AppendSectionDelta(
            section=state_module.Section(title="Introduction", body="first")
        ),
    )
    second_delta = state_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=state_module.AppendSectionDelta(
            section=state_module.Section(title="Introduction", body="second")
        ),
    )
    runtime = run_module.PlayGameRuntime()
    runtime = run_module.apply_referee_decision_to_runtime(
        runtime=runtime,
        candidate_delta=first_delta,
        decision=run_module.RefereeDecision(disposition="accept", rationale="ok"),
    )
    runtime = run_module.apply_referee_decision_to_runtime(
        runtime=runtime,
        candidate_delta=second_delta,
        decision=run_module.RefereeDecision(disposition="reject", rationale="no"),
    )
    assert runtime.current_best_delta is not None
    assert runtime.current_best_delta.payload.section.body == "first"


def test_play_game_debug_logs_appear(caplog) -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Write an introduction section",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
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
    with caplog.at_level(logging.DEBUG):
        _ = play_game(state, spec)
    assert "blue.input:" in caplog.text
    assert "blue.output:" in caplog.text
    assert "red.input:" in caplog.text
    assert "red.output:" in caplog.text
    assert "referee.input:" in caplog.text
    assert "referee.output:" in caplog.text
    assert "play_game.input:" in caplog.text
    assert "play_game.attempt:" in caplog.text
    assert "play_game.output:" in caplog.text
    assert "attempt: 1" in caplog.text
    blue_input_msg = next(r.getMessage() for r in caplog.records if "blue.input:" in r.getMessage())
    assert "state_view:" in blue_input_msg
    assert "content: === StateView Start ===" in blue_input_msg
    assert "--- State Artifacts ---" in blue_input_msg
    assert "## Artifact: main-document" in blue_input_msg
    assert "kind: document" in blue_input_msg
    assert "No sections." in blue_input_msg
    assert '"target_artifact_id"' not in blue_input_msg
    assert "state:" not in blue_input_msg
    assert "game_spec:" in blue_input_msg
    assert "attempt_number: 1" in blue_input_msg
    assert "previous_feedback: None" in blue_input_msg
    red_input_msg = next(r.getMessage() for r in caplog.records if "red.input:" in r.getMessage())
    assert "game_spec:" in red_input_msg
    assert "state_view:" in red_input_msg
    assert "delta_state:" in red_input_msg
    assert "artifact_id: main-document" in red_input_msg
    assert "red_finding:" in caplog.text
    referee_input_msg = next(r.getMessage() for r in caplog.records if "referee.input:" in r.getMessage())
    assert "game_spec:" in referee_input_msg
    assert "state_view:" in referee_input_msg
    assert "delta_state:" in referee_input_msg
    assert "red_finding:" in referee_input_msg
    assert "referee_decision:" in caplog.text
    assert "current_best_delta:" in caplog.text


def test_main_calls_play_game_with_gamespec_from_create_game(monkeypatch, tmp_path: Path) -> None:
    import baps.run as run_module

    captured: dict[str, object] = {}
    expected = run_module.GameSpec(
        objective="O",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="S",
    )

    monkeypatch.setattr(
        "baps.orchestration.create_game",
        lambda config, state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs: expected,
    )

    def _capture_play_game(state, spec, adapter=None, verification_result=None, **_kwargs):
        captured["state"] = state
        captured["spec"] = spec
        return state_module.DeltaDocumentState(
            artifact_id=spec.target_artifact_id,
            operation="append_section",
            payload=state_module.AppendSectionDelta(
                section=state_module.Section(title="Introduction", body=spec.objective)
            ),
        )

    monkeypatch.setattr("baps.orchestration.play_game", _capture_play_game)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(tmp_path / "ws-main-play"),
            "--project-type",
            "document",
        "--artifact-id", "main-document", "--goal", "Write a report.", "--output", "output/report.md", ],
    )

    run_module.main()

    assert captured["spec"] == expected
    assert captured["state"] is not None


def test_main_exits_cleanly_if_play_game_returns_none(monkeypatch, capsys, tmp_path: Path) -> None:
    import baps.run as run_module

    monkeypatch.setattr("baps.orchestration.play_game", lambda _state, _spec, adapter=None, verification_result=None, **_kwargs: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(tmp_path / "ws-play-none"),
            "--project-type",
            "document",
        "--artifact-id", "main-document", "--goal", "Write a report.", "--output", "output/report.md", ],
    )
    run_module.main()
    captured = capsys.readouterr()
    assert "error: play_game produced no DeltaState" not in captured.err
    assert "update_applied=False" in captured.out
    assert "state_changed=False" in captured.out
    assert "stop_reason=northstar_update_proposed" in captured.out
    assert "northstar_proposal_written=True" in captured.out


def test_main_max_iterations_two_runs_two_iterations_with_state_carry_forward(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    import baps.run as run_module

    create_game_seen_sections: list[list[str]] = []

    def _create_game(config, state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        del verification_result
        document = next(a for a in state.artifacts if a.id == "main-document")
        section_titles = [s.title for s in document.sections]
        create_game_seen_sections.append(section_titles)
        if "Introduction" not in section_titles:
            objective = "Add introduction section"
        else:
            objective = "Add conclusion section"
        return run_module.GameSpec(
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
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(tmp_path / "ws-multi-iter"),
            "--project-type",
            "document",
            "--artifact-id", "main-document", "--goal", "Write a report.", "--output", "output/report.md", "--max-iterations",
            "2",
        ],
    )

    run_module.main()
    out = capsys.readouterr().out

    assert len(create_game_seen_sections) == 2
    assert create_game_seen_sections[0] == []
    assert create_game_seen_sections[1] == ["Introduction"]
    assert "update_applied=True" in out
    assert "state_changed=True" in out
    assert "output_exported=True" in out
    persisted = run_module.JsonStateStore(tmp_path / "ws-multi-iter" / "state" / "state.json").load()
    doc = next(a for a in persisted.artifacts if a.id == "main-document")
    assert [section.title for section in doc.sections] == ["Introduction", "Conclusion"]


def test_main_create_state_called_once_for_multi_iteration(monkeypatch, tmp_path: Path) -> None:
    import baps.run as run_module

    calls = {"count": 0}
    original_create_state = run_module.create_state

    def _capture_create_state(config):
        calls["count"] += 1
        return original_create_state(config)

    monkeypatch.setattr(run_module, "create_state", _capture_create_state)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(tmp_path / "ws-create-once"),
            "--project-type",
            "document",
            "--artifact-id", "main-document", "--goal", "Write a report.", "--output", "output/report.md", "--max-iterations",
            "2",
        ],
    )

    run_module.main()
    assert calls["count"] == 1


def test_main_stops_when_create_game_cannot_produce_new_game(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    import baps.run as run_module

    calls = {"count": 0}

    def _create_game(_config, _state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        del verification_result
        calls["count"] += 1
        if calls["count"] == 1:
            return run_module.GameSpec(
                objective="Add introduction section",
                target_artifact_id="main-document",
                allowed_delta_type="DeltaDocumentState",
                success_condition="Introduction section exists",
            )
        raise run_module.NoNewGameError("no further game")

    monkeypatch.setattr("baps.orchestration.create_game", _create_game)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(tmp_path / "ws-stop-no-game"),
            "--project-type",
            "document",
            "--artifact-id", "main-document", "--goal", "Write a report.", "--output", "output/report.md", "--max-iterations",
            "3",
        ],
    )

    run_module.main()
    out = capsys.readouterr().out
    assert "stop_reason=create_game_no_new_game" in out


def test_no_new_game_accepted_when_no_verification_has_run(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    """no_new_game is a valid stop when verification has never run (non-coding)."""
    import baps.run as run_module

    monkeypatch.setattr(
        "baps.orchestration.create_game",
        lambda _c, _s, adapter=None, verification_result=None, context_chain=(), depth=0, **_kw: (
            (_ for _ in ()).throw(run_module.NoNewGameError("done"))
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run", "start",
            "--workspace", str(tmp_path / "ws-no-vr-no-new-game"),
            "--project-type", "document",
            "--artifact-id", "main-document",
            "--goal", "Write a report.", "--output", "output/report.md",
        ],
    )
    run_module.main()
    out = capsys.readouterr().out
    assert "stop_reason=create_game_no_new_game" in out


def test_no_new_game_accepted_when_verification_passed(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    """no_new_game is a valid stop when the last verification passed."""
    import baps.run as run_module

    create_calls = {"n": 0}

    def _create_game(_config, _state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        create_calls["n"] += 1
        if create_calls["n"] == 1:
            return run_module.GameSpec(
                objective="Write a file",
                target_artifact_id="main-codebase",
                allowed_delta_type="DeltaCodingState",
                success_condition="file exists",
            )
        raise run_module.NoNewGameError("done — tests pass")

    import baps.state as state_module

    def _play_game(_state, _spec, adapter=None, verification_result=None, **_kwargs):
        return state_module.DeltaCodingState(
            artifact_id="main-codebase",
            operation="write_file",
            payload=state_module.WriteFileDelta(
                file=state_module.CodeFile(path="main.py", content="x=1\n")
            ),
        )

    monkeypatch.setattr("baps.orchestration.create_game", _create_game)
    monkeypatch.setattr("baps.orchestration.play_game", _play_game)
    monkeypatch.setattr(
        "baps.orchestration._verify_export_with_adapter",
        lambda _a, _o, _s, _id, **_kw: run_module.VerificationResult(
            command="pytest", cwd="/tmp", exit_code=0, stdout="1 passed", stderr="", passed=True
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run", "start",
            "--workspace", str(tmp_path / "ws-vr-pass-no-new-game"),
            "--project-type", "coding",
            "--artifact-id", "main-codebase",
            "--goal", "Write a file.", "--output", "output/project",
            "--language", "python",
        ],
    )
    run_module.main()
    out = capsys.readouterr().out
    assert "stop_reason=create_game_no_new_game" in out


def test_no_new_game_rejected_when_verification_failed(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    """no_new_game is NOT accepted when the last verification failed.
    The runtime retries once, then escalates if still stuck."""
    import baps.run as run_module

    create_calls = {"n": 0}
    verification_results_seen: list[run_module.VerificationResult | None] = []

    failing_vr = run_module.VerificationResult(
        command="pytest", cwd="/tmp", exit_code=1,
        stdout="FAILED test_foo.py::test_bar", stderr="", passed=False,
    )

    def _create_game(_config, _state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        create_calls["n"] += 1
        verification_results_seen.append(verification_result)
        if create_calls["n"] == 1:
            return run_module.GameSpec(
                objective="Write a file",
                target_artifact_id="main-codebase",
                allowed_delta_type="DeltaCodingState",
                success_condition="file exists",
            )
        raise run_module.NoNewGameError("no gap seen")  # on call 2 and 3 — model wrong

    import baps.state as state_module

    def _play_game(_state, _spec, adapter=None, verification_result=None, **_kwargs):
        return state_module.DeltaCodingState(
            artifact_id="main-codebase",
            operation="write_file",
            payload=state_module.WriteFileDelta(
                file=state_module.CodeFile(path="main.py", content="x=1\n")
            ),
        )

    monkeypatch.setattr("baps.orchestration.create_game", _create_game)
    monkeypatch.setattr("baps.orchestration.play_game", _play_game)
    monkeypatch.setattr(
        "baps.orchestration._verify_export_with_adapter",
        lambda _a, _o, _s, _id, **_kw: failing_vr,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run", "start",
            "--workspace", str(tmp_path / "ws-vr-fail-no-new-game"),
            "--project-type", "coding",
            "--artifact-id", "main-codebase",
            "--goal", "Write a file with tests.", "--output", "output/project",
            "--language", "python",
            "--max-iterations", "5",
        ],
    )
    run_module.main()
    out = capsys.readouterr().out

    # Must NOT stop with create_game_no_new_game while verification is failing
    assert "stop_reason=create_game_no_new_game" not in out
    # After two consecutive no_new_game with failing verification, escalates
    assert "stop_reason=northstar_update_proposed" in out
    # create_game was called 3 times: 1 (GameSpec) + 2 (no_new_game override + escalation)
    assert create_calls["n"] == 3
    # Second and third calls received the failing verification result
    assert verification_results_seen[1] is not None
    assert verification_results_seen[1].passed is False
    assert verification_results_seen[2] is not None
    assert verification_results_seen[2].passed is False


def test_no_new_game_override_resets_after_leaf_game(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    """After a leaf game runs, the override flag resets so another retry is allowed."""
    import baps.run as run_module

    # Sequence: GameSpec → (leaf runs, verification fails) → no_new_game (override 1)
    # → GameSpec → (leaf runs, verification fails) → no_new_game (override 2, fresh slate)
    # → no_new_game (escalate after fresh override)
    create_calls = {"n": 0}

    failing_vr = run_module.VerificationResult(
        command="pytest", cwd="/tmp", exit_code=1,
        stdout="FAILED", stderr="", passed=False,
    )

    def _create_game(_config, _state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        create_calls["n"] += 1
        if create_calls["n"] in (1, 3):
            return run_module.GameSpec(
                objective="Write a file",
                target_artifact_id="main-codebase",
                allowed_delta_type="DeltaCodingState",
                success_condition="file exists",
            )
        raise run_module.NoNewGameError("no gap")

    import baps.state as state_module

    play_calls = {"n": 0}

    def _play_game(_state, _spec, adapter=None, verification_result=None, **_kwargs):
        play_calls["n"] += 1
        return state_module.DeltaCodingState(
            artifact_id="main-codebase",
            operation="write_file",
            payload=state_module.WriteFileDelta(
                file=state_module.CodeFile(path=f"file_{play_calls['n']}.py", content="x=1\n")
            ),
        )

    monkeypatch.setattr("baps.orchestration.create_game", _create_game)
    monkeypatch.setattr("baps.orchestration.play_game", _play_game)
    monkeypatch.setattr(
        "baps.orchestration._verify_export_with_adapter",
        lambda _a, _o, _s, _id, **_kw: failing_vr,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run", "start",
            "--workspace", str(tmp_path / "ws-override-reset"),
            "--project-type", "coding",
            "--artifact-id", "main-codebase",
            "--goal", "Write files.", "--output", "output/project",
            "--language", "python",
            "--max-iterations", "10",
        ],
    )
    run_module.main()
    out = capsys.readouterr().out

    assert "stop_reason=northstar_update_proposed" in out
    # GameSpec(1) → leaf → no_new_game(2, override) → GameSpec(3) → leaf → no_new_game(4, fresh override) → no_new_game(5, escalate)
    assert create_calls["n"] == 5


def test_main_stop_reason_iteration_limit_reached_after_all_iterations_used(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    import baps.run as run_module

    create_game_calls = {"n": 0}

    def _create_game(_config, _state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        create_game_calls["n"] += 1
        return run_module.GameSpec(
            objective="Add a section",
            target_artifact_id="main-document",
            allowed_delta_type="DeltaDocumentState",
            success_condition="Section exists.",
        )

    monkeypatch.setattr("baps.orchestration.create_game", _create_game)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace", str(tmp_path / "ws-iter-limit"),
            "--project-type", "document",
            "--artifact-id", "main-document",
            "--goal", "Write a report.", "--output", "output/report.md",
            "--max-iterations", "2",
        ],
    )
    run_module.main()
    out = capsys.readouterr().out
    assert "stop_reason=iteration_limit_reached" in out
    assert create_game_calls["n"] == 2


def test_main_stop_reason_no_state_change_when_applied_delta_has_no_effect(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    import baps.run as run_module

    import baps.state_service as ss_module
    monkeypatch.setattr(ss_module.StateService, "states_differ", lambda self, _b, _a: False)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace", str(tmp_path / "ws-no-change"),
            "--project-type", "document",
            "--artifact-id", "main-document",
            "--goal", "Write a report.", "--output", "output/report.md",
            "--max-iterations", "3",
        ],
    )
    run_module.main()
    out = capsys.readouterr().out
    assert "stop_reason=northstar_update_proposed" in out
    assert "northstar_proposal_written=True" in out
    assert "state_changed=False" in out
    assert "update_applied=True" in out


def test_main_no_state_change_stops_loop_before_max_iterations(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    import baps.run as run_module

    create_game_calls = {"n": 0}

    def _create_game(_config, _state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        create_game_calls["n"] += 1
        return run_module.GameSpec(
            objective="Add a section",
            target_artifact_id="main-document",
            allowed_delta_type="DeltaDocumentState",
            success_condition="Section exists.",
        )

    import baps.state_service as ss_module
    monkeypatch.setattr("baps.orchestration.create_game", _create_game)
    monkeypatch.setattr(ss_module.StateService, "states_differ", lambda self, _b, _a: False)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace", str(tmp_path / "ws-no-change-early"),
            "--project-type", "document",
            "--artifact-id", "main-document",
            "--goal", "Write a report.", "--output", "output/report.md",
            "--max-iterations", "5",
        ],
    )
    run_module.main()
    out = capsys.readouterr().out
    assert "stop_reason=northstar_update_proposed" in out
    assert create_game_calls["n"] == 1


def test_main_no_state_change_after_prior_state_change_reports_state_changed_true(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    """State changed on iteration 1 (carried forward), then no change on iteration 2."""
    import baps.run as run_module

    call_count = {"n": 0}

    def _states_differ(self, _before, _after):
        call_count["n"] += 1
        # Call 1: iteration 1 — state changed
        # Call 2: iteration 2 — no state change
        return call_count["n"] <= 1

    import baps.state_service as ss_module
    monkeypatch.setattr(ss_module.StateService, "states_differ", _states_differ)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace", str(tmp_path / "ws-change-then-no-change"),
            "--project-type", "document",
            "--artifact-id", "main-document",
            "--goal", "Write a report.", "--output", "output/report.md",
            "--max-iterations", "5",
        ],
    )
    run_module.main()
    out = capsys.readouterr().out
    assert "stop_reason=northstar_update_proposed" in out
    assert "state_changed=True" in out


def test_play_game_no_delta_escalates_to_northstar_proposal(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    import baps.run as run_module

    workspace = tmp_path / "ws-no-delta-proposal"
    monkeypatch.setattr("baps.orchestration.play_game", lambda _s, _g, adapter=None, verification_result=None, **_kw: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run", "start",
            "--workspace", str(workspace),
            "--project-type", "document",
            "--artifact-id", "main-document",
            "--goal", "Write a report.", "--output", "output/report.md",
        ],
    )
    run_module.main()
    out = capsys.readouterr().out
    assert "stop_reason=northstar_update_proposed" in out
    assert "northstar_proposal_written=True" in out

    proposals_path = workspace / "blackboard" / "northstar_proposals.jsonl"
    assert proposals_path.exists()
    entry = json.loads(proposals_path.read_text(encoding="utf-8").strip())
    assert entry["event"] == "northstar_update_proposal"
    assert "play_game produced no accepted delta" in entry["rationale"]
    assert "created_at" in entry


def test_no_state_change_escalates_to_northstar_proposal(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    import baps.run as run_module
    import baps.state_service as ss_module

    workspace = tmp_path / "ws-no-change-proposal"
    monkeypatch.setattr(ss_module.StateService, "states_differ", lambda self, _b, _a: False)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run", "start",
            "--workspace", str(workspace),
            "--project-type", "document",
            "--artifact-id", "main-document",
            "--goal", "Write a report.", "--output", "output/report.md",
            "--max-iterations", "3",
        ],
    )
    run_module.main()
    out = capsys.readouterr().out
    assert "stop_reason=northstar_update_proposed" in out
    assert "northstar_proposal_written=True" in out

    proposals_path = workspace / "blackboard" / "northstar_proposals.jsonl"
    assert proposals_path.exists()
    entry = json.loads(proposals_path.read_text(encoding="utf-8").strip())
    assert entry["event"] == "northstar_update_proposal"
    assert "no state change" in entry["rationale"].lower()
    assert "created_at" in entry


def test_main_create_game_parse_error_is_not_swallowed_as_no_game(
    monkeypatch, capsys, caplog, tmp_path: Path
) -> None:
    import baps.run as run_module

    def _broken_create_game(_config, _state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        del verification_result
        raise ValueError("create_game model output must be valid JSON")

    monkeypatch.setattr("baps.orchestration.create_game", _broken_create_game)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(tmp_path / "ws-create-game-error"),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
            "--goal", "Write a report.", "--output", "output/report.md",
            "--max-iterations",
            "2",
        ],
    )
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
        run_module.main()
    assert exc.value.code == 2
    assert "create_game model output must be valid JSON" in caplog.text


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
    state = run_module.State(
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
    state = run_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="main-document", sections=()),),
    )
    output_path = tmp_path / "a" / "b" / "c" / "report.md"
    adapter.export_state(state, output_path, "main-document")
    assert output_path.parent.exists()


def test_document_export_output_changed_false_when_unchanged(tmp_path: Path) -> None:
    import baps.run as run_module

    adapter = DocumentProjectAdapter()
    state = run_module.State(
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
    import baps.run as run_module

    workspace = tmp_path / "ws-reset-no-model"

    def _fail(*_a, **_kw):
        raise AssertionError("model client must not be built during reset")

    monkeypatch.setattr(run_module, "_build_model_client", _fail)
    monkeypatch.setattr(run_module, "_build_planner_model_client", _fail)
    monkeypatch.setattr(run_module, "_build_role_client", _fail)
    monkeypatch.setattr(run_module, "_build_client_for_role", _fail)

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
        return run_module.GameSpec(
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
        run_module._run_project_iterations,
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


def test_coding_blue_prompt_supplement_prefers_src_and_pytest_layout() -> None:
    import baps.run as run_module

    state = run_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(id="main-codebase", files=()),),
    )
    spec = run_module.GameSpec(
        objective="Implement Fibonacci with tests",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="Working code and tests exist",
    )
    view = CodingProjectAdapter().build_state_view(state, spec)
    prompt = CodingProjectAdapter().render_blue_prompt(
        view,
        spec,
        attempt_number=1,
        previous_feedback=None,
    )
    assert "Prefer production code under src/." in prompt
    assert "Prefer tests under tests/." in prompt
    assert "tests/test_*.py" in prompt


def test_coding_create_game_prompt_includes_multi_file_guidance() -> None:
    import baps.run as run_module

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "coding",
        "artifact_id": "main-codebase",
        "language": "python",
        "goal": "Implement Fibonacci with tests",
        "northstar_markdown": "# Goal\n\nImplement Fibonacci with tests",
        "output_path": Path(".baps-workspace/output/project"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = run_module.create_state(config)
    adapter = CodingProjectAdapter()
    state_view = adapter.build_create_game_state_view(state, config)
    prompt = run_module._render_create_game_prompt(
        config=config,
        state=state,
        state_view=state_view,
        adapter=adapter,
    )
    assert "write_files" in prompt
    assert "Group logically related files" in prompt
    assert "Prefer production files under src/" in prompt


def test_coding_create_game_prompt_includes_previous_verification_evidence() -> None:
    import baps.run as run_module

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "coding",
        "artifact_id": "main-codebase",
        "language": "python",
        "goal": "Implement Fibonacci with tests",
        "northstar_markdown": "# Goal\n\nImplement Fibonacci with tests",
        "output_path": Path(".baps-workspace/output/project"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = run_module.create_state(config)
    adapter = CodingProjectAdapter()
    state_view = adapter.build_create_game_state_view(state, config)
    verification = run_module.VerificationResult(
        command="uv run pytest",
        cwd="/tmp/project",
        exit_code=2,
        stdout="ModuleNotFoundError: No module named 'src'",
        stderr="",
        passed=False,
    )
    prompt = run_module._render_create_game_prompt(
        config=config,
        state=state,
        state_view=state_view,
        verification_result=verification,
        adapter=adapter,
    )
    assert "previous_verification_result_json" in prompt
    assert "Use this as evidence from the previous exported state only." in prompt
    assert "If evidence shows import/layout errors, prefer a repair game" in prompt


def test_document_create_game_prompt_has_no_verification_block_by_default() -> None:
    import baps.run as run_module

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write report",
        "northstar_markdown": "# Goal\n\nWrite report",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = run_module.create_state(config)
    adapter = DocumentProjectAdapter()
    state_view = adapter.build_create_game_state_view(state, config)
    prompt = run_module._render_create_game_prompt(
        config=config,
        state=state,
        state_view=state_view,
        adapter=adapter,
    )
    assert "previous_verification_result_json" not in prompt


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
    state = run_module.State(
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
    original = run_module.GameSpec(
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

    state = run_module.State(
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

    state = run_module.State(
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

    state = run_module.State(
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

    state = run_module.State(
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
    state = run_module.State(
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

    state = run_module.State(
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

    state = run_module.State(
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

    state = run_module.State(
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

    state = run_module.State(
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

    state = run_module.State(
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
    state = run_module.State(
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
    state = run_module.State(
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

    state = run_module.State(
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
    state = run_module.State(
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
    result = run_module._commit_export_with_adapter(_CommittingAdapter(), output_dir, game_spec)
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
    result = run_module._commit_export_with_adapter(
        _NoCommitAdapter(), tmp_path / "project", game_spec
    )
    assert result is False


def test_document_adapter_render_create_game_prompt_supplement_includes_delta_guidance() -> None:
    import baps.run as run_module

    adapter = DocumentProjectAdapter()
    state = run_module.State(
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
    state = run_module.State(
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
    verification_result = run_module.VerificationResult(
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


def test_coding_parse_recovers_unescaped_quotes_in_content() -> None:
    import baps.coding_adapter as coding_module

    raw = (
        '{"artifact_id":"main-codebase","operation":"write_file","payload":{"file":{'
        '"path":"tests/test_fibonacci.py",'
        '"content":"def test_msg():\n    assert "hello" == "hello"\n"}}}'
    )
    delta = coding_module.parse_coding_delta_json(raw)
    assert delta.artifact_id == "main-codebase"
    assert delta.payload.file.path == "tests/test_fibonacci.py"
    assert 'assert "hello" == "hello"' in delta.payload.file.content


def test_coding_parse_recovers_multiline_pytest_content() -> None:
    import baps.coding_adapter as coding_module

    raw = (
        '{"artifact_id":"main-codebase","operation":"write_file","payload":{"file":{'
        '"path":"tests/test_fibonacci.py",'
        '"content":"import pytest\n'
        'from src.fibonacci import fibonacci\n\n'
        'def test_values():\n'
        '    assert fibonacci(0) == 0\n'
        '    assert fibonacci(5) == 5\n"}}}'
    )
    delta = coding_module.parse_coding_delta_json(raw)
    assert "import pytest" in delta.payload.file.content
    assert "assert fibonacci(5) == 5" in delta.payload.file.content


def test_coding_parse_recovers_long_content_payload() -> None:
    import baps.coding_adapter as coding_module

    long_lines = ["def test_many():"] + [f"    assert {i} == {i}" for i in range(300)]
    long_content = "\n".join(long_lines)
    raw = (
        '{"artifact_id":"main-codebase","operation":"write_file","payload":{"file":{'
        '"path":"tests/test_fibonacci.py",'
        f'"content":"{long_content}"'
        "}}}"
    )
    delta = coding_module.parse_coding_delta_json(raw)
    assert len(delta.payload.file.content.splitlines()) >= 301
    assert "assert 299 == 299" in delta.payload.file.content


def test_coding_parse_rejects_reasoning_note_marker() -> None:
    import baps.coding_adapter as coding_module

    raw = (
        '{"artifact_id":"main-codebase","operation":"write_file","payload":{"file":{'
        '"path":"tests/test_fibonacci.py",'
        '"content":"import pytest\\n# Note: choosing approach\\ndef test_ok():\\n    assert 1 == 1\\n"'
        "}}}"
    )
    with pytest.raises(ValueError, match="forbidden reasoning marker"):
        coding_module.parse_coding_delta_json(raw)


def test_coding_parse_rejects_self_correction_marker() -> None:
    import baps.coding_adapter as coding_module

    raw = (
        '{"artifact_id":"main-codebase","operation":"write_file","payload":{"file":{'
        '"path":"tests/test_fibonacci.py",'
        '"content":"def test_ok():\\n    assert 1 == 1\\n# Correcting the above\\n"'
        "}}}"
    )
    with pytest.raises(ValueError, match="forbidden reasoning marker"):
        coding_module.parse_coding_delta_json(raw)


def test_coding_parse_rejects_rewriting_commentary_marker() -> None:
    import baps.coding_adapter as coding_module

    raw = (
        '{"artifact_id":"main-codebase","operation":"write_file","payload":{"file":{'
        '"path":"tests/test_fibonacci.py",'
        '"content":"import pytest\\n# Re-writing content structure\\ndef test_ok():\\n    assert 1 == 1\\n"'
        "}}}"
    )
    with pytest.raises(ValueError, match="forbidden reasoning marker"):
        coding_module.parse_coding_delta_json(raw)


def test_coding_parse_fixes_double_escaped_quotes_in_single_line_content() -> None:
    import baps.coding_adapter as coding_module

    # Model double-escaped quotes: after json.loads, content contains \" (backslash + quote)
    # instead of the intended ". Use json.dumps to build valid JSON with that content.
    content_with_escape = 'def greet(): return \\"hello\\"'  # literal: def greet(): return \"hello\"
    raw = json.dumps({
        "artifact_id": "main-codebase",
        "operation": "write_file",
        "payload": {"file": {"path": "src/util.py", "content": content_with_escape}},
    })
    delta = coding_module.parse_coding_delta_json(raw)
    assert delta.payload.file.content == 'def greet(): return "hello"'


def test_coding_parse_fixes_double_escaped_quotes_in_multiline_python() -> None:
    import baps.coding_adapter as coding_module

    # Multiline .py content with \" where " was intended (syntax error without fix)
    content_with_escape = 'def test_empty():\n    assert normalize(\\"") == \\"\\"\n'
    raw = json.dumps({
        "artifact_id": "main-codebase",
        "operation": "write_file",
        "payload": {"file": {"path": "tests/test_util.py", "content": content_with_escape}},
    })
    delta = coding_module.parse_coding_delta_json(raw)
    assert '\\"' not in delta.payload.file.content
    assert 'normalize("") == ""' in delta.payload.file.content


def test_coding_parse_leaves_valid_multiline_python_unchanged() -> None:
    import baps.coding_adapter as coding_module

    # Valid multiline Python with no backslash-quote issues
    content = 'def test_ok():\n    assert 1 == 1\n'
    raw = json.dumps({
        "artifact_id": "main-codebase",
        "operation": "write_file",
        "payload": {"file": {"path": "tests/test_ok.py", "content": content}},
    })
    delta = coding_module.parse_coding_delta_json(raw)
    assert delta.payload.file.content == content


def test_coding_parse_does_not_fix_backslash_quotes_in_multiline_non_python_files() -> None:
    import baps.coding_adapter as coding_module

    # Multi-line non-.py file: the fix only applies to .py files for multi-line content.
    content = 'key: \\"value\\"\nother: \\"field\\"'  # literal: key: \"value\"\nother: \"field\"
    raw = json.dumps({
        "artifact_id": "main-codebase",
        "operation": "write_file",
        "payload": {"file": {"path": "config.yaml", "content": content}},
    })
    delta = coding_module.parse_coding_delta_json(raw)
    assert delta.payload.file.content == content


def test_coding_run_no_files_keeps_output_exported_false(monkeypatch, tmp_path: Path, capsys) -> None:
    import baps.run as run_module

    workspace = tmp_path / "coding-empty-export"
    monkeypatch.setattr(
        "baps.orchestration.create_game",
        lambda *_args, **_kwargs: run_module.GameSpec(
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
        lambda *_args, **_kwargs: run_module.GameSpec(
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
        lambda *_args, **_kwargs: run_module.GameSpec(
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
            return run_module.StateView(
                id="state-view:test",
                projection_type=run_module.ProjectionType.NORTH_STAR,
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
    spec = run_module.GameSpec(
        objective="Add section",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="section exists",
    )
    state = run_module.State(
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
                return run_module.StateUpdateProposal(
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
    proposal = run_module._derive_state_update_from_delta(delta, adapter=_MapperAdapter())
    assert proposal.id == "mapped"


def test_run_module_has_no_legacy_compatibility_shim_wrappers() -> None:
    import baps.run as run_module

    assert not hasattr(run_module, "_build_blue_state_view")
    assert not hasattr(run_module, "_parse_blue_delta_json")
    assert not hasattr(run_module, "_create_game_with_adapter")
    assert not hasattr(run_module, "_play_game_with_adapter")
    src = inspect.getsource(run_module._run_project_iterations)
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
            return run_module.GameSpec(
                objective="Write src/fibonacci.py containing implementation",
                target_artifact_id="main-codebase",
                allowed_delta_type="DeltaCodingState",
                success_condition="src/fibonacci.py exists",
            )
        if call_counter["count"] == 2:
            return run_module.GameSpec(
                objective="Write tests/test_fibonacci.py containing tests",
                target_artifact_id="main-codebase",
                allowed_delta_type="DeltaCodingState",
                success_condition="tests/test_fibonacci.py exists",
            )
        raise run_module.NoNewGameError("done")

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
    assert isinstance(verification_seen[1], run_module.VerificationResult)  # second iteration: receives prior export result


def test_coding_create_game_receives_previous_verification_result_second_iteration(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.run as run_module

    workspace = tmp_path / "coding-create-game-verification-input"
    seen: list[run_module.VerificationResult | None] = []
    create_count = {"n": 0}

    def _create_game(_config, _state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        del adapter
        seen.append(verification_result)
        create_count["n"] += 1
        if create_count["n"] == 1:
            return run_module.GameSpec(
                objective="Write src/fibonacci.py containing implementation",
                target_artifact_id="main-codebase",
                allowed_delta_type="DeltaCodingState",
                success_condition="src/fibonacci.py exists",
            )
        if create_count["n"] == 2:
            return run_module.GameSpec(
                objective="Write tests/test_fibonacci.py containing tests",
                target_artifact_id="main-codebase",
                allowed_delta_type="DeltaCodingState",
                success_condition="tests/test_fibonacci.py exists",
            )
        raise run_module.NoNewGameError("done")

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
            return run_module.VerificationResult(
                command="uv run pytest",
                cwd=str(workspace / "output" / "project"),
                exit_code=2,
                stdout="ModuleNotFoundError: No module named 'src'",
                stderr="",
                passed=False,
            )
        return run_module.VerificationResult(
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


def test_parse_create_game_output_northstar_update_needed_raises_signal() -> None:
    import baps.run as run_module

    raw = json.dumps({
        "northstar_update_needed": True,
        "rationale": "Accumulated state has drifted from NorthStar intent.",
        "proposed_northstar": "# Updated Goal\n\nNew direction.",
    })
    with pytest.raises(run_module.NorthStarUpdateNeededError) as exc_info:
        run_module._parse_create_game_output(raw)

    assert exc_info.value.rationale == "Accumulated state has drifted from NorthStar intent."
    assert exc_info.value.proposed_northstar == "# Updated Goal\n\nNew direction."


def test_parse_create_game_output_northstar_update_needed_flag_false_falls_through_to_game_spec() -> None:
    import baps.run as run_module

    # false marker → not classified as northstar response; falls through to GameSpec missing-keys error
    raw = json.dumps({
        "northstar_update_needed": False,
        "rationale": "some reason",
        "proposed_northstar": "new northstar",
    })
    with pytest.raises(ValueError, match="must contain exactly keys"):
        run_module._parse_create_game_output(raw)


def test_parse_create_game_output_northstar_update_needed_empty_rationale_raises() -> None:
    import baps.run as run_module

    raw = json.dumps({
        "northstar_update_needed": True,
        "rationale": "   ",
        "proposed_northstar": "new northstar",
    })
    with pytest.raises(ValueError, match="rationale must be non-empty"):
        run_module._parse_create_game_output(raw)


def test_parse_create_game_output_northstar_update_needed_empty_proposed_northstar_raises() -> None:
    import baps.run as run_module

    raw = json.dumps({
        "northstar_update_needed": True,
        "rationale": "valid rationale",
        "proposed_northstar": "   ",
    })
    with pytest.raises(ValueError, match="proposed_northstar must be non-empty"):
        run_module._parse_create_game_output(raw)


def test_create_game_prompt_includes_northstar_update_needed_instruction() -> None:
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
    adapter = DocumentProjectAdapter()
    prompt = run_module._render_create_game_prompt(
        config, state, adapter.build_create_game_state_view(state, config), adapter=adapter
    )

    assert '"northstar_update_needed": true' in prompt
    assert '"rationale"' in prompt
    assert '"proposed_northstar"' in prompt
    assert "cannot satisfy NorthStar without changing NorthStar itself" in prompt
    assert "complete updated NorthStar content" in prompt


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
    with pytest.raises(run_module.NorthStarUpdateNeededError) as exc_info:
        run_module.create_game(
            config, state, model_client=FakeModelClient([response])
        )

    assert "drifted" in exc_info.value.rationale
    assert "Revised" in exc_info.value.proposed_northstar


def test_run_iterations_northstar_update_proposed_writes_blackboard_and_stops(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    import baps.run as run_module

    workspace = tmp_path / "ws-northstar-proposal"

    def _create_game_raises(_config, _state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        raise run_module.NorthStarUpdateNeededError(
            rationale="Game direction contradicts NorthStar.",
            proposed_northstar="# Revised NorthStar\n\nNew direction.",
        )

    monkeypatch.setattr("baps.orchestration.create_game", _create_game_raises)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace", str(workspace),
            "--project-type", "document",
            "--artifact-id", "main-document",
            "--goal", "Write a report.", "--output", "output/report.md",
            "--max-iterations", "3",
        ],
    )

    run_module.main()
    out = capsys.readouterr().out

    assert "stop_reason=northstar_update_proposed" in out
    assert "northstar_proposal_written=True" in out

    proposals_path = workspace / "blackboard" / "northstar_proposals.jsonl"
    assert proposals_path.exists()
    entry = json.loads(proposals_path.read_text(encoding="utf-8").strip())
    assert entry["event"] == "northstar_update_proposal"
    assert entry["rationale"] == "Game direction contradicts NorthStar."
    assert entry["proposed_northstar"] == "# Revised NorthStar\n\nNew direction."
    assert "created_at" in entry


def test_run_iterations_northstar_update_proposed_does_not_apply_state_update(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.run as run_module

    workspace = tmp_path / "ws-northstar-no-update"

    def _create_game_raises(_config, _state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        raise run_module.NorthStarUpdateNeededError(
            rationale="Direction mismatch.",
            proposed_northstar="# New NorthStar",
        )

    monkeypatch.setattr("baps.orchestration.create_game", _create_game_raises)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace", str(workspace),
            "--project-type", "document",
            "--artifact-id", "main-document",
            "--goal", "Write a report.", "--output", "output/report.md",
            "--max-iterations", "3",
        ],
    )

    run_module.main()

    state_path = workspace / "state" / "state.json"
    initial_state = run_module.State.model_validate(
        json.loads(state_path.read_text(encoding="utf-8"))
    )
    assert len(initial_state.artifacts) == 1
    artifact = initial_state.artifacts[0]
    assert hasattr(artifact, "sections") or artifact.kind == "document"


def test_run_iterations_northstar_proposal_appends_on_multiple_signals(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.run as run_module

    workspace = tmp_path / "ws-northstar-append"

    proposals_path = workspace / "blackboard" / "northstar_proposals.jsonl"
    proposals_path.parent.mkdir(parents=True, exist_ok=True)
    proposals_path.write_text(
        json.dumps({
            "event": "northstar_update_proposal",
            "rationale": "Earlier proposal.",
            "proposed_northstar": "# Old NorthStar",
            "created_at": "2026-01-01T00:00:00",
        }) + "\n",
        encoding="utf-8",
    )

    def _create_game_raises(_config, _state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        raise run_module.NorthStarUpdateNeededError(
            rationale="New mismatch.",
            proposed_northstar="# Newer NorthStar",
        )

    monkeypatch.setattr("baps.orchestration.create_game", _create_game_raises)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace", str(workspace),
            "--project-type", "document",
            "--artifact-id", "main-document",
            "--goal", "Write a report.", "--output", "output/report.md",
            "--max-iterations", "1",
        ],
    )

    run_module.main()

    lines = [l for l in proposals_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["rationale"] == "Earlier proposal."
    assert second["rationale"] == "New mismatch."


# ---------------------------------------------------------------------------
# Backend dispatch tests
# ---------------------------------------------------------------------------

def test_build_model_client_returns_ollama_by_default(monkeypatch) -> None:
    monkeypatch.delenv("BAPS_BACKEND", raising=False)
    monkeypatch.setenv("BAPS_OLLAMA_MODEL", "llama3.2")
    client = _real_build_model_client()
    assert isinstance(client, OllamaClient)
    assert client.model == "llama3.2"


def test_build_model_client_returns_anthropic_when_backend_set(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("BAPS_ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    client = _real_build_model_client()
    assert isinstance(client, AnthropicClient)
    assert client.model == "claude-haiku-4-5-20251001"
    assert client.api_key == "sk-ant-test"


def test_build_model_client_returns_openai_when_backend_set(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_BACKEND", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    monkeypatch.setenv("BAPS_OPENAI_MODEL", "gpt-4o-mini")
    client = _real_build_model_client()
    assert isinstance(client, OpenAIClient)
    assert client.model == "gpt-4o-mini"
    assert client.api_key == "sk-openai-test"


def test_build_client_anthropic_raises_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        _real_run._build_client("anthropic", "claude-sonnet-4-6")


def test_build_client_openai_raises_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        _real_run._build_client("openai", "gpt-4o")


def test_build_create_game_client_uses_cloud_client_without_planner_split(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("BAPS_OLLAMA_PLANNER_MODEL", raising=False)
    client = _real_build_planner_model_client()
    assert isinstance(client, AnthropicClient)


def test_build_create_game_client_uses_ollama_planner_model_when_set(monkeypatch) -> None:
    monkeypatch.delenv("BAPS_BACKEND", raising=False)
    monkeypatch.setenv("BAPS_OLLAMA_PLANNER_MODEL", "mistral")
    monkeypatch.setenv("BAPS_OLLAMA_MODEL", "llama3.2")
    client = _real_build_planner_model_client()
    assert isinstance(client, OllamaClient)
    assert client.model == "mistral"


def test_build_create_game_client_falls_back_to_ollama_model_when_no_planner(monkeypatch) -> None:
    monkeypatch.delenv("BAPS_BACKEND", raising=False)
    monkeypatch.delenv("BAPS_OLLAMA_PLANNER_MODEL", raising=False)
    monkeypatch.setenv("BAPS_OLLAMA_MODEL", "llama3.2")
    client = _real_build_planner_model_client()
    assert isinstance(client, OllamaClient)
    assert client.model == "llama3.2"


# --- _build_role_client tests ---


def test_build_role_client_falls_back_to_global_when_no_role_vars(monkeypatch) -> None:
    monkeypatch.delenv("BAPS_RED_BACKEND", raising=False)
    monkeypatch.delenv("BAPS_RED_MODEL", raising=False)
    monkeypatch.delenv("BAPS_BACKEND", raising=False)
    monkeypatch.setenv("BAPS_OLLAMA_MODEL", "llama3.2")
    # Restore the real _build_model_client so the fallback path exercises it,
    # not the FakeModelClient injected by the autouse fixture.
    monkeypatch.setattr("baps.run._build_model_client", _real_build_model_client)
    client = _real_build_role_client("red")
    assert isinstance(client, OllamaClient)
    assert client.model == "llama3.2"


def test_build_role_client_uses_role_model_on_anthropic_backend(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_RED_BACKEND", "anthropic")
    monkeypatch.setenv("BAPS_RED_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client = _real_build_role_client("red")
    assert isinstance(client, AnthropicClient)
    assert client.model == "claude-haiku-4-5-20251001"


def test_build_role_client_uses_role_model_on_openai_backend(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_REFEREE_BACKEND", "openai")
    monkeypatch.setenv("BAPS_REFEREE_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    client = _real_build_role_client("referee")
    assert isinstance(client, OpenAIClient)
    assert client.model == "gpt-4o-mini"


def test_build_role_client_uses_role_model_on_ollama_backend(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_BLUE_BACKEND", "ollama")
    monkeypatch.setenv("BAPS_BLUE_MODEL", "gemma3:latest")
    client = _real_build_role_client("blue")
    assert isinstance(client, OllamaClient)
    assert client.model == "gemma3:latest"


def test_build_role_client_infers_backend_from_global_when_only_model_set(monkeypatch) -> None:
    monkeypatch.delenv("BAPS_RED_BACKEND", raising=False)
    monkeypatch.setenv("BAPS_RED_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.setenv("BAPS_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client = _real_build_role_client("red")
    assert isinstance(client, AnthropicClient)
    assert client.model == "claude-haiku-4-5-20251001"


def test_build_role_client_raises_on_anthropic_without_api_key(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_RED_BACKEND", "anthropic")
    monkeypatch.setenv("BAPS_RED_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        _real_build_role_client("red")


def test_build_role_client_raises_on_openai_without_api_key(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_REFEREE_BACKEND", "openai")
    monkeypatch.setenv("BAPS_REFEREE_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        _real_build_role_client("referee")


def test_build_role_client_uses_global_anthropic_model_when_only_backend_set(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_BLUE_BACKEND", "anthropic")
    monkeypatch.delenv("BAPS_BLUE_MODEL", raising=False)
    monkeypatch.setenv("BAPS_ANTHROPIC_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client = _real_build_role_client("blue")
    assert isinstance(client, AnthropicClient)
    assert client.model == "claude-sonnet-4-6"


# --- _resolve_backend_model / _build_client_for_role tests ---


def test_resolve_backend_model_spec_global_overrides_env(monkeypatch) -> None:
    import baps.run as run_module

    monkeypatch.setenv("BAPS_BACKEND", "ollama")
    monkeypatch.setenv("BAPS_OLLAMA_MODEL", "env-model")
    config = {"spec_backend": "ollama", "spec_model": "spec-model", "spec_roles": {}}
    backend, model = run_module._resolve_backend_model("blue", config)
    assert backend == "ollama"
    assert model == "spec-model"


def test_resolve_backend_model_role_spec_overrides_global_spec(monkeypatch) -> None:
    import baps.run as run_module

    monkeypatch.delenv("BAPS_BACKEND", raising=False)
    config = {
        "spec_backend": "ollama",
        "spec_model": "global-model",
        "spec_roles": {"blue": {"backend": "ollama", "model": "role-model"}},
    }
    backend, model = run_module._resolve_backend_model("blue", config)
    assert model == "role-model"


def test_resolve_backend_model_env_fallback_when_no_spec(monkeypatch) -> None:
    import baps.run as run_module

    monkeypatch.setenv("BAPS_BACKEND", "ollama")
    monkeypatch.setenv("BAPS_OLLAMA_MODEL", "env-model")
    config: dict = {"spec_backend": None, "spec_model": None, "spec_roles": {}}
    backend, model = run_module._resolve_backend_model("blue", config)
    assert backend == "ollama"
    assert model == "env-model"


def test_resolve_backend_model_role_env_overrides_global_env(monkeypatch) -> None:
    import baps.run as run_module

    monkeypatch.setenv("BAPS_BACKEND", "ollama")
    monkeypatch.setenv("BAPS_OLLAMA_MODEL", "global-env")
    monkeypatch.setenv("BAPS_BLUE_BACKEND", "ollama")
    monkeypatch.setenv("BAPS_BLUE_MODEL", "role-env")
    config: dict = {"spec_backend": None, "spec_model": None, "spec_roles": {}}
    backend, model = run_module._resolve_backend_model("blue", config)
    assert model == "role-env"


def test_resolve_backend_model_raises_when_nothing_configured(monkeypatch) -> None:
    import baps.run as run_module

    for var in ("BAPS_BACKEND", "BAPS_OLLAMA_MODEL", "BAPS_ANTHROPIC_MODEL",
                "BAPS_OPENAI_MODEL", "BAPS_BLUE_BACKEND", "BAPS_BLUE_MODEL"):
        monkeypatch.delenv(var, raising=False)
    config: dict = {"spec_backend": None, "spec_model": None, "spec_roles": {}}
    with pytest.raises(ValueError, match="No model configured"):
        run_module._resolve_backend_model("blue", config)


def test_resolve_backend_model_raises_on_unknown_backend(monkeypatch) -> None:
    import baps.run as run_module

    config: dict = {"spec_backend": "bogus", "spec_model": "some-model", "spec_roles": {}}
    with pytest.raises(ValueError, match="Unknown backend"):
        run_module._resolve_backend_model("blue", config)


def test_resolve_backend_model_role_spec_backend_only_falls_back_to_spec_model(monkeypatch) -> None:
    import baps.run as run_module

    monkeypatch.delenv("BAPS_RED_MODEL", raising=False)
    config = {
        "spec_backend": "ollama",
        "spec_model": "global-model",
        "spec_roles": {"red": {"backend": "ollama"}},
    }
    backend, model = run_module._resolve_backend_model("red", config)
    assert backend == "ollama"
    assert model == "global-model"


def test_build_client_for_role_constructs_ollama_client(monkeypatch) -> None:
    import baps.run as run_module

    config = {"spec_backend": "ollama", "spec_model": "gemma4:e4b", "spec_roles": {}}
    client = run_module._build_client(  # bypass env
        *run_module._resolve_backend_model("blue", config)
    )
    assert isinstance(client, OllamaClient)
    assert client.model == "gemma4:e4b"


def test_build_client_constructs_anthropic_client(monkeypatch) -> None:
    # Test _build_client directly (not patched by autouse fixture).
    import baps.run as run_module

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client = run_module._build_client("anthropic", "claude-haiku-4-5-20251001")
    assert isinstance(client, AnthropicClient)
    assert client.model == "claude-haiku-4-5-20251001"


def test_build_client_anthropic_raises_without_api_key(monkeypatch) -> None:
    import baps.run as run_module

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        run_module._build_client("anthropic", "claude-sonnet-4-6")


def test_spec_backend_and_model_parsed_into_config(tmp_path: Path) -> None:
    import argparse
    import yaml
    import baps.run as run_module

    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_markdown": "# Goal",
        "goal": "write",
        "output": "output/doc.md",
        "backend": "ollama",
        "model": "gemma4:e4b",
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path), workspace=None, artifact_id=None, goal=None,
        output=None, max_iterations=None, project_type=None, sandbox=None,
        command="start", language=None,
    )
    config = run_module.resolve_run_config(args)
    assert config["spec_backend"] == "ollama"
    assert config["spec_model"] == "gemma4:e4b"
    assert config["spec_roles"] == {}


def test_spec_roles_parsed_into_config(tmp_path: Path) -> None:
    import argparse
    import yaml
    import baps.run as run_module

    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_markdown": "# Goal",
        "goal": "write",
        "output": "output/doc.md",
        "backend": "ollama",
        "model": "gemma4:e4b",
        "roles": {
            "blue": {"backend": "anthropic", "model": "claude-sonnet-4-6"},
            "decompose": {"backend": "ollama", "model": "gemma4:e4b"},
        },
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path), workspace=None, artifact_id=None, goal=None,
        output=None, max_iterations=None, project_type=None, sandbox=None,
        command="start", language=None,
    )
    config = run_module.resolve_run_config(args)
    assert config["spec_roles"]["blue"]["backend"] == "anthropic"
    assert config["spec_roles"]["blue"]["model"] == "claude-sonnet-4-6"
    assert config["spec_roles"]["decompose"]["model"] == "gemma4:e4b"


def test_spec_backend_invalid_raises(tmp_path: Path) -> None:
    import argparse
    import yaml
    import baps.run as run_module

    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_markdown": "# Goal",
        "goal": "write",
        "output": "output/doc.md",
        "backend": "bogus",
        "model": "whatever",
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path), workspace=None, artifact_id=None, goal=None,
        output=None, max_iterations=None, project_type=None, sandbox=None,
        command="start", language=None,
    )
    with pytest.raises(ValueError, match="spec 'backend' must be one of"):
        run_module.resolve_run_config(args)


def test_spec_role_override_is_used_in_resolve(monkeypatch) -> None:
    import baps.run as run_module

    monkeypatch.setenv("BAPS_BACKEND", "ollama")
    monkeypatch.setenv("BAPS_OLLAMA_MODEL", "global-env")
    config = {
        "spec_backend": "ollama",
        "spec_model": "global-spec",
        "spec_roles": {"referee": {"backend": "ollama", "model": "referee-override"}},
    }
    backend, model = run_module._resolve_backend_model("referee", config)
    assert model == "referee-override"


def test_role_spec_backend_only_uses_spec_model_for_model(monkeypatch) -> None:
    import baps.run as run_module

    config = {
        "spec_backend": "ollama",
        "spec_model": "fallback-model",
        "spec_roles": {"red": {"backend": "ollama"}},
    }
    _, model = run_module._resolve_backend_model("red", config)
    assert model == "fallback-model"


# --- Model fallback/escalation tests ---

def test_spec_roles_parsed_with_fallback_config(tmp_path: Path) -> None:
    import argparse
    import yaml
    import baps.run as run_module

    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_markdown": "# Goal",
        "goal": "write",
        "output": "output/doc.md",
        "backend": "ollama",
        "model": "gemma4:e4b",
        "roles": {
            "create_game": {
                "backend": "ollama",
                "model": "gemma4:e4b",
                "fallback": {"backend": "ollama", "model": "gemma4:26b"},
            },
        },
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path), workspace=None, artifact_id=None, goal=None,
        output=None, max_iterations=None, project_type=None, sandbox=None,
        command="start", language=None,
    )
    config = run_module.resolve_run_config(args)
    role_cfg = config["spec_roles"]["create_game"]
    assert role_cfg["backend"] == "ollama"
    assert role_cfg["model"] == "gemma4:e4b"
    assert role_cfg["fallback"]["backend"] == "ollama"
    assert role_cfg["fallback"]["model"] == "gemma4:26b"


def test_spec_role_fallback_invalid_backend_raises(tmp_path: Path) -> None:
    import argparse
    import yaml
    import baps.run as run_module

    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_markdown": "# Goal",
        "goal": "write",
        "output": "output/doc.md",
        "backend": "ollama",
        "model": "gemma4:e4b",
        "roles": {
            "create_game": {
                "backend": "ollama",
                "model": "gemma4:e4b",
                "fallback": {"backend": "bogus", "model": "some-model"},
            },
        },
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path), workspace=None, artifact_id=None, goal=None,
        output=None, max_iterations=None, project_type=None, sandbox=None,
        command="start", language=None,
    )
    with pytest.raises(ValueError, match="roles.create_game.fallback.backend"):
        run_module.resolve_run_config(args)


def test_spec_role_fallback_non_mapping_raises(tmp_path: Path) -> None:
    import argparse
    import yaml
    import baps.run as run_module

    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_markdown": "# Goal",
        "goal": "write",
        "output": "output/doc.md",
        "backend": "ollama",
        "model": "gemma4:e4b",
        "roles": {
            "create_game": {
                "backend": "ollama",
                "model": "gemma4:e4b",
                "fallback": "ollama",
            },
        },
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path), workspace=None, artifact_id=None, goal=None,
        output=None, max_iterations=None, project_type=None, sandbox=None,
        command="start", language=None,
    )
    with pytest.raises(ValueError, match="roles.create_game.fallback.*must be a mapping"):
        run_module.resolve_run_config(args)


def test_build_fallback_client_for_role_returns_none_when_no_fallback() -> None:
    config: dict = {
        "spec_roles": {"create_game": {"backend": "ollama", "model": "gemma4:e4b"}},
    }
    result = _real_run._build_fallback_client_for_role("create_game", config)
    assert result is None


def test_build_fallback_client_for_role_returns_none_for_unconfigured_role() -> None:
    config: dict = {"spec_roles": {}}
    result = _real_run._build_fallback_client_for_role("create_game", config)
    assert result is None


def test_create_game_fallback_called_when_primary_exhausts_retries(monkeypatch) -> None:
    valid_response = (
        '{"objective":"Advance goal","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"section exists"}'
    )
    fallback_client = FakeModelClient(responses=[valid_response])
    _chain = lambda role, cfg: [("gemma4:26b", fallback_client)] if role == "create_game" else []
    monkeypatch.setattr("baps.run._build_fallback_chain_for_role", _chain)
    monkeypatch.setattr("baps.game._build_fallback_chain_for_role", _chain)

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
        "spec_roles": {},
    }
    state = create_state(config)

    # Primary exhausts initial call + two retries before escalating to fallback.
    primary_client = FakeModelClient(responses=["not-json"] * 3)
    game_spec = create_game(config, state, model_client=primary_client)

    assert game_spec.target_artifact_id == "main-document"
    assert len(fallback_client.prompts) == 1


def test_create_game_fallback_not_called_when_primary_succeeds(monkeypatch) -> None:
    valid_response = (
        '{"objective":"Advance goal","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"section exists"}'
    )
    fallback_client = FakeModelClient(responses=[valid_response])
    _chain = lambda role, cfg: [("gemma4:26b", fallback_client)] if role == "create_game" else []
    monkeypatch.setattr("baps.run._build_fallback_chain_for_role", _chain)
    monkeypatch.setattr("baps.game._build_fallback_chain_for_role", _chain)

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
        "spec_roles": {},
    }
    state = create_state(config)

    primary_client = FakeModelClient(responses=[valid_response])
    game_spec = create_game(config, state, model_client=primary_client)

    assert game_spec.target_artifact_id == "main-document"
    assert len(fallback_client.prompts) == 0


def test_play_game_red_fallback_called_when_primary_exhausts_retries(monkeypatch) -> None:
    import baps.run as run_module

    valid_accept = '{"disposition":"accept","rationale":"looks good"}'
    fallback_red_client = FakeModelClient(responses=[valid_accept])
    _chain = lambda role, cfg: [("gemma4:26b", fallback_red_client)] if role == "red" else []
    monkeypatch.setattr("baps.run._build_fallback_chain_for_role", _chain)
    monkeypatch.setattr("baps.game._build_fallback_chain_for_role", _chain)

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
    )
    state = create_state({
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    })

    blue_client = FakeModelClient(tool_responses=[ToolCall(
        name="append_section",
        arguments={"artifact_id": "main-document", "title": "Introduction", "body": "Any objective"},
    )])
    referee_client = FakeModelClient(responses=[valid_accept])
    # Primary red exhausts initial call + two retries before escalating to fallback.
    primary_red_client = FakeModelClient(responses=["not-json"] * 3)

    result = play_game(
        state,
        spec,
        model_client=blue_client,
        red_model_client=primary_red_client,
        referee_model_client=referee_client,
        config={"workspace": Path(".baps-workspace"), "spec_roles": {}},
    )

    assert result is not None
    assert len(fallback_red_client.prompts) == 1


def test_play_game_referee_fallback_called_when_primary_exhausts_retries(monkeypatch) -> None:
    import baps.run as run_module

    valid_accept = '{"disposition":"accept","rationale":"looks good"}'
    fallback_referee_client = FakeModelClient(responses=[valid_accept])
    _chain = lambda role, cfg: [("gemma4:26b", fallback_referee_client)] if role == "referee" else []
    monkeypatch.setattr("baps.run._build_fallback_chain_for_role", _chain)
    monkeypatch.setattr("baps.game._build_fallback_chain_for_role", _chain)

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
    )
    state = create_state({
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    })

    blue_client = FakeModelClient(tool_responses=[ToolCall(
        name="append_section",
        arguments={"artifact_id": "main-document", "title": "Introduction", "body": "Any objective"},
    )])
    red_client = FakeModelClient(responses=[valid_accept])
    # Primary referee exhausts initial call + two retries before escalating to fallback.
    primary_referee_client = FakeModelClient(responses=["not-json"] * 3)

    result = play_game(
        state,
        spec,
        model_client=blue_client,
        red_model_client=red_client,
        referee_model_client=primary_referee_client,
        config={"workspace": Path(".baps-workspace"), "spec_roles": {}},
    )

    assert result is not None
    assert len(fallback_referee_client.prompts) == 1


def test_spec_roles_parsed_with_deep_fallback_chain(tmp_path: Path) -> None:
    import argparse
    import yaml
    import baps.run as run_module

    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_markdown": "# Goal",
        "goal": "write",
        "output": "output/doc.md",
        "backend": "ollama",
        "model": "gemma4:e4b",
        "roles": {
            "create_game": {
                "backend": "ollama",
                "model": "gemma4:e4b",
                "fallback": {
                    "backend": "ollama",
                    "model": "gemma4:26b",
                    "fallback": {
                        "backend": "ollama",
                        "model": "gemma4:72b",
                    },
                },
            },
        },
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path), workspace=None, artifact_id=None, goal=None,
        output=None, max_iterations=None, project_type=None, sandbox=None,
        command="start", language=None,
    )
    config = run_module.resolve_run_config(args)
    role_cfg = config["spec_roles"]["create_game"]
    assert role_cfg["model"] == "gemma4:e4b"
    assert role_cfg["fallback"]["model"] == "gemma4:26b"
    assert role_cfg["fallback"]["fallback"]["model"] == "gemma4:72b"


def test_spec_role_deep_fallback_invalid_backend_raises(tmp_path: Path) -> None:
    import argparse
    import yaml
    import baps.run as run_module

    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_markdown": "# Goal",
        "goal": "write",
        "output": "output/doc.md",
        "backend": "ollama",
        "model": "gemma4:e4b",
        "roles": {
            "create_game": {
                "backend": "ollama",
                "model": "gemma4:e4b",
                "fallback": {
                    "backend": "ollama",
                    "model": "gemma4:26b",
                    "fallback": {
                        "backend": "bogus",
                        "model": "gemma4:72b",
                    },
                },
            },
        },
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path), workspace=None, artifact_id=None, goal=None,
        output=None, max_iterations=None, project_type=None, sandbox=None,
        command="start", language=None,
    )
    with pytest.raises(ValueError, match="roles.create_game.fallback.fallback.backend"):
        run_module.resolve_run_config(args)


def test_build_fallback_chain_for_role_returns_empty_when_no_fallback() -> None:
    config: dict = {
        "spec_roles": {"create_game": {"backend": "ollama", "model": "gemma4:e4b"}},
    }
    chain = _real_build_fallback_chain_for_role("create_game", config)
    assert chain == []


def test_build_fallback_chain_for_role_returns_empty_for_unconfigured_role() -> None:
    config: dict = {"spec_roles": {}}
    chain = _real_build_fallback_chain_for_role("create_game", config)
    assert chain == []


def test_build_fallback_chain_for_role_returns_single_entry_chain() -> None:
    config: dict = {
        "spec_roles": {
            "create_game": {
                "backend": "ollama",
                "model": "gemma4:e4b",
                "fallback": {"backend": "ollama", "model": "gemma4:26b"},
            }
        }
    }
    chain = _real_build_fallback_chain_for_role("create_game", config)
    assert len(chain) == 1
    assert chain[0][0] == "gemma4:26b"
    assert isinstance(chain[0][1], OllamaClient)


def test_build_fallback_chain_for_role_returns_two_entry_chain() -> None:
    config: dict = {
        "spec_roles": {
            "create_game": {
                "backend": "ollama",
                "model": "gemma4:e4b",
                "fallback": {
                    "backend": "ollama",
                    "model": "gemma4:26b",
                    "fallback": {"backend": "ollama", "model": "gemma4:72b"},
                },
            }
        }
    }
    chain = _real_build_fallback_chain_for_role("create_game", config)
    assert len(chain) == 2
    assert chain[0][0] == "gemma4:26b"
    assert chain[1][0] == "gemma4:72b"
    assert isinstance(chain[0][1], OllamaClient)
    assert isinstance(chain[1][1], OllamaClient)


def test_create_game_fallback_chain_escalates_through_all_links(monkeypatch) -> None:
    valid_response = (
        '{"objective":"Advance goal","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"section exists"}'
    )
    fail_client = FakeModelClient(responses=[])  # raises RuntimeError immediately
    success_client = FakeModelClient(responses=[valid_response])
    _chain = (
        lambda role, cfg: [("gemma4:26b", fail_client), ("gemma4:72b", success_client)]
        if role == "create_game" else []
    )
    monkeypatch.setattr("baps.run._build_fallback_chain_for_role", _chain)
    monkeypatch.setattr("baps.game._build_fallback_chain_for_role", _chain)

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
        "spec_roles": {},
    }
    state = create_state(config)

    primary_client = FakeModelClient(responses=["not-json"] * 3)
    game_spec = create_game(config, state, model_client=primary_client)

    assert game_spec.target_artifact_id == "main-document"
    assert len(fail_client.prompts) == 1  # called once, raised RuntimeError
    assert len(success_client.prompts) == 1  # called once, succeeded


def test_create_game_chain_exhaustion_raises_runtime_error(monkeypatch) -> None:
    fail_client1 = FakeModelClient(responses=[])
    fail_client2 = FakeModelClient(responses=[])
    _chain = (
        lambda role, cfg: [("gemma4:26b", fail_client1), ("gemma4:72b", fail_client2)]
        if role == "create_game" else []
    )
    monkeypatch.setattr("baps.run._build_fallback_chain_for_role", _chain)
    monkeypatch.setattr("baps.game._build_fallback_chain_for_role", _chain)

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
        "spec_roles": {},
    }
    state = create_state(config)

    primary_client = FakeModelClient(responses=["not-json"] * 3)
    with pytest.raises(RuntimeError, match="all models in fallback chain exhausted"):
        create_game(config, state, model_client=primary_client)


def test_no_fallback_behavior_unchanged_when_primary_succeeds(monkeypatch) -> None:
    valid_response = (
        '{"objective":"Advance goal","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"section exists"}'
    )
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
        "spec_roles": {},
    }
    state = create_state(config)

    primary_client = FakeModelClient(responses=[valid_response])
    game_spec = create_game(config, state, model_client=primary_client)

    assert game_spec.target_artifact_id == "main-document"
    assert len(primary_client.prompts) == 1  # called once, no retries needed


# --- write_files adapter tests ---

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


def test_parse_coding_delta_json_handles_write_files_operation() -> None:
    import json
    from baps.coding_adapter import parse_coding_delta_json

    text = json.dumps({
        "artifact_id": "main-codebase",
        "operation": "write_files",
        "payload": {
            "files": [
                {"path": "src/a.py", "content": "print('a')"},
                {"path": "src/b.py", "content": "print('b')"},
            ]
        },
    })
    delta = parse_coding_delta_json(text)
    assert isinstance(delta, state_module.DeltaCodingBatchState)
    assert delta.operation == "write_files"
    assert len(delta.payload.files) == 2


def test_parse_coding_delta_json_still_accepts_write_file_operation() -> None:
    import json
    from baps.coding_adapter import parse_coding_delta_json

    text = json.dumps({
        "artifact_id": "main-codebase",
        "operation": "write_file",
        "payload": {"file": {"path": "src/a.py", "content": "x"}},
    })
    delta = parse_coding_delta_json(text)
    assert isinstance(delta, state_module.DeltaCodingState)
    assert delta.operation == "write_file"


def test_parse_coding_delta_json_rejects_write_files_with_empty_files_list() -> None:
    import json
    from baps.coding_adapter import parse_coding_delta_json

    text = json.dumps({
        "artifact_id": "main-codebase",
        "operation": "write_files",
        "payload": {"files": []},
    })
    with pytest.raises(ValueError, match="DeltaCodingBatchState"):
        parse_coding_delta_json(text)


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

def test_parse_document_delta_json_handles_modify_section_operation() -> None:
    import json
    from baps.document_adapter import parse_document_delta_json

    text = json.dumps({
        "artifact_id": "main-document",
        "operation": "modify_section",
        "payload": {"section_title": "Intro", "new_body": "Updated intro."},
    })
    delta = parse_document_delta_json(text)
    assert isinstance(delta, state_module.DeltaModifyDocumentState)
    assert delta.payload.section_title == "Intro"
    assert delta.payload.new_body == "Updated intro."


def test_parse_document_delta_json_still_accepts_append_section() -> None:
    import json
    from baps.document_adapter import parse_document_delta_json

    text = json.dumps({
        "artifact_id": "main-document",
        "operation": "append_section",
        "payload": {"section": {"title": "New", "body": "Body."}},
    })
    delta = parse_document_delta_json(text)
    assert isinstance(delta, state_module.DeltaDocumentState)


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


def test_document_blue_prompt_includes_modify_section_shape() -> None:
    import baps.run as run_module

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a report.",
        "northstar_markdown": "# Goal\n\nWrite a report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = run_module.create_state(config)
    adapter = DocumentProjectAdapter()
    state_view = adapter.build_state_view(
        state,
        state_module.GameSpec(
            objective="Test",
            target_artifact_id="main-document",
            allowed_delta_type="DeltaDocumentState",
            success_condition="ok",
        ),
    )
    prompt = adapter.render_blue_prompt(
        state_view=state_view,
        game_spec=state_module.GameSpec(
            objective="Test",
            target_artifact_id="main-document",
            allowed_delta_type="DeltaDocumentState",
            success_condition="ok",
        ),
        attempt_number=1,
        previous_feedback=None,
    )
    assert "modify_section" in prompt
    assert "section_title" in prompt
    assert "new_body" in prompt


# --- delete_file adapter tests ---

def test_parse_coding_delta_json_handles_delete_file_operation() -> None:
    import json
    from baps.coding_adapter import parse_coding_delta_json

    text = json.dumps({
        "artifact_id": "main-codebase",
        "operation": "delete_file",
        "payload": {"path": "src/old.py"},
    })
    delta = parse_coding_delta_json(text)
    assert isinstance(delta, state_module.DeltaDeleteCodingState)
    assert delta.payload.path == "src/old.py"


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

def test_parse_document_delta_json_handles_delete_section_operation() -> None:
    import json
    from baps.document_adapter import parse_document_delta_json

    text = json.dumps({
        "artifact_id": "main-document",
        "operation": "delete_section",
        "payload": {"section_title": "Obsolete"},
    })
    delta = parse_document_delta_json(text)
    assert isinstance(delta, state_module.DeltaDeleteDocumentState)
    assert delta.payload.section_title == "Obsolete"


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

    state = run_module.State(
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
    state = run_module.State(
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

def test_parse_create_game_output_returns_decompose_spec() -> None:
    import baps.run as run_module

    text = json.dumps({
        "decompose": True,
        "rationale": "Gap is too large",
        "sub_gaps": [
            {"description": "Implement auth module"},
            {"description": "Implement user model"},
        ],
    })
    result = run_module._parse_create_game_output(text)
    assert isinstance(result, run_module.DecomposeSpec)
    assert result.rationale == "Gap is too large"
    assert len(result.sub_gaps) == 2
    assert result.sub_gaps[0].description == "Implement auth module"
    assert result.sub_gaps[1].description == "Implement user model"


def test_parse_create_game_output_decompose_requires_non_empty_sub_gaps() -> None:
    import baps.run as run_module
    import pytest

    text = json.dumps({
        "decompose": True,
        "rationale": "Too large",
        "sub_gaps": [],
    })
    with pytest.raises(ValueError, match="non-empty list"):
        run_module._parse_create_game_output(text)


def test_parse_create_game_output_decompose_requires_rationale() -> None:
    import baps.run as run_module
    import pytest

    text = json.dumps({
        "decompose": True,
        "rationale": "",
        "sub_gaps": [{"description": "x"}],
    })
    with pytest.raises(ValueError, match="rationale must be non-empty"):
        run_module._parse_create_game_output(text)


def test_parse_create_game_output_truncates_sub_gaps_when_over_max() -> None:
    import baps.run as run_module

    sub_gaps = [{"description": f"Gap {i}"} for i in range(7)]
    text = json.dumps({"decompose": True, "rationale": "Too large", "sub_gaps": sub_gaps})
    result = run_module._parse_create_game_output(text, max_sub_gaps=5)
    assert isinstance(result, run_module.DecomposeSpec)
    assert len(result.sub_gaps) == 5
    assert result.sub_gaps[0].description == "Gap 0"
    assert result.sub_gaps[4].description == "Gap 4"


def test_parse_create_game_output_does_not_truncate_at_exactly_max() -> None:
    import baps.run as run_module

    sub_gaps = [{"description": f"Gap {i}"} for i in range(5)]
    text = json.dumps({"decompose": True, "rationale": "Decomposing", "sub_gaps": sub_gaps})
    result = run_module._parse_create_game_output(text, max_sub_gaps=5)
    assert isinstance(result, run_module.DecomposeSpec)
    assert len(result.sub_gaps) == 5


def test_parse_create_game_output_max_sub_gaps_1_allows_only_one() -> None:
    import baps.run as run_module

    sub_gaps = [{"description": "First"}, {"description": "Second"}]
    text = json.dumps({"decompose": True, "rationale": "Big gap", "sub_gaps": sub_gaps})
    result = run_module._parse_create_game_output(text, max_sub_gaps=1)
    assert isinstance(result, run_module.DecomposeSpec)
    assert len(result.sub_gaps) == 1
    assert result.sub_gaps[0].description == "First"


def test_parse_create_game_output_strips_empty_sub_gaps_and_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import baps.run as run_module

    sub_gaps = [
        {"description": "write the API"},
        {"description": ""},
        {"description": "   "},
    ]
    text = json.dumps({"decompose": True, "rationale": "gap is large", "sub_gaps": sub_gaps})
    with caplog.at_level(logging.WARNING):
        result = run_module._parse_create_game_output(text, max_sub_gaps=5)
    assert isinstance(result, run_module.DecomposeSpec)
    assert len(result.sub_gaps) == 1
    assert result.sub_gaps[0].description == "write the API"
    assert "stripped 2 sub-gap(s) with empty description" in caplog.text


def test_parse_create_game_output_all_empty_sub_gaps_no_fallback_raises() -> None:
    import baps.run as run_module

    text = json.dumps({
        "decompose": True,
        "rationale": "gap is large",
        "sub_gaps": [{"description": ""}, {"description": "   "}],
    })
    with pytest.raises(ValueError, match="no valid entries"):
        run_module._parse_create_game_output(text, max_sub_gaps=5)


def test_parse_create_game_output_all_empty_sub_gaps_with_fallback_escalates() -> None:
    import baps.run as run_module

    valid_decompose = json.dumps({
        "decompose": True,
        "rationale": "gap is large",
        "sub_gaps": [{"description": "write the implementation"}],
    })
    fallback_calls: list[str] = []

    def fallback_fn(prompt: str) -> str:
        fallback_calls.append(prompt)
        return valid_decompose

    text = json.dumps({
        "decompose": True,
        "rationale": "gap is large",
        "sub_gaps": [{"description": ""}, {"description": "   "}],
    })
    result = run_module._parse_create_game_output(text, max_sub_gaps=5, fallback_fn=fallback_fn)
    assert isinstance(result, run_module.DecomposeSpec)
    assert len(result.sub_gaps) == 1
    assert result.sub_gaps[0].description == "write the implementation"
    assert len(fallback_calls) == 1


def test_parse_create_game_output_unrecognizable_shape_no_fallback_raises() -> None:
    import baps.run as run_module

    text = json.dumps({"something_unexpected": "value"})
    with pytest.raises(ValueError, match="must contain exactly keys"):
        run_module._parse_create_game_output(text, max_sub_gaps=5)


def test_parse_create_game_output_unrecognizable_shape_with_fallback_escalates() -> None:
    import baps.run as run_module

    valid_game_spec = json.dumps({
        "objective": "Close the gap",
        "target_artifact_id": "main-document",
        "allowed_delta_type": "DeltaDocumentState",
        "success_condition": "section present",
    })
    fallback_calls: list[str] = []

    def fallback_fn(prompt: str) -> str:
        fallback_calls.append(prompt)
        return valid_game_spec

    text = json.dumps({"something_unexpected": "value"})
    result = run_module._parse_create_game_output(text, max_sub_gaps=5, fallback_fn=fallback_fn)
    assert isinstance(result, run_module.GameSpec)
    assert result.target_artifact_id == "main-document"
    assert len(fallback_calls) == 1


def test_parse_create_game_output_unrecognizable_shape_fallback_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import baps.run as run_module

    valid_game_spec = json.dumps({
        "objective": "Close the gap",
        "target_artifact_id": "main-document",
        "allowed_delta_type": "DeltaDocumentState",
        "success_condition": "section present",
    })

    def fallback_fn(prompt: str) -> str:
        return valid_game_spec

    text = json.dumps({"something_unexpected": "value"})
    with caplog.at_level(logging.WARNING):
        run_module._parse_create_game_output(text, max_sub_gaps=5, fallback_fn=fallback_fn)
    assert "unrecognizable response shape" in caplog.text


def test_parse_create_game_output_empty_dict_with_fallback_escalates() -> None:
    import baps.run as run_module

    valid_game_spec = json.dumps({
        "objective": "Close the gap",
        "target_artifact_id": "main-document",
        "allowed_delta_type": "DeltaDocumentState",
        "success_condition": "section present",
    })
    fallback_calls: list[str] = []

    def fallback_fn(prompt: str) -> str:
        fallback_calls.append(prompt)
        return valid_game_spec

    # Empty dict: all keys stripped as unexpected, leaving nothing
    text = json.dumps({})
    result = run_module._parse_create_game_output(text, max_sub_gaps=5, fallback_fn=fallback_fn)
    assert isinstance(result, run_module.GameSpec)
    assert len(fallback_calls) == 1


def test_parse_create_game_output_game_spec_with_false_marker_keys_and_extra_keys() -> None:
    import baps.run as run_module
    from baps.state import GameSpec

    # Local models (e.g. qwen2.5-coder) often include false-valued marker keys and
    # extra metadata like confidence in what is intended to be a GameSpec response.
    raw = json.dumps({
        "objective": "Add introduction section",
        "target_artifact_id": "doc-main",
        "allowed_delta_type": "append_section",
        "success_condition": "Introduction section present",
        "no_new_game": False,
        "decompose": False,
        "confidence": 0.95,
    })
    result = run_module._parse_create_game_output(raw)
    assert isinstance(result, GameSpec)
    assert result.objective == "Add introduction section"


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


def test_create_game_prompt_includes_context_chain_when_provided() -> None:
    import baps.run as run_module

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "northstar_markdown": "# Goal\n\nWrite a report.",
        "goal": "Write a report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = run_module.create_state(config)
    adapter = DocumentProjectAdapter()
    state_view = adapter.build_create_game_state_view(state, config)
    prompt = run_module._render_create_game_prompt(
        config, state, state_view, adapter=adapter,
        context_chain=("Implement auth subsystem", "Implement JWT token generation"),
    )
    assert "Parent planning context" in prompt
    assert "[1] Implement auth subsystem" in prompt
    assert "[2] Implement JWT token generation" in prompt
    assert "[current] Plan within this scope" in prompt


def test_create_game_prompt_no_context_block_when_chain_empty() -> None:
    import baps.run as run_module

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "artifact_id": "main-document",
        "northstar_markdown": "# Goal\n\nWrite a report.",
        "goal": "Write a report.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = run_module.create_state(config)
    adapter = DocumentProjectAdapter()
    state_view = adapter.build_create_game_state_view(state, config)
    prompt = run_module._render_create_game_prompt(
        config, state, state_view, adapter=adapter,
    )
    assert "Parent planning context" not in prompt
    assert "[current]" not in prompt


def test_blue_prompt_includes_context_chain_from_game_spec() -> None:
    from baps.project_adapter import render_blue_prompt_core
    from baps.state import GameSpec
    from baps.northstar_projection import StateView, ProjectionType

    game_spec = GameSpec(
        objective="Write jwt_utils.py",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="jwt_utils.py exists",
        context_chain=("Auth subsystem missing", "JWT generation missing"),
    )
    state_view = StateView(
        id="sv-1",
        projection_type=ProjectionType.NORTH_STAR,
        content="=== StateView Start ===\ncontent\n=== StateView End ===",
        input_fingerprint="fp-1",
    )
    prompt = render_blue_prompt_core(state_view, game_spec, 1, None)
    assert "Planning context (coarsest → finest scope):" in prompt
    assert "[1] Auth subsystem missing" in prompt
    assert "[2] JWT generation missing" in prompt


def test_blue_prompt_no_context_block_when_chain_empty() -> None:
    from baps.project_adapter import render_blue_prompt_core
    from baps.state import GameSpec
    from baps.northstar_projection import StateView, ProjectionType

    game_spec = GameSpec(
        objective="Write something",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="file exists",
    )
    state_view = StateView(
        id="sv-1",
        projection_type=ProjectionType.NORTH_STAR,
        content="=== StateView Start ===\ncontent\n=== StateView End ===",
        input_fingerprint="fp-1",
    )
    prompt = render_blue_prompt_core(state_view, game_spec, 1, None)
    assert "Planning context" not in prompt


def test_solve_gap_decompose_then_play(monkeypatch, tmp_path: Path) -> None:
    """Decompose at depth 0 → two sub-games played at depth 1, then no_new_game."""
    import baps.run as run_module
    import baps.state as state_module

    played: list[str] = []
    top_calls = [0]

    def _fake_create_game(config, state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        if not context_chain:
            top_calls[0] += 1
            if top_calls[0] > 1:
                raise run_module.NoNewGameError("all gaps closed")
            return run_module.DecomposeSpec(
                rationale="Too large",
                sub_gaps=(
                    run_module.SubGapSpec(description="Sub-gap A"),
                    run_module.SubGapSpec(description="Sub-gap B"),
                ),
            )
        # leaf — return a game spec for each sub-gap
        return run_module.GameSpec(
            objective=f"Do {context_chain[-1]}",
            target_artifact_id="main-document",
            allowed_delta_type="DeltaDocumentState",
            success_condition="done",
        )

    def _fake_play_game(state, game_spec, adapter=None, **kwargs):
        played.append(game_spec.objective)
        return state_module.DeltaDocumentState(
            artifact_id="main-document",
            operation="append_section",
            payload=state_module.AppendSectionDelta(
                section=state_module.Section(title=game_spec.objective, body="body"),
            ),
        )

    monkeypatch.setattr("baps.orchestration.create_game", _fake_create_game)
    monkeypatch.setattr("baps.orchestration.play_game", _fake_play_game)

    config = {
        "workspace": tmp_path / "ws",
        "project_type": "document",
        "artifact_id": "main-document",
        "northstar_markdown": "# Goal",
        "goal": "Write something",
        "output_path": tmp_path / "ws" / "output" / "report.md",
        "max_iterations": 10,
        "max_depth": 2,
        "spec_path": None,
    }
    service, state = run_module._initialize_project(config)
    adapter = DocumentProjectAdapter()

    result = run_module._run_project_iterations(config, adapter, service, state)

    assert len(played) == 2
    assert "Sub-gap A" in played[0]
    assert "Sub-gap B" in played[1]
    assert result["iterations_completed"] == 2


def test_solve_gap_context_chain_injected_into_game_spec(monkeypatch, tmp_path: Path) -> None:
    """The context chain accumulated through decomposition reaches Blue's GameSpec."""
    import baps.run as run_module
    import baps.state as state_module

    captured_chain: list[tuple[str, ...]] = []
    top_calls = [0]

    def _fake_create_game(config, state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        if not context_chain:
            top_calls[0] += 1
            if top_calls[0] > 1:
                raise run_module.NoNewGameError("done")
            return run_module.DecomposeSpec(
                rationale="Top level too large",
                sub_gaps=(run_module.SubGapSpec(description="Level-1 gap"),),
            )
        return run_module.GameSpec(
            objective="Leaf game",
            target_artifact_id="main-document",
            allowed_delta_type="DeltaDocumentState",
            success_condition="done",
        )

    def _fake_play_game(state, game_spec, adapter=None, **kwargs):
        captured_chain.append(game_spec.context_chain)
        return state_module.DeltaDocumentState(
            artifact_id="main-document",
            operation="append_section",
            payload=state_module.AppendSectionDelta(
                section=state_module.Section(title="Leaf game", body="body"),
            ),
        )

    monkeypatch.setattr("baps.orchestration.create_game", _fake_create_game)
    monkeypatch.setattr("baps.orchestration.play_game", _fake_play_game)

    config = {
        "workspace": tmp_path / "ws",
        "project_type": "document",
        "artifact_id": "main-document",
        "northstar_markdown": "# Goal",
        "goal": "Write something",
        "output_path": tmp_path / "ws" / "output" / "report.md",
        "max_iterations": 5,
        "max_depth": 3,
        "spec_path": None,
    }
    service, state = run_module._initialize_project(config)
    adapter = DocumentProjectAdapter()
    run_module._run_project_iterations(config, adapter, service, state)

    assert len(captured_chain) == 1
    assert captured_chain[0] == ("Level-1 gap",)


def test_solve_gap_max_depth_stops_recursion(monkeypatch, tmp_path: Path) -> None:
    """Decompose always → max_depth_reached stop reason."""
    import baps.run as run_module

    def _always_decompose(config, state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        return run_module.DecomposeSpec(
            rationale="Always decompose",
            sub_gaps=(run_module.SubGapSpec(description="inner"),),
        )

    monkeypatch.setattr("baps.orchestration.create_game", _always_decompose)

    config = {
        "workspace": tmp_path / "ws",
        "project_type": "document",
        "artifact_id": "main-document",
        "northstar_markdown": "# Goal",
        "goal": "Write something",
        "output_path": tmp_path / "ws" / "output" / "report.md",
        "max_iterations": 5,
        "max_depth": 2,
        "spec_path": None,
    }
    service, state = run_module._initialize_project(config)
    adapter = DocumentProjectAdapter()
    result = run_module._run_project_iterations(config, adapter, service, state)

    assert result["stop_reason"] == "max_depth_reached"
    assert result["iterations_completed"] == 0


# ---------------------------------------------------------------------------
# Phase 3: _parse_pytest_failures
# ---------------------------------------------------------------------------

def test_parse_pytest_failures_empty_stdout() -> None:
    from baps.language_python import _parse_pytest_failures
    assert _parse_pytest_failures("") == []


def test_parse_pytest_failures_no_failures() -> None:
    from baps.language_python import _parse_pytest_failures
    stdout = "collected 3 items\n\n3 passed in 0.1s\n"
    assert _parse_pytest_failures(stdout) == []


def test_parse_pytest_failures_single_failure_with_reason() -> None:
    from baps.language_python import _parse_pytest_failures
    stdout = "FAILED tests/test_foo.py::test_bar - AssertionError: expected 1 got 2\n"
    result = _parse_pytest_failures(stdout)
    assert result == [{"test_id": "tests/test_foo.py::test_bar", "reason": "AssertionError: expected 1 got 2"}]


def test_parse_pytest_failures_multiple_failures() -> None:
    from baps.language_python import _parse_pytest_failures
    stdout = (
        "FAILED tests/test_a.py::test_one - AssertionError: wrong\n"
        "FAILED tests/test_b.py::test_two - TypeError: bad type\n"
    )
    result = _parse_pytest_failures(stdout)
    assert len(result) == 2
    assert result[0]["test_id"] == "tests/test_a.py::test_one"
    assert result[1]["test_id"] == "tests/test_b.py::test_two"


def test_parse_pytest_failures_no_reason_separator() -> None:
    from baps.language_python import _parse_pytest_failures
    stdout = "FAILED tests/test_foo.py::test_bar\n"
    result = _parse_pytest_failures(stdout)
    assert result == [{"test_id": "tests/test_foo.py::test_bar", "reason": ""}]


def test_truncate_lines_short_text_unchanged() -> None:
    from baps.coding_adapter import _truncate_lines
    text = "line1\nline2\nline3"
    assert _truncate_lines(text, max_lines=5) == text


def test_truncate_lines_truncates_at_limit() -> None:
    from baps.coding_adapter import _truncate_lines
    text = "\n".join(f"line{i}" for i in range(10))
    result = _truncate_lines(text, max_lines=3)
    assert result.startswith("line0\nline1\nline2")
    assert "7 more lines" in result


# ---------------------------------------------------------------------------
# Phase 1: Blue receives prior export verification in its initial prompt
# ---------------------------------------------------------------------------

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
    game_spec = run_module.GameSpec(
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
    game_spec = run_module.GameSpec(
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

    vr = run_module.VerificationResult(
        command="uv run pytest", cwd="/tmp", exit_code=1,
        stdout="FAILED tests/test_foo.py::test_x - AssertionError\n",
        stderr="", passed=False,
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(id="main-codebase", files=()),),
    )
    game_spec = run_module.GameSpec(
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
    game_spec = run_module.GameSpec(
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

def test_create_game_writes_create_game_blackboard_event(tmp_path: Path) -> None:
    config = {
        "workspace": tmp_path / "ws-cg-bb",
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": tmp_path / "ws-cg-bb" / "output" / "report.md",
        "max_iterations": 1,
        "spec_path": None,
    }
    state = create_state(config)
    create_game(
        config,
        state,
        model_client=FakeModelClient([
            '{"objective":"Close the gap","target_artifact_id":"main-document",'
            '"allowed_delta_type":"DeltaDocumentState",'
            '"success_condition":"Section present."}'
        ]),
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
    config = {
        "workspace": tmp_path / "ws-nng-bb",
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": tmp_path / "ws-nng-bb" / "output" / "report.md",
        "max_iterations": 1,
        "spec_path": None,
    }
    state = create_state(config)
    import baps.run as run_module
    with pytest.raises(run_module.NoNewGameError):
        create_game(
            config,
            state,
            model_client=FakeModelClient(['{"no_new_game": true, "reason": "All gaps closed."}']),
        )

    games_path = config["workspace"] / "blackboard" / "games.jsonl"
    assert games_path.exists()
    entry = json.loads(games_path.read_text(encoding="utf-8").strip())
    assert entry["event"] == "create_game"
    assert entry["result_type"] == "no_new_game"
    assert entry["result"] is None
    assert "created_at" in entry


def test_create_game_writes_decompose_spec_event(tmp_path: Path) -> None:
    config = {
        "workspace": tmp_path / "ws-dc-bb",
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a long report.",
        "northstar_markdown": "# Goal\n\nWrite a long report.",
        "output_path": tmp_path / "ws-dc-bb" / "output" / "report.md",
        "max_iterations": 1,
        "spec_path": None,
    }
    state = create_state(config)
    create_game(
        config,
        state,
        model_client=FakeModelClient([
            '{"decompose": true, "rationale": "Too large", '
            '"sub_gaps": [{"description": "Part one"}, {"description": "Part two"}]}'
        ]),
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
    config = {
        "workspace": workspace,
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": workspace / "output" / "report.md",
        "max_iterations": 1,
        "spec_path": None,
    }
    state = create_state(config)
    game_spec = _real_run.GameSpec(
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


def test_integration_writes_integration_blackboard_event(
    monkeypatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-int-bb"
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
            "--max-iterations", "1",
        ],
    )
    from baps.run import main as run_main
    run_main()

    games_path = workspace / "blackboard" / "games.jsonl"
    assert games_path.exists(), "games.jsonl must exist after a successful run"

    lines = [json.loads(l) for l in games_path.read_text(encoding="utf-8").strip().splitlines()]
    integration_events = [e for e in lines if e["event"] == "integration"]
    assert len(integration_events) >= 1, "at least one integration event must be written"

    evt = integration_events[0]
    assert "created_at" in evt
    assert "depth" in evt
    assert "proposal_id" in evt
    assert evt["proposal_id"] != ""
    assert "proposal_summary" in evt
    assert isinstance(evt["state_changed"], bool)
    assert "delta_type" in evt
    assert evt["delta_type"] != ""


# ---------------------------------------------------------------------------
# play_game blackboard — final_disposition branches
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


def _make_document_game_spec(**kwargs) -> "_real_run.GameSpec":
    return _real_run.GameSpec(
        objective="Add introduction section",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Introduction section must be present.",
        **kwargs,
    )


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
            tool_responses=[ToolCall("append_section", {"artifact_id": "main-document", "title": "Intro", "body": ""})]
        ),
        max_attempts=1,
    )

    entry = json.loads(
        (workspace / "blackboard" / "games.jsonl").read_text(encoding="utf-8").strip()
    )
    assert entry["final_disposition"] == "no_delta"
    assert all(r["blue_delta"] is None for r in entry["attempts"])


# ---------------------------------------------------------------------------
# depth and context_chain captured in create_game and play_game events
# ---------------------------------------------------------------------------

def test_create_game_blackboard_captures_depth_and_context_chain(tmp_path: Path) -> None:
    config = {
        "workspace": tmp_path / "ws-cg-depth",
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a report.",
        "northstar_markdown": "# Goal\n\nWrite a report.",
        "output_path": tmp_path / "ws-cg-depth" / "output" / "report.md",
        "max_iterations": 1,
        "spec_path": None,
    }
    state = create_state(config)
    chain = ("Top-level gap", "Sub-level concern")
    create_game(
        config,
        state,
        depth=2,
        context_chain=chain,
        model_client=FakeModelClient([
            '{"objective":"Close the gap","target_artifact_id":"main-document",'
            '"allowed_delta_type":"DeltaDocumentState",'
            '"success_condition":"Section present."}'
        ]),
    )

    entry = json.loads(
        (config["workspace"] / "blackboard" / "games.jsonl").read_text(encoding="utf-8").strip()
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


# ---------------------------------------------------------------------------
# Verification summary truncation — blackboard truncates, source is unchanged
# ---------------------------------------------------------------------------

def test_blackboard_verification_summary_truncated_to_cap(
    tmp_path: Path, monkeypatch
) -> None:
    import baps.run as run_module

    long_stdout = "O" * 700
    long_stderr = "E" * 600
    mock_vr = run_module.VerificationResult(
        command="pytest", cwd="/tmp", exit_code=0,
        stdout=long_stdout, stderr=long_stderr, passed=True,
    )
    monkeypatch.setattr("baps.game._verify_candidate_with_adapter", lambda *a, **kw: mock_vr)

    workspace = tmp_path / "ws-trunc"
    config = _make_play_game_config(workspace)
    state = create_state(config)
    play_game(state, _make_document_game_spec(), config=config)

    entry = json.loads(
        (workspace / "blackboard" / "games.jsonl").read_text(encoding="utf-8").strip()
    )
    cap = run_module._VERIFICATION_SUMMARY_CAP
    vr_summary = entry["verification_result"]
    assert vr_summary["stdout_summary"] == "O" * cap
    assert vr_summary["stderr_summary"] == "E" * cap
    assert len(vr_summary["stdout_summary"]) == cap
    assert len(vr_summary["stderr_summary"]) == cap

    attempt_vr = entry["attempts"][0]["candidate_verification"]
    assert attempt_vr["stdout_summary"] == "O" * cap
    assert attempt_vr["stderr_summary"] == "E" * cap

    # Original VerificationResult object is not mutated
    assert mock_vr.stdout == long_stdout
    assert mock_vr.stderr == long_stderr


def test_blackboard_verification_feedback_loop_uses_full_text(
    tmp_path: Path, monkeypatch
) -> None:
    """When candidate verification fails and Blue retries, the full stdout/stderr
    must appear in Blue's next prompt — only the blackboard summary is truncated."""
    import baps.run as run_module

    long_stdout = "F" * 700
    failing_vr = run_module.VerificationResult(
        command="pytest", cwd="/tmp", exit_code=1,
        stdout=long_stdout, stderr="", passed=False,
    )
    passing_vr = run_module.VerificationResult(
        command="pytest", cwd="/tmp", exit_code=0,
        stdout="ok", stderr="", passed=True,
    )
    call_count = {"n": 0}

    def _mock_verify(*a, **kw):
        call_count["n"] += 1
        return failing_vr if call_count["n"] == 1 else passing_vr

    monkeypatch.setattr("baps.game._verify_candidate_with_adapter", _mock_verify)

    workspace = tmp_path / "ws-feedbackloop"
    config = _make_play_game_config(workspace)
    state = create_state(config)
    blue_client = FakeModelClient(
        tool_responses=[
            ToolCall("append_section", {"artifact_id": "main-document", "title": "Intro", "body": "first"}),
            ToolCall("append_section", {"artifact_id": "main-document", "title": "Intro2", "body": "second"}),
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


# ---------------------------------------------------------------------------
# integration event — explicit field value verification
# ---------------------------------------------------------------------------

def test_integration_event_all_required_fields_with_correct_types(
    monkeypatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "ws-int-fields"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run", "start",
            "--workspace", str(workspace),
            "--project-type", "document",
            "--artifact-id", "main-document",
            "--goal", "Write a short report.",
            "--output", "output/report.md",
            "--max-iterations", "1",
        ],
    )
    from baps.run import main as run_main
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


# ---------------------------------------------------------------------------
# create_game no_new_game blackboard event — with failing verification context
# ---------------------------------------------------------------------------

def test_create_game_blackboard_no_new_game_with_failing_verification(
    tmp_path: Path,
) -> None:
    """create_game writes result_type=no_new_game even when a failing verification
    result is in context. Runtime-level rejection of no_new_game happens in
    _solve_gap, not inside create_game; the blackboard must faithfully record
    what the model actually returned."""
    import baps.run as run_module

    config = {
        "workspace": tmp_path / "ws-nng-vr",
        "project_type": "document",
        "artifact_id": "main-document",
        "goal": "Write a short report.",
        "northstar_markdown": "# Goal\n\nWrite a short report.",
        "output_path": tmp_path / "ws-nng-vr" / "output" / "report.md",
        "max_iterations": 1,
        "spec_path": None,
    }
    state = create_state(config)
    failing_vr = run_module.VerificationResult(
        command="pytest", cwd="/tmp", exit_code=1,
        stdout="FAILED tests/test_foo.py::test_bar", stderr="", passed=False,
    )

    with pytest.raises(run_module.NoNewGameError):
        create_game(
            config,
            state,
            verification_result=failing_vr,
            model_client=FakeModelClient(
                ['{"no_new_game": true, "reason": "No gap identified."}']
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
