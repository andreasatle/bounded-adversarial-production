from pathlib import Path

import pytest

from baps.models import FakeModelClient
from baps.run import SECTION_MARKER, create_game, create_state, main, play_game, run_baps_loop


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


def test_create_game_receives_input_and_state_and_outputs_game_spec() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "goal": "Write a short report with an introduction and conclusion.",
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
        "goal": "Write a short report with an introduction and conclusion.",
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
        "goal": "Write a short report with an introduction and conclusion.",
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
        "goal": "Write a short report with an introduction and conclusion.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    monkeypatch.setenv("BAPS_DEBUG", "1")

    with pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient(["not-json-output"]))
    out = capsys.readouterr().out
    assert "[DEBUG] create_game.raw_model_output:" in out
    assert "  not-json-output" in out


def test_create_game_invalid_json_without_debug_does_not_print_raw_model_output(capsys) -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "goal": "Write a short report with an introduction and conclusion.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)

    with pytest.raises(ValueError, match="must be valid JSON"):
        create_game(config, state, model_client=FakeModelClient(["not-json-output"]))
    out = capsys.readouterr().out
    assert "[DEBUG] create_game.raw_model_output:" not in out


def test_create_game_raw_json_still_accepted() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "document",
        "goal": "Write a short report with an introduction and conclusion.",
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
        "goal": "Write a short report with an introduction and conclusion.",
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
        "goal": "Write a short report with an introduction and conclusion.",
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
        "goal": "Write a short report with an introduction and conclusion.",
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
        "goal": "Write a short report with an introduction and conclusion.",
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
        "goal": "Write a short report with an introduction and conclusion.",
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
        "goal": "Write a short report with an introduction and conclusion.",
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
        "goal": "Write a short report with an introduction and conclusion.",
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
        "goal": "Write a short report with an introduction and conclusion.",
        "output_path": Path(".baps-workspace/output/report.md"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = create_state(config)
    with pytest.raises(ValueError, match="target artifact not found in state"):
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
        "goal": "Write a short report with an introduction and conclusion.",
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
            "goal": "Write a short report with an introduction and conclusion.",
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
            "goal": "Write a short report with an introduction and conclusion.",
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
            "goal": "Write a short report with an introduction and conclusion.",
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
            "goal": "Write a short report with an introduction and conclusion.",
            "output_path": Path(".baps-workspace/output/report.md"),
            "max_iterations": 2,
            "spec_path": None,
        }
    )
    with pytest.raises(ValueError, match="blue model output must be valid JSON"):
        play_game(state, spec, model_client=FakeModelClient(["not-json"]))


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
            "goal": "Write a short report with an introduction and conclusion.",
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
            "goal": "Write a short report with an introduction and conclusion.",
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
            "goal": "Write a short report with an introduction and conclusion.",
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
            "goal": "Write a short report with an introduction and conclusion.",
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
            "goal": "Write a short report with an introduction and conclusion.",
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
            "goal": "Write a short report with an introduction and conclusion.",
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
            "goal": "Write a short report with an introduction and conclusion.",
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
            "goal": "Write a short report with an introduction and conclusion.",
            "output_path": Path(".baps-workspace/output/report.md"),
            "max_iterations": 2,
            "spec_path": None,
        }
    )
    state_view = run_module._build_blue_state_view(state, spec)
    prompt = run_module._render_blue_prompt(state_view, spec)
    assert "state_view_json:" in prompt
    assert "objective:" in prompt
    assert "target_artifact_id:" in prompt
    assert "allowed_delta_type:" in prompt
    assert "success_condition:" in prompt
    assert "blue_view_json:" not in prompt
    assert "state_json:" not in prompt


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
    state_view = run_module._build_blue_state_view(state, spec)
    assert state_view.metadata["target_artifact_id"] == "main-document"
    assert state_view.metadata["sections"] == [{"title": "Existing", "body": "Already here"}]


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
            "goal": "Write a short report with an introduction and conclusion.",
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
    )
    assert delta is None


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
            "goal": "Write a short report with an introduction and conclusion.",
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
    assert "[DEBUG] play_game.output:" in out
    blue_input_block = out.split("[DEBUG] blue.input:")[1].split("[DEBUG] blue.output:")[0]
    assert "state_view:" in blue_input_block
    assert "target_artifact_id: main-document" in blue_input_block
    assert "sections: []" in blue_input_block
    assert "state:" not in blue_input_block
    assert "game_spec:" in blue_input_block
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

    monkeypatch.setattr(run_module, "create_game", lambda config, state: expected)

    def _capture_play_game(state, spec):
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
        ],
    )

    run_module.main()

    assert captured["spec"] is expected
    assert captured["state"] is not None


def test_main_exits_cleanly_if_play_game_returns_none(monkeypatch, capsys, tmp_path: Path) -> None:
    import baps.run as run_module

    monkeypatch.setattr(run_module, "play_game", lambda _state, _spec: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "--workspace",
            str(tmp_path / "ws-play-none"),
            "--project-type",
            "document",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        run_module.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "error: play_game produced no DeltaState" in err


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
