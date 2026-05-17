from pathlib import Path

from baps.state import State
from baps.state_loop_demo import main, run_state_loop_demo
from baps.state_store import JsonStateStore


def test_run_state_loop_demo_creates_state_file_and_runs_once(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace-a"
    state_path = workspace / "state" / "demo-state.json"

    iteration_1, iteration_2 = run_state_loop_demo(
        workspace=workspace,
        runtime_objective="Run deterministic state loop demo",
    )
    loop_result_1, northstar_view_1, proposal_1, updated_state_1, before_1, after_1 = iteration_1
    loop_result_2, northstar_view_2, proposal_2, updated_state_2, before_2, after_2 = iteration_2

    assert state_path.exists()
    assert loop_result_1.proposal.id != ""
    assert loop_result_2.proposal.id != ""
    assert northstar_view_1.content != ""
    assert northstar_view_2.content != ""
    assert proposal_1 is not None
    assert proposal_2 is not None
    assert updated_state_1 is not None
    assert updated_state_2 is not None
    assert before_2 == after_1
    assert (before_1 != after_1) is True
    assert (before_2 != after_2) is True

    loaded = JsonStateStore(state_path).load()
    assert isinstance(loaded, State)
    assert after_2 != ""


def test_state_loop_demo_main_uses_custom_workspace(monkeypatch, capsys, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace-custom"
    state_path = workspace / "state" / "demo-state.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-state-loop-demo",
            "--workspace",
            str(workspace),
            "--runtime-objective",
            "Deterministic objective",
        ],
    )

    main()
    out = capsys.readouterr().out

    assert "iteration=1" in out
    assert "iteration=2" in out
    assert "proposal_id=" in out
    assert "decision_id=" in out
    assert "update_proposal_produced=True" in out
    assert "update_applied=True" in out
    assert "state_changed=True" in out
    assert "state_fingerprint_before=" in out
    assert "state_fingerprint_after=" in out
    assert f"workspace={workspace}" in out
    assert f"state_path={state_path}" in out


def test_state_loop_demo_main_uses_default_workspace_and_not_repo_state(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-state-loop-demo",
            "--runtime-objective",
            "Deterministic objective",
        ],
    )

    main()
    out = capsys.readouterr().out

    expected_workspace = Path(".baps-workspace")
    expected_state_path = expected_workspace / "state" / "demo-state.json"
    assert expected_state_path.exists()
    assert not Path("state/demo-state.json").exists()
    assert f"workspace={expected_workspace}" in out
    assert f"state_path={expected_state_path}" in out
