import argparse
import inspect
from pathlib import Path

import pytest

from baps.models import FakeModelClient
from baps.run import create_game, create_state, main, play_game


@pytest.fixture(autouse=True)
def _patch_create_game_model_client(monkeypatch):
    create_game_response = (
        '{"objective":"Advance goal","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}'
    )
    blue_response = (
        '{"artifact_id":"main-document","operation":"append_section",'
        '"payload":{"section":{"title":"Introduction","body":"Advance goal"}}}'
    )
    red_response = '{"disposition":"accept","rationale":"deterministic test path"}'
    referee_response = '{"disposition":"accept","rationale":"deterministic test path"}'

    def _fake_create_game_builder():
        return FakeModelClient([create_game_response])

    def _fake_blue_builder():
        return FakeModelClient([blue_response])

    def _fake_red_builder():
        return FakeModelClient([red_response])

    def _fake_referee_builder():
        return FakeModelClient([referee_response])

    monkeypatch.setattr("baps.run._build_create_game_model_client", _fake_create_game_builder)
    monkeypatch.setattr("baps.run._build_blue_model_client", _fake_blue_builder)
    monkeypatch.setattr("baps.run._build_red_model_client", _fake_red_builder)
    monkeypatch.setattr("baps.run._build_referee_model_client", _fake_referee_builder)


def test_main_prints_required_fields_and_no_legacy_iteration_output(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    workspace = tmp_path / "w"
    monkeypatch.setattr(
        "sys.argv",
        ["baps-run", "--workspace", str(workspace), "--project-type", "document", "--artifact-id", "main-document"],
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

    monkeypatch.setattr("sys.argv", ["baps-run", "--spec", str(spec)])
    main()
    out = capsys.readouterr().out

    assert f"workspace={workspace}" in out
    assert "project_type=document" in out
    assert "goal=Spec goal" in out
    assert f"output_path={workspace / 'out/spec-report.md'}" in out
    assert "max_iterations=3" in out


def test_main_document_spec_without_artifact_id_fails_cleanly(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    spec = tmp_path / "config-missing-artifact.yaml"
    spec.write_text(
        "\n".join(
            [
                "project_type: document",
                "goal: Spec goal",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("sys.argv", ["baps-run", "--spec", str(spec)])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "artifact_id must be non-empty" in err


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
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id", "main-document", "--output",
            str(absolute_output),
        ],
    )

    main()
    out = capsys.readouterr().out
    assert f"output_path={absolute_output}" in out


@pytest.mark.parametrize(
    ("argv", "error_substring"),
    [
        (["baps-run", "--project-type", "document", "--artifact-id", "main-document", "--max-iterations", "0"], "max_iterations must be >= 1"),
        (["baps-run"], "project_type must be non-empty"),
        (["baps-run", "--project-type", "document", "--artifact-id", "main-document", "--goal", "   "], "goal must be non-empty"),
        (["baps-run", "--project-type", "document", "--artifact-id", "main-document", "--workspace", "   "], "workspace must be non-empty"),
        (["baps-run", "--project-type", "document", "--artifact-id", "main-document", "--output", "   "], "output must be non-empty"),
    ],
)
def test_invalid_config_fails_cleanly(monkeypatch, capsys, argv: list[str], error_substring: str) -> None:
    monkeypatch.setattr("sys.argv", argv)
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert error_substring in err


@pytest.mark.parametrize(
    ("argv", "error_substring"),
    [
        (["baps-run", "--project-type", "git"], "project_type 'git' is not implemented"),
        (["baps-run", "--project-type", "unknown"], "unknown project_type: unknown"),
    ],
)
def test_invalid_project_type_fails_cleanly(
    monkeypatch, capsys, argv: list[str], error_substring: str
) -> None:
    monkeypatch.setattr("sys.argv", argv)
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert error_substring in err


def test_project_type_document_creates_state_and_logs_when_debug_enabled(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    workspace = tmp_path / "debug-doc-ws"
    monkeypatch.setenv("BAPS_DEBUG", "1")
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
        "--artifact-id", "main-document", ],
    )

    main()
    out = capsys.readouterr().out
    assert "[DEBUG] create_state.input:" in out
    assert "  project_type: document" in out
    assert "[DEBUG] create_state.output:" in out
    assert "[DEBUG] create_game.input:" in out
    assert "[DEBUG] create_game.output:" in out
    assert "  state:" in out
    assert "    northstar:" in out
    assert "    artifacts:" in out
    assert "      - id: main-document" in out
    assert "        kind: document" in out
    assert "        sections: []" in out


def test_document_type_is_not_stored_in_state_output(monkeypatch, capsys, tmp_path: Path) -> None:
    workspace = tmp_path / "doc-ws"
    monkeypatch.setenv("BAPS_DEBUG", "1")
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
        "--artifact-id", "main-document", ],
    )

    main()
    out = capsys.readouterr().out
    create_state_block = out.split("[DEBUG] create_state.output:")[1].split("\n\n", 1)[0]
    assert "project_type" not in create_state_block


def test_create_state_output_flows_into_create_game(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "flow-ws"
    import baps.run as run_module

    captured: dict[str, object] = {}
    original_create_game = run_module.create_game

    def _capturing_create_game(config, state, adapter=None):
        captured.setdefault("state", state)
        return original_create_game(config, state, adapter=adapter)

    monkeypatch.setattr(run_module, "create_game", _capturing_create_game)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
        "--artifact-id", "main-document", ],
    )

    run_module.main()

    forwarded_state = captured.get("state")
    assert forwarded_state is not None
    assert forwarded_state.model_dump(mode="json") == {
        "northstar": {
            "artifacts": [
                {
                    "id": forwarded_state.northstar.artifacts[0].id,
                    "kind": "document",
                    "sections": [
                        {"title": "NorthStar", "body": "Write a short report."}
                    ],
                }
            ]
        },
        "artifacts": [{"id": "main-document", "kind": "document", "sections": []}],
    }


