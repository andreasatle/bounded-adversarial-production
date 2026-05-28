import json
import logging
from pathlib import Path

import pytest

from baps.core.run import main
import baps.state.state as state_module


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
    import baps.core.run as run_module

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

    monkeypatch.setattr("baps.core.clients._build_model_client", _fail)
    monkeypatch.setattr("baps.core.clients._build_planner_model_client", _fail)
    monkeypatch.setattr("baps.core.clients._build_role_client", _fail)
    monkeypatch.setattr("baps.core.clients._build_client_for_role", _fail)

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
        return state_module.GameSpec(
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

    monkeypatch.setattr("baps.core.orchestration.create_game", _create_game)
    monkeypatch.setattr("baps.core.orchestration.play_game", _play_game)

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
    import baps.core.run as run_module

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
    import baps.core.run as run_module

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


def test_init_from_spec_persists_northstar_in_workspace_config(monkeypatch, tmp_path: Path) -> None:
    import baps.core.run as run_module

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
