from pathlib import Path

from baps.state import State
from baps.state_loop_demo import main, run_state_loop_demo
from baps.state_store import JsonStateStore


def test_run_state_loop_demo_creates_state_file_and_runs_once(tmp_path: Path) -> None:
    state_path = tmp_path / "state" / "demo-state.json"

    iteration_1, iteration_2 = run_state_loop_demo(
        state_path=state_path,
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

    loaded = JsonStateStore(state_path).load()
    assert isinstance(loaded, State)
    assert after_2 != ""


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

    assert "iteration=1" in out
    assert "iteration=2" in out
    assert "proposal_id=" in out
    assert "decision_id=" in out
    assert "update_proposal_produced=True" in out
    assert "update_proposal_produced_iteration2=True" in out
    assert "state_updated=True" in out
    assert "state_fingerprint_before=" in out
    assert "state_fingerprint_after=" in out
    assert f"state_path={state_path}" in out
