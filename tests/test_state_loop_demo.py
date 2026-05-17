from pathlib import Path

from baps.state import State
from baps.state_loop_demo import main, run_state_loop_demo
from baps.state_store import JsonStateStore


def test_run_state_loop_demo_creates_state_file_and_runs_once(tmp_path: Path) -> None:
    state_path = tmp_path / "state" / "demo-state.json"

    loop_result, northstar_view, proposal, updated_state = run_state_loop_demo(
        state_path=state_path,
        runtime_objective="Run deterministic state loop demo",
    )

    assert state_path.exists()
    assert loop_result.proposal.id != ""
    assert northstar_view.content != ""
    assert proposal is not None
    assert updated_state is not None

    loaded = JsonStateStore(state_path).load()
    assert isinstance(loaded, State)


def test_state_loop_demo_main_prints_expected_fields(monkeypatch, capsys, tmp_path: Path) -> None:
    state_path = tmp_path / "state" / "demo-state.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-state-loop-demo",
            "--state-path",
            str(state_path),
            "--runtime-objective",
            "Deterministic objective",
        ],
    )

    main()
    out = capsys.readouterr().out

    assert "loop_proposal_id=" in out
    assert "loop_execution_result_id=" in out
    assert "loop_integration_decision_id=" in out
    assert "update_proposal_produced=True" in out
    assert "state_updated=True" in out
    assert f"state_path={state_path}" in out
