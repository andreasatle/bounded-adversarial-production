from pathlib import Path

import pytest

from baps.run import SECTION_MARKER, main, run_baps_loop


def test_run_baps_loop_creates_report_and_appends_once(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"

    result = run_baps_loop(workspace)

    output_path = workspace / "output" / "report.md"
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert content.count(SECTION_MARKER) == 1

    first, second = result["iterations"]
    assert first["iteration"] == 1
    assert first["update_applied"] is True
    assert first["document_changed"] is True
    assert second["iteration"] == 2
    assert second["update_applied"] is False
    assert second["document_changed"] is False
    assert second["stop_reason"] == "section_already_exists"


def test_run_baps_loop_preserves_existing_content(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    output_path = workspace / "output" / "report.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("# Existing Header\n\n", encoding="utf-8")

    run_baps_loop(workspace)

    content = output_path.read_text(encoding="utf-8")
    assert content.startswith("# Existing Header\n\n")
    assert content.count(SECTION_MARKER) == 1


def test_run_baps_loop_writes_only_under_workspace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    workspace = tmp_path / "custom-workspace"

    run_baps_loop(workspace)

    assert (workspace / "output" / "report.md").exists()
    assert not Path("state/demo-state.json").exists()


def test_main_prints_required_loop_fields(monkeypatch, capsys, tmp_path: Path) -> None:
    workspace = tmp_path / "w"
    monkeypatch.setattr(
        "sys.argv",
        ["baps-run", "--workspace", str(workspace), "--project-type", "document"],
    )

    main()
    out = capsys.readouterr().out

    assert f"workspace={workspace}" in out
    assert "project_type=document" in out
    assert "goal=Write a short report with an introduction and conclusion." in out
    assert f"output_path={workspace / 'output' / 'report.md'}" in out
    assert "max_iterations=2" in out
    assert "iteration=1" in out
    assert "iteration=2" in out
    assert "state_derived=True" in out
    assert "view_built=True" in out
    assert f"proposal={SECTION_MARKER}" in out
    assert "game_result=accepted" in out
    assert "decision=accepted_append_only" in out
    assert "update_applied=True" in out
    assert "document_changed=True" in out
    assert "stop_reason=section_already_exists" in out
    assert "[DEBUG]" not in out


def test_duplicate_detection_uses_authoritative_document_not_view_content(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "ws"
    import baps.run as run_module

    original_build_input = run_module._build_input

    def _misleading_build_input(iteration: int, current_document: str, goal: str):
        input_obj = original_build_input(iteration=iteration, current_document=current_document, goal=goal)
        if iteration == 2:
            input_obj.northstar_view = input_obj.northstar_view.model_copy(
                update={
                    "content": "Request:\nWrite a short report with an introduction and conclusion.\n\nCurrent report tail:\n"
                }
            )
        return input_obj

    monkeypatch.setattr(run_module, "_build_input", _misleading_build_input)

    run_module.run_baps_loop(workspace)

    content = (workspace / "output" / "report.md").read_text(encoding="utf-8")
    assert content.count(SECTION_MARKER) == 1


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
            "--goal",
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


def test_main_cli_overrides_yaml(monkeypatch, capsys, tmp_path: Path) -> None:
    spec = tmp_path / "config.yaml"
    spec.write_text(
        "\n".join(
            [
                "workspace: from-spec",
                "project_type: document",
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
            "--goal",
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
            "--output",
            str(absolute_output),
        ],
    )

    main()
    out = capsys.readouterr().out
    assert f"output_path={absolute_output}" in out


@pytest.mark.parametrize(
    ("argv", "error_substring"),
    [
        (["baps-run", "--project-type", "document", "--max-iterations", "0"], "max_iterations must be >= 1"),
        (["baps-run"], "project_type must be non-empty"),
        (["baps-run", "--project-type", "document", "--goal", "   "], "goal must be non-empty"),
        (["baps-run", "--project-type", "document", "--workspace", "   "], "workspace must be non-empty"),
        (["baps-run", "--project-type", "document", "--output", "   "], "output must be non-empty"),
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
        ],
    )

    main()
    out = capsys.readouterr().out
    assert "[DEBUG] create_state.input:" in out
    assert "  project_type: document" in out
    assert "[DEBUG] create_state.output:" in out
    assert "[DEBUG] create_game.input:" in out
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
        ],
    )

    main()
    out = capsys.readouterr().out
    create_state_block = out.split("[DEBUG] create_state.output:")[1].split("\n\n", 1)[0]
    assert "project_type" not in create_state_block


def test_create_state_output_flows_into_next_stage(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "flow-ws"
    import baps.run as run_module

    captured: dict[str, object] = {}
    original_run_baps_loop = run_module.run_baps_loop

    def _capturing_run_baps_loop(*args, **kwargs):
        captured["state"] = kwargs.get("state")
        return original_run_baps_loop(*args, **kwargs)

    monkeypatch.setattr(run_module, "run_baps_loop", _capturing_run_baps_loop)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
        ],
    )

    run_module.main()

    forwarded_state = captured.get("state")
    assert forwarded_state is not None
    assert forwarded_state.model_dump(mode="json") == {
        "northstar": {"artifacts": []},
        "artifacts": [{"id": "main-document", "kind": "document", "sections": []}],
    }


def test_spec_relative_path_resolves_from_cwd(monkeypatch, capsys, tmp_path: Path) -> None:
    spec = tmp_path / "config.yaml"
    workspace = tmp_path / "from-relative-spec"
    spec.write_text("project_type: document\n" f"workspace: {workspace}\n", encoding="utf-8")
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
    assert "  goal: Debug spec goal" in out
    assert f"  output_path: {workspace / 'out/debug.md'}" in out
    assert "  max_iterations: 2" in out
    assert "{'cli_args':" not in out


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
        ],
    )

    main()
    out = capsys.readouterr().out
    assert "northstar:\n      artifacts: []" in out
    assert "sections: []" in out
