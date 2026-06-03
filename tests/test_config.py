import argparse
import logging
from pathlib import Path

import pytest

from baps.core.run import main


def test_main_cli_config_resolves_and_prints(
    monkeypatch, capsys, tmp_path: Path
) -> None:
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
            "--artifact-id",
            "main-document",
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


def test_main_yaml_spec_resolves_and_prints(
    monkeypatch, capsys, tmp_path: Path
) -> None:
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
            "--artifact-id",
            "main-document",
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


def test_output_path_absolute_remains_absolute(
    monkeypatch, capsys, tmp_path: Path
) -> None:
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
            "--artifact-id",
            "main-document",
            "--goal",
            "Write a report.",
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
        (
            [
                "baps-run",
                "start",
                "--project-type",
                "document",
                "--artifact-id",
                "main-document",
                "--goal",
                "Write a report.",
                "--output",
                "output/report.md",
                "--max-iterations",
                "0",
            ],
            "max_iterations must be >= 1",
        ),
        (["baps-run", "start"], "project_type must be non-empty"),
        (
            [
                "baps-run",
                "start",
                "--project-type",
                "document",
                "--artifact-id",
                "main-document",
                "--output",
                "output/report.md",
                "--goal",
                "   ",
            ],
            "goal must be non-empty",
        ),
        (
            [
                "baps-run",
                "start",
                "--project-type",
                "document",
                "--artifact-id",
                "main-document",
                "--goal",
                "Write a report.",
                "--output",
                "output/report.md",
                "--workspace",
                "   ",
            ],
            "workspace must be non-empty",
        ),
        (
            [
                "baps-run",
                "start",
                "--project-type",
                "document",
                "--artifact-id",
                "main-document",
                "--goal",
                "Write a report.",
                "--output",
                "   ",
            ],
            "output must be non-empty",
        ),
        (
            [
                "baps-run",
                "start",
                "--project-type",
                "document",
                "--artifact-id",
                "main-document",
                "--output",
                "output/report.md",
            ],
            "goal is required",
        ),
        (
            [
                "baps-run",
                "start",
                "--project-type",
                "document",
                "--artifact-id",
                "main-document",
                "--goal",
                "Write a report.",
            ],
            "output is required",
        ),
    ],
)
def test_invalid_config_fails_cleanly(
    monkeypatch, caplog, tmp_path, argv: list[str], error_substring: str
) -> None:
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
            [
                "baps-run",
                "start",
                "--project-type",
                "git",
                "--goal",
                "g",
                "--output",
                "o/o.md",
            ],
            "project_type 'git' is not implemented",
        ),
        (
            [
                "baps-run",
                "start",
                "--project-type",
                "unknown",
                "--goal",
                "g",
                "--output",
                "o/o.md",
            ],
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


def test_resolve_config_reads_artifact_id_and_northstar_and_create_state_uses_artifact_id(
    tmp_path: Path,
) -> None:
    import baps.core.run as run_module

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


def test_required_sections_top_level_is_rejected_in_config(
    monkeypatch, caplog, tmp_path: Path
) -> None:
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


def test_spec_file_multiple_unknown_keys_all_reported(
    monkeypatch, caplog, tmp_path: Path
) -> None:
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
        "\n".join(
            [
                "workspace: " + str(tmp_path / "ws"),
                "project_type: document",
                "artifact_id: main-document",
                "northstar_markdown: '# Goal'",
                "goal: Write a report.",
                "output: output/report.md",
                "max_iterations: 1",
            ]
        ),
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


def test_spec_relative_path_resolves_from_cwd(
    monkeypatch, capsys, tmp_path: Path
) -> None:
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


def test_debug_enabled_prints_read_config_input_output(
    monkeypatch, caplog, tmp_path: Path
) -> None:
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


def test_examples_document_project_yaml_still_passes(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    import baps.core.run as run_module

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


def test_start_cli_args_override_workspace_config(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    import baps.core.run as run_module

    workspace = tmp_path / "ws-override"
    spec = tmp_path / "init-spec.yaml"
    spec.write_text(
        "\n".join(
            [
                f"workspace: {workspace}",
                "project_type: document",
                "artifact_id: main-document",
                "goal: Original goal.",
                "northstar_markdown: '# NorthStar\\n\\nWrite a report.'",
                "output: output/report.md",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["baps-run", "start", "--spec", str(spec)])
    run_module.main()
    capsys.readouterr()

    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--goal",
            "Overridden goal.",
            "--max-iterations",
            "1",
        ],
    )
    run_module.main()
    out = capsys.readouterr().out
    assert "goal=Overridden goal." in out


def test_coding_example_output_path_resolves_under_workspace() -> None:
    import baps.core.run as run_module

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
    assert (
        config["output_path"]
        == Path(".baps-workspace/coding-project/output/project").resolve()
    )


def test_resolve_run_config_max_sub_gaps_defaults_to_5(tmp_path: Path) -> None:
    import argparse
    import yaml
    import baps.core.run as run_module

    (tmp_path / "ns.md").write_text("NorthStar")
    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_path": str(tmp_path / "ns.md"),
        "goal": "write a doc",
        "output": "out/doc.md",
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
    assert config["max_sub_gaps"] == 5


def test_resolve_run_config_max_sub_gaps_from_spec(tmp_path: Path) -> None:
    import argparse
    import yaml
    import baps.core.run as run_module

    (tmp_path / "ns.md").write_text("NorthStar")
    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_path": str(tmp_path / "ns.md"),
        "goal": "write a doc",
        "output": "out/doc.md",
        "max_sub_gaps": 3,
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
    assert config["max_sub_gaps"] == 3


def test_resolve_run_config_max_sub_gaps_zero_raises(tmp_path: Path) -> None:
    import argparse
    import pytest
    import yaml
    import baps.core.run as run_module

    (tmp_path / "ns.md").write_text("NorthStar")
    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_path": str(tmp_path / "ns.md"),
        "goal": "write a doc",
        "output": "out/doc.md",
        "max_sub_gaps": 0,
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
    with pytest.raises(ValueError, match="max_sub_gaps must be >= 1"):
        run_module.resolve_run_config(args)


def test_resolve_run_config_max_sub_gaps_non_integer_raises(tmp_path: Path) -> None:
    import argparse
    import pytest
    import yaml
    import baps.core.run as run_module

    (tmp_path / "ns.md").write_text("NorthStar")
    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_path": str(tmp_path / "ns.md"),
        "goal": "write a doc",
        "output": "out/doc.md",
        "max_sub_gaps": "lots",
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
    with pytest.raises(ValueError, match="max_sub_gaps must be an integer"):
        run_module.resolve_run_config(args)


def test_resolve_runconfig_language_zig_propagates_to_config(tmp_path: Path) -> None:
    import argparse
    import yaml
    import baps.core.run as run_module

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


def test_resolve_runconfig_language_absent_leaves_empty_string(tmp_path: Path) -> None:
    import argparse
    import yaml
    import baps.core.run as run_module

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