def test_derive_state_update_from_delta_converts_append_section() -> None:
    import baps.run as run_module

    delta = run_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=run_module.AppendSectionDelta(
            section=run_module.Section(title="Introduction", body="Body text")
        ),
    )
    proposal = run_module._derive_state_update_from_delta(
        delta, adapter=run_module.DocumentProjectAdapter()
    )
    assert proposal.target.artifact_id == "main-document"
    assert proposal.payload["operation"] == "append_section"
    assert proposal.payload["section"] == {
        "title": "Introduction",
        "body": "Body text",
    }


def test_main_integration_uses_state_service_apply_update(monkeypatch, tmp_path: Path) -> None:
    import baps.run as run_module

    called = {"value": False}
    original_apply = run_module.StateService.apply_update

    def _capture_apply(self, proposal):
        called["value"] = True
        return original_apply(self, proposal)

    monkeypatch.setattr(run_module.StateService, "apply_update", _capture_apply)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "--workspace",
            str(tmp_path / "ws-service"),
            "--project-type",
            "document",
        "--artifact-id", "main-document", ],
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
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
        "--artifact-id", "main-document", ],
    )
    run_module.main()

    persisted = run_module.JsonStateStore(workspace / "state" / "state.json").load()
    doc = next(a for a in persisted.artifacts if a.id == "main-document")
    assert isinstance(doc, run_module.DocumentArtifact)
    assert len(doc.sections) == 2
    assert doc.sections[0].title == "Introduction"
    assert doc.sections[0].body == "Advance goal"


def test_main_unsupported_delta_operation_fails_explicitly(monkeypatch, capsys, tmp_path: Path) -> None:
    import baps.run as run_module

    monkeypatch.setattr(
        run_module,
        "play_game",
        lambda _state, _spec, adapter=None: run_module.DeltaDocumentState.model_construct(
            artifact_id="main-document",
            operation="unsupported_operation",
            payload=run_module.AppendSectionDelta(
                section=run_module.Section(title="Introduction", body="body")
            ),
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "--workspace",
            str(tmp_path / "ws-unsupported-op"),
            "--project-type",
            "document",
        "--artifact-id", "main-document", ],
    )
    with pytest.raises(SystemExit) as exc:
        run_module.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "unsupported delta operation for integration" in err


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
    with pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient(["not-json"]))


def test_create_game_invalid_json_with_debug_prints_raw_model_output(
    monkeypatch, capsys
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
    monkeypatch.setenv("BAPS_DEBUG", "1")

    with pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient(["not-json-output"]))
    out = capsys.readouterr().out
    assert "[DEBUG] create_game.prompt:" in out
    assert "[DEBUG] create_game.raw_model_output:" in out
    assert "  not-json-output" in out


def test_create_game_invalid_json_without_debug_does_not_print_raw_model_output(capsys) -> None:
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

    with pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient(["not-json-output"]))
    out = capsys.readouterr().out
    assert "[DEBUG] create_game.prompt:" not in out
    assert "[DEBUG] create_game.raw_model_output:" not in out


