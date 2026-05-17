from pathlib import Path

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
    monkeypatch.setattr("sys.argv", ["baps-run", "--workspace", str(workspace)])

    main()
    out = capsys.readouterr().out

    assert f"workspace={workspace}" in out
    assert f"output_path={workspace / 'output' / 'report.md'}" in out
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


def test_duplicate_detection_uses_authoritative_document_not_view_content(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "ws"
    import baps.run as run_module

    original_build_input = run_module._build_input

    def _misleading_build_input(iteration: int, current_document: str):
        input_obj = original_build_input(iteration=iteration, current_document=current_document)
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
