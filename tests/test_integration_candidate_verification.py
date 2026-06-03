import baps.state.state as state_module
from baps.adapters.coding_adapter import CodingProjectAdapter


def testapply_delta_to_files_write_file() -> None:
    from baps.adapters.coding_adapter import apply_delta_to_files

    existing = (state_module.CodeFile(path="src/a.py", content="old"),)
    delta = state_module.DeltaCodingState(
        artifact_id="art",
        operation="write_file",
        payload=state_module.WriteFileDelta(file=state_module.CodeFile(path="src/a.py", content="new")),
    )
    result = apply_delta_to_files(existing, delta)
    assert len(result) == 1
    assert result[0].content == "new"


def testapply_delta_to_files_write_files_adds_and_replaces() -> None:
    from baps.adapters.coding_adapter import apply_delta_to_files

    existing = (state_module.CodeFile(path="src/a.py", content="old_a"),)
    delta = state_module.DeltaCodingBatchState(
        artifact_id="art",
        operation="write_files",
        payload=state_module.WriteFilesDelta(
            files=[
                state_module.CodeFile(path="src/a.py", content="new_a"),
                state_module.CodeFile(path="src/b.py", content="b_content"),
            ]
        ),
    )
    result = apply_delta_to_files(existing, delta)
    paths = {f.path for f in result}
    assert paths == {"src/a.py", "src/b.py"}
    a = next(f for f in result if f.path == "src/a.py")
    assert a.content == "new_a"


def testapply_delta_to_files_delete_file() -> None:
    from baps.adapters.coding_adapter import apply_delta_to_files

    existing = (
        state_module.CodeFile(path="src/a.py", content="a"),
        state_module.CodeFile(path="src/b.py", content="b"),
    )
    delta = state_module.DeltaDeleteCodingState(
        artifact_id="art",
        operation="delete_file",
        payload=state_module.DeleteFileDelta(path="src/a.py"),
    )
    result = apply_delta_to_files(existing, delta)
    assert len(result) == 1
    assert result[0].path == "src/b.py"


def test_verify_candidate_returns_none_when_no_test_files() -> None:

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="art",
                files=(state_module.CodeFile(path="src/foo.py", content="x = 1"),),
            ),
        ),
    )
    delta = state_module.DeltaCodingState(
        artifact_id="art",
        operation="write_file",
        payload=state_module.WriteFileDelta(file=state_module.CodeFile(path="src/bar.py", content="y = 2")),
    )
    result = CodingProjectAdapter().verify_candidate(delta, state, "art")
    assert result is None


def test_verify_candidate_passes_when_tests_pass(tmp_path) -> None:

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="art",
                files=(state_module.CodeFile(path="src/calc.py", content="def add(a, b):\n    return a + b\n"),),
            ),
        ),
    )
    delta = state_module.DeltaCodingState(
        artifact_id="art",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(
                path="tests/test_calc.py",
                content=(
                    "import sys, os\n"
                    "sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))\n"
                    "from calc import add\n"
                    "def test_add():\n"
                    "    assert add(1, 2) == 3\n"
                ),
            )
        ),
    )
    result = CodingProjectAdapter().verify_candidate(delta, state, "art", sandbox_mode="none")
    assert result is not None
    assert result.passed is True
    assert result.exit_code == 0


def test_verify_candidate_fails_when_tests_fail() -> None:

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="art",
                files=(state_module.CodeFile(path="src/calc.py", content="def add(a, b):\n    return 99\n"),),
            ),
        ),
    )
    delta = state_module.DeltaCodingState(
        artifact_id="art",
        operation="write_file",
        payload=state_module.WriteFileDelta(
            file=state_module.CodeFile(
                path="tests/test_calc.py",
                content=(
                    "import sys, os\n"
                    "sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))\n"
                    "from calc import add\n"
                    "def test_add():\n"
                    "    assert add(1, 2) == 3\n"
                ),
            )
        ),
    )
    result = CodingProjectAdapter().verify_candidate(delta, state, "art", sandbox_mode="none")
    assert result is not None
    assert result.passed is False
    assert result.exit_code == 1