def test_create_game_atomicity_failure_debug_prints_raw_output_before_failure(
    monkeypatch, capsys
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
    monkeypatch.setenv("BAPS_DEBUG", "1")
    payload = (
        '{"objective":"Add introduction and conclusion","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"Add introduction and conclusion"}'
    )
    with pytest.raises(ValueError, match="one coherent task"):
        create_game(config, state, model_client=FakeModelClient([payload]))
    out = capsys.readouterr().out
    assert "[DEBUG] create_game.prompt:" in out
    assert "[DEBUG] create_game.raw_model_output:" in out
    assert "[DEBUG] create_game.validation_input:" in out
    assert "[DEBUG] create_game.validation_analysis:" in out
    assert "[DEBUG] create_game.validation_failure:" in out
    assert "message=create_game model output must describe one coherent task in objective" in out
    assert payload in out


def test_create_game_validation_input_debug_enabled(monkeypatch, capsys) -> None:
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
    monkeypatch.setenv("BAPS_DEBUG", "1")

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
    out = capsys.readouterr().out
    assert "[DEBUG] create_game.validation_input:" in out
    assert "objective=Advance report objective" in out
    assert "success_condition=PlayGame must return a valid DeltaDocumentState targeting main-document." in out
    assert "target_artifact_id=main-document" in out
    assert "allowed_delta_type=DeltaDocumentState" in out


def test_create_game_semantic_refinement_objective_is_accepted(monkeypatch, capsys) -> None:
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
    monkeypatch.setenv("BAPS_DEBUG", "1")

    game_spec = create_game(
        config,
        state,
        model_client=FakeModelClient(
            [
                '{"objective":"Add Introduction section to artifact main-document, introducing bounded adversarial evaluation and its relevance to software project improvement.",'
                '"target_artifact_id":"main-document",'
                '"allowed_delta_type":"DeltaDocumentState",'
                '"success_condition":"Artifact contains an Introduction section introducing bounded adversarial evaluation and its relevance to software project improvement."}'
            ]
        ),
    )
    assert game_spec.target_artifact_id == "main-document"
    out = capsys.readouterr().out
    assert "independent_tasks=False" in out
    assert "reason=semantic refinement of single coherent task" in out


def test_create_game_rejects_independent_task_verb_bundle() -> None:
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
    with pytest.raises(ValueError, match="one coherent task"):
        create_game(
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


def test_create_game_validation_debug_disabled_prints_nothing(capsys) -> None:
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
    out = capsys.readouterr().out
    assert "[DEBUG] create_game.validation_input:" not in out
    assert "[DEBUG] create_game.validation_analysis:" not in out
    assert "[DEBUG] create_game.validation_failure:" not in out


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


def test_create_game_prose_before_fence_rejected() -> None:
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
    with pytest.raises(ValueError, match="must be valid JSON"):
        create_game(
            config,
            state,
            model_client=FakeModelClient(
                [
                    "Here is the result:\n```json\n"
                    '{"objective":"Advance report objective","target_artifact_id":"main-document",'
                    '"allowed_delta_type":"DeltaDocumentState",'
                    '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}\n'
                    "```"
                ]
            ),
        )


def test_create_game_prose_after_fence_rejected() -> None:
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
    with pytest.raises(ValueError, match="must be valid JSON"):
        create_game(
            config,
            state,
            model_client=FakeModelClient(
                [
                    "```json\n"
                    '{"objective":"Advance report objective","target_artifact_id":"main-document",'
                    '"allowed_delta_type":"DeltaDocumentState",'
                    '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}\n'
                    "```\nDone."
                ]
            ),
        )


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
    with pytest.raises(ValueError, match="must be valid JSON"):
        create_game(
            config,
            state,
            model_client=FakeModelClient(
                [
                    "```json\n"
                    '{"objective":"Advance report objective","target_artifact_id":"main-document",'
                    '"allowed_delta_type":"DeltaDocumentState",'
                    '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}\n'
                    "```\n```json\n{}\n```"
                ]
            ),
        )


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
    with pytest.raises(ValueError, match="must be valid JSON"):
        create_game(
            config,
            state,
            model_client=FakeModelClient(["```json\n{not valid json}\n```"]),
        )


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
    prompt = run_module._render_create_game_prompt(config, state)

    assert "Return only a JSON object" in prompt
    assert "Do not wrap output in markdown" in prompt
    assert "Do not use triple-backtick fences" in prompt
    assert '"objective"' in prompt
    assert '"target_artifact_id"' in prompt
    assert '"allowed_delta_type"' in prompt
    assert '"success_condition"' in prompt
    assert "GameSpec should represent one coherent task" in prompt
    assert "structural change, local content intent, and semantic purpose may coexist" in prompt
    assert "reject only when multiple independent tasks/features are bundled." in prompt
    assert "VALID: Add Introduction section introducing bounded adversarial evaluation." in prompt
    assert "VALID: Add Conclusion section summarizing the report findings." in prompt
    assert "INVALID: Add Introduction and Conclusion sections." in prompt


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


def test_create_game_rejects_bundled_objective_and_success_condition() -> None:
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
    with pytest.raises(ValueError, match="one coherent task"):
        create_game(
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


def test_create_game_rejects_broad_multi_feature_gamespec() -> None:
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
    with pytest.raises(ValueError, match="one coherent task"):
        create_game(
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


def test_play_game_valid_blue_json_returns_delta() -> None:
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
            [
                '{"artifact_id":"main-document","operation":"append_section",'
                '"payload":{"section":{"title":"Introduction","body":"Any objective"}}}'
            ]
        ),
    )
    assert delta is not None
    assert delta.model_dump(mode="json")["artifact_id"] == "main-document"


def test_play_game_invalid_blue_json_rejected() -> None:
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
        model_client=FakeModelClient(["not-json"]),
        max_attempts=1,
    )
    assert delta is None


def test_play_game_fenced_blue_json_accepted() -> None:
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
            [
                "```json\n"
                '{"artifact_id":"main-document","operation":"append_section",'
                '"payload":{"section":{"title":"Introduction","body":"Any objective"}}}\n'
                "```"
            ]
        ),
    )
    assert delta is not None
    assert delta.model_dump(mode="json")["operation"] == "append_section"


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
    with pytest.raises(ValueError, match="red model output must be valid JSON"):
        play_game(
            state,
            spec,
            model_client=FakeModelClient(
                [
                    '{"artifact_id":"main-document","operation":"append_section",'
                    '"payload":{"section":{"title":"Introduction","body":"Any objective"}}}'
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
    with pytest.raises(ValueError, match="referee model output must be valid JSON"):
        play_game(
            state,
            spec,
            model_client=FakeModelClient(
                [
                    '{"artifact_id":"main-document","operation":"append_section",'
                    '"payload":{"section":{"title":"Introduction","body":"Any objective"}}}'
                ]
            ),
            red_model_client=FakeModelClient(
                ['{"disposition":"accept","rationale":"deterministic test path"}']
            ),
            referee_model_client=FakeModelClient(["not-json"]),
        )


def test_play_game_referee_receives_gamespec_state_view_delta_and_red(monkeypatch) -> None:
    import baps.run as run_module

    captured: dict[str, object] = {}

    def _capture_referee_input(state_view, game_spec, delta_state, red_finding):
        captured["state_view"] = state_view
        captured["game_spec"] = game_spec
        captured["delta_state"] = delta_state
        captured["red_finding"] = red_finding

    monkeypatch.setattr(run_module, "_debug_print_referee_input", _capture_referee_input)
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


def test_play_game_referee_revise_prevents_current_best_delta() -> None:
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
            [
                '{"artifact_id":"main-document","operation":"append_section",'
                '"payload":{"section":{"title":"Introduction","body":"Any objective"}}}'
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
    assert delta is None


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
            [
                '{"artifact_id":"main-document","operation":"append_section",'
                '"payload":{"section":{"title":"Introduction","body":"Any objective"}}}'
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

    monkeypatch.setattr(run_module, "_debug_print_red_input", _capture_red_input)
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


def test_blue_prompt_includes_state_view_and_gamespec() -> None:
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
    state_view = run_module._build_document_state_view(state, spec)
    prompt = run_module._render_blue_prompt(
        state_view=state_view,
        game_spec=spec,
        attempt_number=1,
        previous_feedback=None,
    )
    assert "state_view_json:" in prompt
    assert "attempt_number: 1" in prompt
    assert "previous_feedback_json: null" in prompt
    assert "objective:" in prompt
    assert "target_artifact_id:" in prompt
    assert "allowed_delta_type:" in prompt
    assert "success_condition:" in prompt
    assert "section.title and section.body must be non-empty strings." in prompt
    assert (
        "If previous_feedback_json contains validation errors, repair those exact errors in this attempt."
        in prompt
    )
    assert "Do not repeat outputs that fail previously reported validation constraints." in prompt
    assert (
        "When attempt_number > 1, treat previous_feedback_json as mandatory correction requirements."
        in prompt
    )
    assert 'Invalid example, do not output: "body": ""' in prompt
    assert '"artifact_id": "<game_spec.target_artifact_id>"' in prompt
    assert (
        '"body": "Concrete non-empty section body text."'
        in prompt
    )
    assert '"body": "...' not in prompt
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
    state_view = run_module._build_document_state_view(state, spec)
    delta = run_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=run_module.AppendSectionDelta(
            section=run_module.Section(title="Introduction", body="Intro only")
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
        northstar=run_module.NorthStar(artifacts=()),
        artifacts=(
            run_module.DocumentArtifact(
                id="main-document",
                sections=(
                    run_module.Section(title="Introduction", body="Intro"),
                    run_module.Section(title="Conclusion", body="Outro"),
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


def test_create_game_explicit_no_new_atomic_game_signal() -> None:
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
    with pytest.raises(run_module.NoNewAtomicGameError):
        run_module.create_game(
            config,
            state,
            model_client=FakeModelClient(
                ['{"no_new_atomic_game": true, "reason": "all required sections already present"}']
            ),
        )


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
    state_view = run_module._build_create_game_state_view(state, config["artifact_id"])
    prompt = run_module._render_create_game_prompt(config, state)
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
    assert "Use StateView NorthStar section as authoritative context." in prompt
    assert "Derive the next coherent game task from projected state context, including NorthStar intent." in prompt
    assert "GameSpec must be self-contained for PlayGame execution without independently reading full NorthStar." in prompt
    assert "The objective must describe BOTH:" in prompt
    assert "1. structural change" in prompt
    assert "2. substantive local intent" in prompt
    assert "Do not emit objectives that only describe structure." in prompt
    assert "The GameSpec must contain enough local intent so PlayGame can execute without reading NorthStar." in prompt
    assert "Fold relevant NorthStar intent into objective and success_condition." in prompt
    assert "Avoid purely structural objectives when NorthStar contains substantive intent." in prompt
    assert "BAD objective: Add Introduction section." in prompt
    assert (
        "GOOD objective: Add Introduction section introducing bounded adversarial evaluation and its role in improving software projects."
        in prompt
    )
    assert "BAD success_condition: document contains Introduction." in prompt
    assert (
        "GOOD success_condition: artifact contains an Introduction section explaining bounded adversarial evaluation and framing the report purpose."
        in prompt
    )
    assert '{\"no_new_atomic_game\": true, \"reason\": \"...\"}' in prompt
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


def test_required_sections_top_level_is_rejected_in_config(monkeypatch, capsys, tmp_path: Path) -> None:
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
    monkeypatch.setattr("sys.argv", ["baps-run", "--spec", str(spec)])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "required_sections is no longer supported" in capsys.readouterr().err


def test_blue_prompt_and_source_do_not_hardcode_project_policy_literals() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Add Overview section",
        target_artifact_id="doc-a",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Overview section exists.",
    )
    state = run_module.State(
        northstar=run_module.NorthStar(artifacts=()),
        artifacts=(run_module.DocumentArtifact(id="doc-a", sections=()),),
    )
    state_view = run_module._build_document_state_view(state, spec)
    prompt = run_module._render_blue_prompt(state_view, spec, 1, None)
    assert '"artifact_id": "<game_spec.target_artifact_id>"' in prompt
    assert '"title": "<section title>"' in prompt
    src = inspect.getsource(run_module._render_blue_prompt)
    assert '"artifact_id": "main-document"' not in src
    assert '"title": "Introduction"' not in src


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
    state_view = run_module._build_document_state_view(state, spec)
    delta = run_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=run_module.AppendSectionDelta(
            section=run_module.Section(
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
    state_view = run_module._build_document_state_view(state, spec)
    delta = run_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=run_module.AppendSectionDelta(
            section=run_module.Section(title="Introduction", body="Body")
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
    state_view = run_module._build_document_state_view(state, spec)
    delta = run_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=run_module.AppendSectionDelta(
            section=run_module.Section(title="Introduction", body="Body")
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
    state_view = run_module._build_document_state_view(state, spec)
    delta = run_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=run_module.AppendSectionDelta(
            section=run_module.Section(title="Introduction", body="Body")
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


def test_state_view_is_derived_from_state_and_gamespec_with_existing_sections() -> None:
    import baps.run as run_module

    spec = run_module.GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
    )
    state = run_module.State(
        northstar=run_module.NorthStar(artifacts=()),
        artifacts=(
            run_module.DocumentArtifact(
                id="main-document",
                sections=(run_module.Section(title="Existing", body="Already here"),),
            ),
        ),
    )
    state_view = run_module._build_document_state_view(state, spec)
    assert state_view.metadata["target_artifact_id"] == "main-document"
    assert state_view.metadata["sections"] == [{"title": "Existing", "body": "Already here"}]


def test_create_game_state_view_content_is_markdown_for_empty_document() -> None:
    import baps.run as run_module

    state = run_module.State(
        northstar=run_module.NorthStar(
            artifacts=(
                run_module.DocumentArtifact(
                    id="northstar:abc",
                    sections=(
                        run_module.Section(
                            title="NorthStar",
                            body="# Goal\n\nWrite a short report about bounded adversarial evaluation.",
                        ),
                    ),
                ),
            )
        ),
        artifacts=(run_module.DocumentArtifact(id="main-document", sections=()),),
    )

    state_view = run_module._build_create_game_state_view(state, "main-document")
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
        northstar=run_module.NorthStar(
            artifacts=(
                run_module.DocumentArtifact(
                    id="northstar:def",
                    sections=(
                        run_module.Section(
                            title="NorthStar",
                            body="# Goal\n\nWrite a short report about bounded adversarial evaluation.",
                        ),
                    ),
                ),
            )
        ),
        artifacts=(
            run_module.DocumentArtifact(
                id="main-document",
                sections=(run_module.Section(title="Introduction", body="Intro body text."),),
            ),
        ),
    )

    state_view = run_module._build_create_game_state_view(state, "main-document")
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
        [
            '{"artifact_id":"main-document","operation":"append_section",'
            '"payload":{"section":{"title":"Introduction","body":"first"}}}',
            '{"artifact_id":"main-document","operation":"append_section",'
            '"payload":{"section":{"title":"Introduction","body":"second"}}}',
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
    assert len(blue_client.prompts) == 1
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
        [
            '{"artifact_id":"main-document","operation":"append_section",'
            '"payload":{"section":{"title":"Introduction","body":"first"}}}',
            '{"artifact_id":"main-document","operation":"append_section",'
            '"payload":{"section":{"title":"Introduction","body":"second"}}}',
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
    assert len(blue_client.prompts) == 2


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
        [
            '{"artifact_id":"main-document","operation":"append_section",'
            '"payload":{"section":{"title":"Introduction","body":"first"}}}',
            '{"artifact_id":"main-document","operation":"append_section",'
            '"payload":{"section":{"title":"Introduction","body":"second"}}}',
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
    assert len(blue_client.prompts) == 2


def test_play_game_attempts_exhausted_returns_none() -> None:
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
            [
                '{"artifact_id":"main-document","operation":"append_section",'
                '"payload":{"section":{"title":"Introduction","body":"first"}}}',
                '{"artifact_id":"main-document","operation":"append_section",'
                '"payload":{"section":{"title":"Introduction","body":"second"}}}',
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
    assert delta is None


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
        [
            '{"artifact_id":"main-document","operation":"append_section",'
            '"payload":{"section":{"title":"Introduction","body":"first"}}}',
            '{"artifact_id":"main-document","operation":"append_section",'
            '"payload":{"section":{"title":"Introduction","body":"second"}}}',
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
    assert len(blue_client.prompts) == 2
    second_prompt = blue_client.prompts[1]
    assert "previous_feedback_json:" in second_prompt
    assert (
        "When attempt_number > 1, treat previous_feedback_json as mandatory correction requirements."
        in second_prompt
    )
    assert (
        "If previous_feedback_json contains validation errors, repair those exact errors in this attempt."
        in second_prompt
    )
    assert '"red_finding": {"disposition": "accept", "rationale": "ok"}' in second_prompt
    assert (
        '"referee_decision": {"disposition": "revise", "rationale": "needs revision"}'
        in second_prompt
    )


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
        [
            '{"artifact_id":"main-document","operation":"append_section",'
            '"payload":{"section":{"title":"Introduction","body":""}}}',
            '{"artifact_id":"main-document","operation":"append_section",'
            '"payload":{"section":{"title":"Introduction","body":"second"}}}',
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
    assert len(blue_client.prompts) == 2
    second_prompt = blue_client.prompts[1]
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
            [
                '{"artifact_id":"main-document","operation":"append_section",'
                '"payload":{"section":{"title":"Introduction","body":""}}}',
                '{"artifact_id":"main-document","operation":"append_section",'
                '"payload":{"section":{"title":"Introduction","body":""}}}',
            ]
        ),
        max_attempts=2,
    )
    assert delta is None


def test_play_game_invalid_blue_debug_and_non_debug_output(monkeypatch, capsys) -> None:
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

    _ = play_game(
        state,
        spec,
        model_client=FakeModelClient(
            ['{"artifact_id":"main-document","operation":"append_section","payload":{"section":{"title":"Introduction","body":""}}}']
        ),
        max_attempts=1,
    )
    non_debug_out = capsys.readouterr().out
    assert "[DEBUG] blue.raw_model_output:" not in non_debug_out

    monkeypatch.setenv("BAPS_DEBUG", "1")
    _ = play_game(
        state,
        spec,
        model_client=FakeModelClient(
            ['{"artifact_id":"main-document","operation":"append_section","payload":{"section":{"title":"Introduction","body":""}}}']
        ),
        max_attempts=1,
    )
    debug_out = capsys.readouterr().out
    assert "[DEBUG] blue.raw_model_output:" in debug_out
    assert "[DEBUG] play_game.attempt_rejected:" in debug_out
    assert "reason: blue output failed DeltaState validation:" in debug_out
    assert "payload.section.body" in debug_out
    assert "must be a non-empty string" in debug_out


def test_runtime_preserves_accepted_delta_after_later_reject_in_helper_flow() -> None:
    import baps.run as run_module

    first_delta = run_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=run_module.AppendSectionDelta(
            section=run_module.Section(title="Introduction", body="first")
        ),
    )
    second_delta = run_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=run_module.AppendSectionDelta(
            section=run_module.Section(title="Introduction", body="second")
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


def test_play_game_debug_logs_appear(monkeypatch, capsys) -> None:
    import baps.run as run_module

    monkeypatch.setenv("BAPS_DEBUG", "1")
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
    _ = play_game(state, spec)
    out = capsys.readouterr().out
    assert "[DEBUG] blue.input:" in out
    assert "[DEBUG] blue.output:" in out
    assert "[DEBUG] red.input:" in out
    assert "[DEBUG] red.output:" in out
    assert "[DEBUG] referee.input:" in out
    assert "[DEBUG] referee.output:" in out
    assert "[DEBUG] play_game.input:" in out
    assert "[DEBUG] play_game.attempt:" in out
    assert "[DEBUG] play_game.output:" in out
    assert "  attempt: 1" in out
    blue_input_block = out.split("[DEBUG] blue.input:")[1].split("[DEBUG] blue.output:")[0]
    assert "state_view:" in blue_input_block
    assert "target_artifact_id: main-document" in blue_input_block
    assert "sections: []" in blue_input_block
    assert "state:" not in blue_input_block
    assert "game_spec:" in blue_input_block
    assert "attempt_number: 1" in blue_input_block
    assert "previous_feedback: None" in blue_input_block
    red_input_block = out.split("[DEBUG] red.input:")[1].split("[DEBUG] red.output:")[0]
    assert "game_spec:" in red_input_block
    assert "state_view:" in red_input_block
    assert "delta_state:" in red_input_block
    assert "artifact_id: main-document" in red_input_block
    assert "red_finding:" in out
    referee_input_block = out.split("[DEBUG] referee.input:")[1].split("[DEBUG] referee.output:")[0]
    assert "game_spec:" in referee_input_block
    assert "state_view:" in referee_input_block
    assert "delta_state:" in referee_input_block
    assert "red_finding:" in referee_input_block
    assert "referee_decision:" in out
    assert "current_best_delta:" in out


def test_main_calls_play_game_with_gamespec_from_create_game(monkeypatch, tmp_path: Path) -> None:
    import baps.run as run_module

    captured: dict[str, object] = {}
    expected = run_module.GameSpec(
        objective="O",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="S",
    )

    monkeypatch.setattr(run_module, "create_game", lambda config, state, adapter=None: expected)

    def _capture_play_game(state, spec, adapter=None):
        captured["state"] = state
        captured["spec"] = spec
        return run_module.DeltaDocumentState(
            artifact_id=spec.target_artifact_id,
            operation="append_section",
            payload=run_module.AppendSectionDelta(
                section=run_module.Section(title="Introduction", body=spec.objective)
            ),
        )

    monkeypatch.setattr(run_module, "play_game", _capture_play_game)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "--workspace",
            str(tmp_path / "ws-main-play"),
            "--project-type",
            "document",
        "--artifact-id", "main-document", ],
    )

    run_module.main()

    assert captured["spec"] is expected
    assert captured["state"] is not None


def test_main_exits_cleanly_if_play_game_returns_none(monkeypatch, capsys, tmp_path: Path) -> None:
    import baps.run as run_module

    monkeypatch.setattr(run_module, "play_game", lambda _state, _spec, adapter=None: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "--workspace",
            str(tmp_path / "ws-play-none"),
            "--project-type",
            "document",
        "--artifact-id", "main-document", ],
    )
    run_module.main()
    captured = capsys.readouterr()
    assert "error: play_game produced no DeltaState" not in captured.err
    assert "update_applied=False" in captured.out
    assert "state_changed=False" in captured.out
    assert "stop_reason=play_game_no_delta" in captured.out


def test_main_max_iterations_two_runs_two_iterations_with_state_carry_forward(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    import baps.run as run_module

    create_game_seen_sections: list[list[str]] = []

    def _create_game(config, state, adapter=None):
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

    def _play_game(_state, spec, adapter=None):
        title = "Introduction" if "introduction" in spec.objective.lower() else "Conclusion"
        return run_module.DeltaDocumentState(
            artifact_id="main-document",
            operation="append_section",
            payload=run_module.AppendSectionDelta(
                section=run_module.Section(title=title, body=f"{title} body")
            ),
        )

    monkeypatch.setattr(run_module, "create_game", _create_game)
    monkeypatch.setattr(run_module, "play_game", _play_game)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "--workspace",
            str(tmp_path / "ws-multi-iter"),
            "--project-type",
            "document",
            "--artifact-id", "main-document", "--max-iterations",
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
            "--workspace",
            str(tmp_path / "ws-create-once"),
            "--project-type",
            "document",
            "--artifact-id", "main-document", "--max-iterations",
            "2",
        ],
    )

    run_module.main()
    assert calls["count"] == 1


def test_main_stops_when_create_game_cannot_produce_new_atomic_game(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    import baps.run as run_module

    calls = {"count": 0}

    def _create_game(_config, _state, adapter=None):
        calls["count"] += 1
        if calls["count"] == 1:
            return run_module.GameSpec(
                objective="Add introduction section",
                target_artifact_id="main-document",
                allowed_delta_type="DeltaDocumentState",
                success_condition="Introduction section exists",
            )
        raise run_module.NoNewAtomicGameError("no further atomic game")

    monkeypatch.setattr(run_module, "create_game", _create_game)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "--workspace",
            str(tmp_path / "ws-stop-no-game"),
            "--project-type",
            "document",
            "--artifact-id", "main-document", "--max-iterations",
            "3",
        ],
    )

    run_module.main()
    out = capsys.readouterr().out
    assert "stop_reason=create_game_no_new_atomic_game" in out


def test_main_create_game_parse_error_is_not_swallowed_as_no_game(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    import baps.run as run_module

    def _broken_create_game(_config, _state, adapter=None):
        raise ValueError("create_game model output must be valid JSON")

    monkeypatch.setattr(run_module, "create_game", _broken_create_game)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "--workspace",
            str(tmp_path / "ws-create-game-error"),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
            "--max-iterations",
            "2",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        run_module.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "create_game model output must be valid JSON" in err


def test_init_and_run_clean_workspace_creates_report_from_spec(
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
        ["baps-run", "init_and_run", "--spec", str(spec)],
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
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
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

    adapter = run_module.DocumentProjectAdapter()
    state = run_module.State(
        northstar=run_module.NorthStar(artifacts=()),
        artifacts=(
            run_module.DocumentArtifact(
                id="main-document",
                sections=(
                    run_module.Section(title="Introduction", body="Intro body"),
                    run_module.Section(title="Conclusion", body="Conclusion body"),
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

    adapter = run_module.DocumentProjectAdapter()
    state = run_module.State(
        northstar=run_module.NorthStar(artifacts=()),
        artifacts=(run_module.DocumentArtifact(id="main-document", sections=()),),
    )
    output_path = tmp_path / "a" / "b" / "c" / "report.md"
    adapter.export_state(state, output_path, "main-document")
    assert output_path.parent.exists()


def test_document_export_output_changed_false_when_unchanged(tmp_path: Path) -> None:
    import baps.run as run_module

    adapter = run_module.DocumentProjectAdapter()
    state = run_module.State(
        northstar=run_module.NorthStar(artifacts=()),
        artifacts=(
            run_module.DocumentArtifact(
                id="main-document",
                sections=(run_module.Section(title="Intro", body="Body"),),
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

    main_src = inspect.getsource(run_module.main)
    assert "output_path.write_text" not in main_src
    assert "run_baps_loop(" not in main_src
    adapter_src = inspect.getsource(run_module.DocumentProjectAdapter.export_state)
    assert "write_text" in adapter_src


def test_baps_init_creates_state_file(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "ws-init"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "init",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
        ],
    )
    main()
    assert (workspace / "state" / "state.json").exists()


def test_baps_init_twice_fails(monkeypatch, tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "ws-init-twice"
    argv = [
        "baps-run",
        "init",
        "--workspace",
        str(workspace),
        "--project-type",
        "document",
        "--artifact-id",
        "main-document",
    ]
    monkeypatch.setattr("sys.argv", argv)
    main()
    monkeypatch.setattr("sys.argv", argv)
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "project already initialized" in capsys.readouterr().err


def test_baps_run_before_init_fails(monkeypatch, tmp_path: Path, capsys) -> None:
    workspace = tmp_path / "ws-run-before-init"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "run",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "project state not initialized" in capsys.readouterr().err


def test_baps_run_loads_existing_state_without_create_state(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.run as run_module

    workspace = tmp_path / "ws-run-load"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "init",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
        ],
    )
    main()

    monkeypatch.setattr(
        run_module,
        "create_state",
        lambda _config: (_ for _ in ()).throw(AssertionError("create_state should not be called for run")),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "run",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
            "--max-iterations",
            "1",
        ],
    )
    main()


def test_baps_init_and_run_works_once(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "ws-init-and-run"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "init_and_run",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
            "--max-iterations",
            "1",
        ],
    )
    main()
    assert (workspace / "state" / "state.json").exists()
    assert (workspace / "output" / "report.md").exists()


def test_baps_init_and_run_after_initialization_fails(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    workspace = tmp_path / "ws-init-and-run-fails"
    argv = [
        "baps-run",
        "init_and_run",
        "--workspace",
        str(workspace),
        "--project-type",
        "document",
        "--artifact-id",
        "main-document",
        "--max-iterations",
        "1",
    ]
    monkeypatch.setattr("sys.argv", argv)
    main()
    monkeypatch.setattr("sys.argv", argv)
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "project already initialized" in capsys.readouterr().err


def test_second_run_sees_previous_state(monkeypatch, tmp_path: Path) -> None:
    import baps.run as run_module

    workspace = tmp_path / "ws-second-run-state"
    seen_titles: list[list[str]] = []

    def _create_game(config, state, adapter=None):
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

    def _play_game(_state, spec, adapter=None):
        title = "Introduction" if "introduction" in spec.objective.lower() else "Conclusion"
        return run_module.DeltaDocumentState(
            artifact_id="main-document",
            operation="append_section",
            payload=run_module.AppendSectionDelta(
                section=run_module.Section(title=title, body=f"{title} body")
            ),
        )

    monkeypatch.setattr(run_module, "create_game", _create_game)
    monkeypatch.setattr(run_module, "play_game", _play_game)

    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "init",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
        ],
    )
    main()

    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "run",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
            "--max-iterations",
            "1",
        ],
    )
    main()
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "run",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
            "--max-iterations",
            "1",
        ],
    )
    main()
    assert seen_titles[0] == []
    assert seen_titles[1] == ["Introduction"]


def test_export_works_after_run_command(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "ws-export-after-run"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "init",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
        ],
    )
    main()
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "run",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
            "--max-iterations",
            "1",
        ],
    )
    main()
    assert (workspace / "output" / "report.md").exists()


def test_spec_relative_path_resolves_from_cwd(monkeypatch, capsys, tmp_path: Path) -> None:
    spec = tmp_path / "config.yaml"
    workspace = tmp_path / "from-relative-spec"
    spec.write_text(
        "project_type: document\nartifact_id: main-document\n" f"workspace: {workspace}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["baps-run", "--spec", "config.yaml"])

    main()
    out = capsys.readouterr().out
    assert f"workspace={workspace}" in out


def test_debug_enabled_prints_read_config_input_output(monkeypatch, capsys, tmp_path: Path) -> None:
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

    monkeypatch.setenv("BAPS_DEBUG", "1")
    monkeypatch.setattr("sys.argv", ["baps-run", "--spec", str(spec)])

    main()
    out = capsys.readouterr().out

    assert "[DEBUG] read_config.input:" in out
    assert "  cli_args:" in out
    assert "  yaml_values:" in out
    assert f"    workspace: {workspace}" in out
    assert "    goal: Debug spec goal" in out
    assert "    output: out/debug.md" in out
    assert "    max_iterations: 2" in out
    assert "[DEBUG] read_config.output:" in out
    assert f"  workspace: {workspace}" in out
    assert "  artifact_id: main-document" in out
    assert "  goal: Debug spec goal" in out
    assert f"  output_path: {workspace / 'out/debug.md'}" in out
    assert "  max_iterations: 2" in out
    assert "{'cli_args':" not in out


def test_examples_document_project_yaml_still_passes(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["baps-run", "run", "--spec", "examples/document-project.yaml"])
    main()
    out = capsys.readouterr().out
    assert "project_type=document" in out
    assert "stop_reason=" in out


def test_init_from_spec_persists_northstar_artifact(monkeypatch, tmp_path: Path) -> None:
    import baps.run as run_module

    workspace = tmp_path / "ws-init-northstar"
    spec = tmp_path / "config.yaml"
    spec.write_text(
        "\n".join(
            [
                "project_type: document",
                "artifact_id: main-document",
                f"workspace: {workspace}",
                "northstar_markdown: |",
                "  # Goal",
                "",
                "  Write a short report grounded in NorthStar intent.",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("sys.argv", ["baps-run", "init", "--spec", str(spec)])
    run_module.main()

    persisted = run_module.JsonStateStore(workspace / "state" / "state.json").load()
    assert len(persisted.northstar.artifacts) == 1
    northstar_artifact = persisted.northstar.artifacts[0]
    assert northstar_artifact.kind == "document"
    assert northstar_artifact.id.startswith("northstar:")
    assert isinstance(northstar_artifact, run_module.DocumentArtifact)
    assert len(northstar_artifact.sections) == 1
    assert northstar_artifact.sections[0].body == (
        "# Goal\n\nWrite a short report grounded in NorthStar intent."
    )


def test_debug_formatter_renders_nested_list_of_dicts_without_python_repr(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    workspace = tmp_path / "debug-structure-ws"
    monkeypatch.setenv("BAPS_DEBUG", "1")
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
        ],
    )

    main()
    out = capsys.readouterr().out
    assert "artifacts: [{'id':" not in out
    assert "artifacts:\n      - id: main-document" in out
    assert "sections: []" in out


def test_debug_formatter_renders_tuple_as_yaml_list_and_empty_as_brackets(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    workspace = tmp_path / "debug-tuple-ws"
    monkeypatch.setenv("BAPS_DEBUG", "1")
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
        ],
    )

    main()
    out = capsys.readouterr().out
    assert "northstar:\n      artifacts:\n        - id: northstar:" in out
    assert "sections: []" in out


def test_main_uses_project_type_adapter_dispatch_for_document(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.run as run_module

    class _RecordingAdapter:
        project_type = "document"
        supported_delta_type = "DeltaDocumentState"

        def __init__(self) -> None:
            self.calls: list[str] = []
            self._delegate = run_module.DocumentProjectAdapter()

        def create_initial_state(self, config):
            self.calls.append("create_initial_state")
            return self._delegate.create_initial_state(config)

        def build_state_view(self, state, game_spec):
            self.calls.append("build_state_view")
            return self._delegate.build_state_view(state, game_spec)

        def render_blue_prompt(self, state_view, game_spec, attempt_number, previous_feedback):
            self.calls.append("render_blue_prompt")
            return self._delegate.render_blue_prompt(
                state_view, game_spec, attempt_number, previous_feedback
            )

        def parse_blue_delta(self, text):
            self.calls.append("parse_blue_delta")
            return self._delegate.parse_blue_delta(text)

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
            "--workspace",
            str(tmp_path / "ws-adapter-dispatch"),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
            "--max-iterations",
            "1",
        ],
    )
    run_module.main()
    assert "create_initial_state" in adapter.calls
    assert "build_state_view" in adapter.calls
    assert "render_blue_prompt" in adapter.calls
    assert "parse_blue_delta" in adapter.calls
    assert "delta_to_state_update" in adapter.calls
    assert "export_state" in adapter.calls


def test_play_game_uses_adapter_provided_state_view_prompt_and_parser() -> None:
    import baps.run as run_module

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

        def parse_blue_delta(self, _text):
            self.calls.append("parse_blue_delta")
            return run_module.DeltaDocumentState(
                artifact_id="main-document",
                operation="append_section",
                payload=run_module.AppendSectionDelta(
                    section=run_module.Section(title="Intro", body="Body")
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
        northstar=run_module.NorthStar(artifacts=()),
        artifacts=(run_module.DocumentArtifact(id="main-document", sections=()),),
    )
    delta = run_module.play_game(
        state,
        spec,
        adapter=adapter,
        model_client=FakeModelClient(["ignored"]),
        red_model_client=FakeModelClient(['{"disposition":"accept","rationale":"ok"}']),
        referee_model_client=FakeModelClient(['{"disposition":"accept","rationale":"ok"}']),
    )
    assert isinstance(delta, run_module.DeltaDocumentState)
    assert adapter.calls == ["build_state_view", "render_blue_prompt", "parse_blue_delta"]


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
                target=run_module.StateUpdateTarget(artifact_id=delta_state.artifact_id),
                summary="mapped",
                payload={
                    "operation": "replace_artifact",
                    "artifact": {"id": delta_state.artifact_id, "kind": "document"},
                },
            )

    delta = run_module.DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=run_module.AppendSectionDelta(
            section=run_module.Section(title="T", body="B")
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


def test_active_main_and_play_game_orchestration_have_no_direct_document_mechanics() -> None:
    import baps.run as run_module

    main_src = inspect.getsource(run_module.main)
    play_src = inspect.getsource(run_module.play_game)
    for token in ("DocumentArtifact", "DeltaDocumentState", "append_section", "sections"):
        assert token not in main_src
        assert token not in play_src
