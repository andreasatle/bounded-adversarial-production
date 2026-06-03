from pathlib import Path

from baps.adapters.project_adapter import VerificationResult
from baps.core.parsers import NoNewGameError
from baps.state.state import GameSpec
import baps.state.state as state_module
def test_coding_run_no_files_keeps_output_exported_false(monkeypatch, tmp_path: Path, capsys) -> None:
    import baps.core.run as run_module

    workspace = tmp_path / "coding-empty-export"
    _cg_n: dict[str, int] = {"n": 0}
    _cg_spec = GameSpec(
        objective="No-op coding objective",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="No file changes required",
    )

    def _mock_cg(*_args, **_kwargs):
        _cg_n["n"] += 1
        if _cg_n["n"] > 1:
            raise NoNewGameError("done")
        return _cg_spec

    monkeypatch.setattr("baps.core.orchestration.create_game", _mock_cg)
    monkeypatch.setattr("baps.core.orchestration.play_game", lambda *_args, **_kwargs: None)
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
    import baps.core.run as run_module

    workspace = tmp_path / "coding-verify-summary"

    monkeypatch.setattr(
        "baps.core.orchestration.create_game",
        lambda *_args, **_kwargs: GameSpec(
            objective="Write one file",
            target_artifact_id="main-codebase",
            allowed_delta_type="DeltaCodingState",
            success_condition="File exists",
        ),
    )
    monkeypatch.setattr(
        "baps.core.orchestration.play_game",
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
    import baps.core.run as run_module

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
    import baps.core.run as run_module

    workspace = tmp_path / "coding-workspace"
    output_dir = workspace / "output" / "project"

    monkeypatch.setattr(
        "baps.core.orchestration.create_game",
        lambda *_args, **_kwargs: GameSpec(
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

    monkeypatch.setattr("baps.core.orchestration.play_game", _play_game)
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

def test_coding_iteration_two_does_not_receive_stale_verification_result(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.core.run as run_module

    workspace = tmp_path / "coding-no-stale-verification"
    verification_seen: list[object] = []
    call_counter = {"count": 0}

    def _create_game(_config, _state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        del verification_result
        call_counter["count"] += 1
        if call_counter["count"] == 1:
            return GameSpec(
                objective="Write src/fibonacci.py containing implementation",
                target_artifact_id="main-codebase",
                allowed_delta_type="DeltaCodingState",
                success_condition="src/fibonacci.py exists",
            )
        if call_counter["count"] == 2:
            return GameSpec(
                objective="Write tests/test_fibonacci.py containing tests",
                target_artifact_id="main-codebase",
                allowed_delta_type="DeltaCodingState",
                success_condition="tests/test_fibonacci.py exists",
            )
        raise NoNewGameError("done")

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

    monkeypatch.setattr("baps.core.orchestration.create_game", _create_game)
    monkeypatch.setattr("baps.core.orchestration.play_game", _play_game)
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
    assert isinstance(verification_seen[1], VerificationResult)  # second iteration: receives prior export result


def test_coding_create_game_receives_previous_verification_result_second_iteration(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.core.run as run_module

    workspace = tmp_path / "coding-create-game-verification-input"
    seen: list[VerificationResult | None] = []
    create_count = {"n": 0}

    def _create_game(_config, _state, adapter=None, verification_result=None, context_chain=(), depth=0, **_kwargs):
        del adapter
        seen.append(verification_result)
        create_count["n"] += 1
        if create_count["n"] == 1:
            return GameSpec(
                objective="Write src/fibonacci.py containing implementation",
                target_artifact_id="main-codebase",
                allowed_delta_type="DeltaCodingState",
                success_condition="src/fibonacci.py exists",
            )
        if create_count["n"] == 2:
            return GameSpec(
                objective="Write tests/test_fibonacci.py containing tests",
                target_artifact_id="main-codebase",
                allowed_delta_type="DeltaCodingState",
                success_condition="tests/test_fibonacci.py exists",
            )
        raise NoNewGameError("done")

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
            return VerificationResult(
                command="uv run pytest",
                cwd=str(workspace / "output" / "project"),
                exit_code=2,
                stdout="ModuleNotFoundError: No module named 'src'",
                stderr="",
                passed=False,
            )
        return VerificationResult(
            command="uv run pytest",
            cwd=str(workspace / "output" / "project"),
            exit_code=0,
            stdout="1 passed",
            stderr="",
            passed=True,
        )

    monkeypatch.setattr("baps.core.orchestration.create_game", _create_game)
    monkeypatch.setattr("baps.core.orchestration.play_game", _play_game)
    monkeypatch.setattr("baps.core.orchestration.verify_export_with_adapter", _verify_export)
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
