import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import baps.state.state as state_module
from baps.adapters.coding_adapter import CodingProjectAdapter
from baps.adapters.document_adapter import DocumentProjectAdapter
from baps.core.run_config import RunConfig
from baps.models.models import FakeModelClient, Role
from baps.state.state import (
    GameSpec,
)
from baps.summarizer.summarizer import SummarizationContext

# ---------------------------------------------------------------------------
# Shared helpers for Rust / Zig Docker mocking
# ---------------------------------------------------------------------------

_RUST_SRC = """\
/// Returns the sum of two integers.
pub fn add(a: i32, b: i32) -> i32 {
    a + b
}

fn _private() {}
"""

_RUST_INDEX = {
    "items": [
        {
            "kind": "fn",
            "name": "add",
            "pub": True,
            "signature": "pub fn add(a: i32, b: i32) -> i32",
            "doc": "Returns the sum of two integers.",
            "is_test": False,
            "body_start": 2,
            "body_end": 4,
        },
        {
            "kind": "fn",
            "name": "_private",
            "pub": False,
            "signature": "fn _private()",
            "doc": None,
            "is_test": False,
            "body_start": 6,
            "body_end": 6,
        },
    ]
}

_ZIG_SRC = """\
/// Adds two integers.
pub fn add(a: i32, b: i32) i32 {
    return a + b;
}

fn _private() void {}
"""

_ZIG_INDEX = {
    "items": [
        {
            "kind": "fn",
            "name": "add",
            "pub": True,
            "signature": "pub fn add(a: i32, b: i32) i32",
            "doc": "Adds two integers.",
            "is_test": False,
            "body_start": 2,
            "body_end": 4,
        },
        {
            "kind": "fn",
            "name": "_private",
            "pub": False,
            "signature": "fn _private() void",
            "doc": None,
            "is_test": False,
            "body_start": 6,
            "body_end": 6,
        },
    ]
}


def _rust_docker_mock():
    m = MagicMock()
    m.stdout = json.dumps(_RUST_INDEX)
    m.returncode = 0
    return m


def _zig_docker_mock():
    m = MagicMock()
    m.stdout = json.dumps(_ZIG_INDEX)
    m.returncode = 0
    return m


def _make_summarization_context(response: str) -> SummarizationContext:
    role = Role(name="summarize", client=FakeModelClient([response]))
    return SummarizationContext(summarizer=role, game_spec=None)


def test_state_view_is_derived_from_state_and_gamespec_with_existing_sections() -> None:

    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.DocumentArtifact(
                id="main-document",
                sections=(state_module.Section(title="Existing", body="Already here"),),
            ),
        ),
    )
    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    assert state_view.metadata["target_artifact_id"] == "main-document"
    assert state_view.metadata["sections"] == [{"title": "Existing", "body": "Already here"}]
    assert state_view.content.startswith("=== StateView Start ===")
    assert state_view.content.endswith("=== StateView End ===")
    assert "--- State Artifacts ---" in state_view.content
    assert "## Artifact: main-document" in state_view.content
    assert "kind: document" in state_view.content
    assert "### Current Sections" in state_view.content
    assert "### Existing" in state_view.content
    assert "Already here" in state_view.content
    assert '"sections"' not in state_view.content
    assert "target_artifact_id" not in state_view.content
    assert "metadata" not in state_view.content
    assert "input_fingerprint" not in state_view.content


def test_document_state_view_content_for_empty_document() -> None:

    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Any success condition.",
    )
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="main-document", sections=()),),
    )

    state_view = DocumentProjectAdapter().build_state_view(state, spec)
    content = state_view.content
    assert content.startswith("=== StateView Start ===")
    assert content.endswith("=== StateView End ===")
    assert "--- State Artifacts ---" in content
    assert "## Artifact: main-document" in content
    assert "kind: document" in content
    assert "### Current Sections" in content
    assert "No sections." in content
    assert '"sections"' not in content
    assert "target_artifact_id" not in content
    assert "metadata" not in content
    assert "input_fingerprint" not in content


def test_create_game_state_view_content_is_markdown_for_empty_document() -> None:

    state = state_module.State(
        artifacts=(state_module.DocumentArtifact(id="main-document", sections=()),),
    )

    state_view = DocumentProjectAdapter().build_create_game_state_view(
        state,
        {
            "artifact_id": "main-document",
            "northstar_markdown": "# Goal\n\nWrite a short report about bounded adversarial evaluation.",
        },
    )
    content = state_view.content
    assert content.startswith("=== StateView Start ===")
    assert content.endswith("=== StateView End ===")
    assert "--- NorthStar ---" in content
    assert "--- NorthStar ---\n\n# Goal" in content
    assert "Write a short report about bounded adversarial evaluation." in content
    assert "--- State Artifacts ---" in content
    assert "## Artifact: main-document" in content
    assert "kind: document" in content
    assert "### Current Sections" in content
    assert "No sections." in content
    assert "# StateView" not in content
    assert "## NorthStar" not in content
    assert "## Target Artifact" not in content
    assert "northstar_content" not in content
    assert "target_artifact" not in content
    assert not content.lstrip().startswith("{")


def test_create_game_state_view_content_includes_sections_as_markdown() -> None:

    state = state_module.State(
        artifacts=(
            state_module.DocumentArtifact(
                id="main-document",
                sections=(state_module.Section(title="Introduction", body="Intro body text."),),
            ),
        ),
    )

    state_view = DocumentProjectAdapter().build_create_game_state_view(
        state,
        {
            "artifact_id": "main-document",
            "northstar_markdown": "# Goal\n\nWrite a short report about bounded adversarial evaluation.",
        },
    )
    content = state_view.content
    assert "### Current Sections" in content
    assert "### Introduction" in content
    assert "Intro body text." in content
    assert "northstar_content" not in content
    assert "target_artifact" not in content
    assert not content.lstrip().startswith("{")


def test_coding_create_game_state_view_is_textual_with_delimiters() -> None:
    import baps.core.run as run_module

    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "coding",
        "artifact_id": "main-codebase",
        "language": "python",
        "goal": "Implement Fibonacci",
        "northstar_markdown": "# Goal\n\nImplement Fibonacci",
        "output_path": Path(".baps-workspace/output/project"),
        "max_iterations": 2,
        "spec_path": None,
    }
    state = run_module.create_state(RunConfig(**config))
    adapter = CodingProjectAdapter()
    view = adapter.build_create_game_state_view(state, config)
    assert view.content.startswith("=== StateView Start ===")
    assert view.content.endswith("=== StateView End ===")
    assert "--- NorthStar ---" in view.content
    assert "--- State Artifacts ---" in view.content
    assert "## Artifact: main-codebase" in view.content
    assert "kind: coding" in view.content
    assert "No files." in view.content


def test_coding_create_game_state_view_includes_structural_api_summary() -> None:

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(state_module.CodeFile(path="src/hello.py", content="def hello():\n    return 'hi'\n"),),
            ),
        ),
    )
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "coding",
        "artifact_id": "main-codebase",
        "goal": "Build something",
        "northstar_markdown": "# Goal",
        "output_path": Path(".baps-workspace/output"),
        "max_iterations": 1,
        "spec_path": None,
    }
    adapter = CodingProjectAdapter()
    view = adapter.build_create_game_state_view(state, config)
    assert "src/hello.py" in view.content
    assert "def hello():" in view.content
    assert "[api]" in view.content


def test_coding_create_game_state_view_does_not_use_first_30_lines_as_primary_path() -> None:

    long_content = "\n".join(f"line_{i} = {i}" for i in range(100))
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(state_module.CodeFile(path="src/big.py", content=long_content),),
            ),
        ),
    )
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "coding",
        "artifact_id": "main-codebase",
        "goal": "Build something",
        "northstar_markdown": "# Goal",
        "output_path": Path(".baps-workspace/output"),
        "max_iterations": 1,
        "spec_path": None,
    }
    adapter = CodingProjectAdapter()
    view = adapter.build_create_game_state_view(state, config)
    assert "[api-empty]" in view.content
    assert "more lines" not in view.content
    assert "line_99 = 99" not in view.content


def test_coding_create_game_state_view_line_count_in_heading_without_summarizer() -> None:
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(state_module.CodeFile(path="src/hello.py", content="def hello():\n    return 'hi'\n"),),
            ),
        ),
    )
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "coding",
        "artifact_id": "main-codebase",
        "goal": "Build something",
        "northstar_markdown": "# Goal",
        "output_path": Path(".baps-workspace/output"),
        "max_iterations": 1,
        "spec_path": None,
    }
    view = CodingProjectAdapter().build_create_game_state_view(state, config, summarization_context=None)
    assert "src/hello.py (2 lines)" in view.content
    assert "def hello():" in view.content
    assert "[api]" in view.content


def test_coding_create_game_state_view_remains_structural_even_with_summarizer() -> None:
    long_content = "\n".join(f"line_{i} = {i}" for i in range(100))
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(state_module.CodeFile(path="src/big.py", content=long_content),),
            ),
        ),
    )
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "coding",
        "artifact_id": "main-codebase",
        "goal": "Build something",
        "northstar_markdown": "# Goal",
        "output_path": Path(".baps-workspace/output"),
        "max_iterations": 1,
        "spec_path": None,
    }
    summarization_context = _make_summarization_context("API summary: assigns integers to variables")
    view = CodingProjectAdapter().build_create_game_state_view(
        state, config, summarization_context=summarization_context
    )
    assert "[api-empty]" in view.content
    assert "API summary: assigns integers to variables" not in view.content
    assert "src/big.py (100 lines)" in view.content


def test_coding_create_game_state_view_line_count_present_with_summarizer() -> None:
    content = "a = 1\nb = 2\nc = 3\n"
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=(state_module.CodeFile(path="src/abc.py", content=content),),
            ),
        ),
    )
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "coding",
        "artifact_id": "main-codebase",
        "goal": "Build something",
        "northstar_markdown": "# Goal",
        "output_path": Path(".baps-workspace/output"),
        "max_iterations": 1,
        "spec_path": None,
    }
    summarization_context = _make_summarization_context("three variable assignments")
    view = CodingProjectAdapter().build_create_game_state_view(
        state, config, summarization_context=summarization_context
    )
    assert "src/abc.py (3 lines)" in view.content
    assert "[api-empty]" in view.content
    assert "three variable assignments" not in view.content


# ---------------------------------------------------------------------------
# build_coding_state_view — target_entity / summarization tests
# ---------------------------------------------------------------------------


def _make_coding_state(files: list[tuple[str, str]]) -> state_module.State:
    return state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="main-codebase",
                files=tuple(state_module.CodeFile(path=p, content=c) for p, c in files),
            ),
        ),
    )


def _make_coding_spec(target_entity: str | None = None) -> GameSpec:
    return GameSpec(
        objective="Fix the target file",
        target_artifact_id="main-codebase",
        allowed_delta_type="DeltaCodingState",
        success_condition="target file updated",
        target_entity=target_entity,
    )


def test_coding_state_view_target_entity_match_is_full_others_summarized() -> None:
    files = [
        ("src/target.py", "def target(): pass\n"),
        ("src/other.py", "def other(): pass\n"),
    ]
    state = _make_coding_state(files)
    spec = _make_coding_spec(target_entity="src/target.py")
    summarization_context = _make_summarization_context("summary of other")
    view = CodingProjectAdapter().build_state_view(state, spec, summarization_context=summarization_context)
    assert "src/target.py (1 lines) [full]" in view.content
    assert "def target(): pass" in view.content
    assert "src/other.py (1 lines) [api]" in view.content
    assert "summary of other" not in view.content
    assert "def other(): pass" not in view.content


def test_coding_state_view_target_entity_none_all_compact_api_current_behavior() -> None:
    files = [
        ("src/a.py", "x = 1\n"),
        ("src/b.py", "y = 2\n"),
    ]
    state = _make_coding_state(files)
    spec = _make_coding_spec(target_entity=None)
    summarization_context = _make_summarization_context("should not appear")
    view = CodingProjectAdapter().build_state_view(state, spec, summarization_context=summarization_context)
    assert "[full]" not in view.content
    assert "src/a.py (1 lines) [api]" in view.content
    assert "src/b.py (1 lines) [api]" in view.content


def test_coding_state_view_summarizer_none_keeps_non_target_compact_when_target_set() -> None:
    files = [
        ("src/target.py", "def t(): pass\n"),
        ("src/other.py", "def o(): pass\n"),
    ]
    state = _make_coding_state(files)
    spec = _make_coding_spec(target_entity="src/target.py")
    ctx = SummarizationContext(summarizer=None, game_spec=spec)
    view = CodingProjectAdapter().build_state_view(state, spec, summarization_context=ctx)
    assert "src/target.py (1 lines) [full]" in view.content
    assert "src/other.py (1 lines) [api]" in view.content
    assert "def t(): pass" in view.content
    assert "def o(): pass" not in view.content


def test_coding_state_view_target_entity_present_and_no_context_keeps_non_target_compact() -> None:
    files = [
        ("src/target.py", "def t(): pass\n"),
        ("src/other.py", "def o(): pass\n"),
    ]
    state = _make_coding_state(files)
    spec = _make_coding_spec(target_entity="src/target.py")
    view = CodingProjectAdapter().build_state_view(state, spec, summarization_context=None)
    assert "src/target.py (1 lines) [full]" in view.content
    assert "src/other.py (1 lines) [api]" in view.content
    assert "def t(): pass" in view.content
    assert "def o(): pass" not in view.content


def test_coding_state_view_invalid_target_entity_warns_and_stays_compact() -> None:
    files = [
        ("src/target.py", "def t(): pass\n"),
        ("src/other.py", "def o(): pass\n"),
    ]
    state = _make_coding_state(files)
    spec = _make_coding_spec(target_entity="src/missing.py")
    view = CodingProjectAdapter().build_state_view(state, spec, summarization_context=None)
    assert "WARNING: target_entity did not match any known file." in view.content
    assert "No full file was expanded; rendering compact structural views for all files." in view.content
    assert "[full]" not in view.content
    assert "src/target.py (1 lines) [api]" in view.content
    assert "src/other.py (1 lines) [api]" in view.content


# ---------------------------------------------------------------------------
# build_document_state_view — target_entity / summarization tests
# ---------------------------------------------------------------------------


def _make_document_state(sections: list[tuple[str, str]]) -> state_module.State:
    return state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.DocumentArtifact(
                id="main-document",
                sections=tuple(state_module.Section(title=t, body=b) for t, b in sections),
            ),
        ),
    )


def _make_document_spec(target_entity: str | None = None) -> GameSpec:
    return GameSpec(
        objective="Update the target section",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="target section updated",
        target_entity=target_entity,
    )


def test_document_state_view_target_entity_match_is_full_others_summarized() -> None:
    sections = [
        ("Introduction", "Full intro body here."),
        ("Background", "Background body text."),
    ]
    state = _make_document_state(sections)
    spec = _make_document_spec(target_entity="Introduction")
    summarization_context = _make_summarization_context("background summary")
    view = DocumentProjectAdapter().build_state_view(state, spec, summarization_context=summarization_context)
    assert "### Introduction [full]" in view.content
    assert "Full intro body here." in view.content
    assert "### Background [summary]" in view.content
    assert "background summary" in view.content
    assert "Background body text." not in view.content


def test_document_state_view_target_entity_none_all_full_current_behavior() -> None:
    sections = [
        ("Sec A", "Body A."),
        ("Sec B", "Body B."),
    ]
    state = _make_document_state(sections)
    spec = _make_document_spec(target_entity=None)
    summarization_context = _make_summarization_context("should not appear")
    view = DocumentProjectAdapter().build_state_view(state, spec, summarization_context=summarization_context)
    assert "[summary]" not in view.content
    assert "[full]" not in view.content
    assert "Body A." in view.content
    assert "Body B." in view.content


def test_document_state_view_summarizer_none_all_full_regardless_of_target_entity() -> None:
    sections = [
        ("Target", "Target body."),
        ("Other", "Other body."),
    ]
    state = _make_document_state(sections)
    spec = _make_document_spec(target_entity="Target")
    ctx = SummarizationContext(summarizer=None, game_spec=spec)
    view = DocumentProjectAdapter().build_state_view(state, spec, summarization_context=ctx)
    assert "[summary]" not in view.content
    assert "Target body." in view.content
    assert "Other body." in view.content


def test_document_state_view_fallback_to_full_when_summarization_context_none() -> None:
    sections = [
        ("Target", "Target body."),
        ("Other", "Other body."),
    ]
    state = _make_document_state(sections)
    spec = _make_document_spec(target_entity="Target")
    view = DocumentProjectAdapter().build_state_view(state, spec, summarization_context=None)
    assert "[summary]" not in view.content
    assert "Target body." in view.content
    assert "Other body." in view.content


# ---------------------------------------------------------------------------
# Python view — create-game and play-game
# ---------------------------------------------------------------------------

_PY_SRC = """\
def add(a: int, b: int) -> int:
    \"\"\"Return the sum of a and b.\"\"\"
    return a + b

def _private():
    pass
"""


def _make_python_state() -> state_module.State:
    return state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="lib",
                language="python",
                files=(state_module.CodeFile(path="src/math.py", content=_PY_SRC),),
            ),
        ),
    )


def test_python_create_game_state_view_api_surface() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "coding",
        "artifact_id": "lib",
        "goal": "Build a math library",
        "northstar_markdown": "# Goal\n\nBuild a math library",
        "output_path": Path(".baps-workspace/output"),
        "max_iterations": 1,
        "spec_path": None,
    }
    view = CodingProjectAdapter().build_create_game_state_view(_make_python_state(), config)
    assert "src/math.py" in view.content
    assert "def add" in view.content
    assert "[api]" in view.content
    assert "return a + b" not in view.content


def test_python_play_game_state_view_target_full_other_api() -> None:
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="lib",
                language="python",
                files=(
                    state_module.CodeFile(path="src/math.py", content=_PY_SRC),
                    state_module.CodeFile(path="src/other.py", content="def helper(): pass\n"),
                ),
            ),
        ),
    )
    spec = GameSpec(
        objective="Improve add",
        target_artifact_id="lib",
        allowed_delta_type="DeltaCodingState",
        success_condition="add updated",
        target_entity="src/math.py",
    )
    view = CodingProjectAdapter().build_state_view(state, spec)
    assert "src/math.py" in view.content
    assert "[full]" in view.content
    assert "return a + b" in view.content
    assert "src/other.py" in view.content
    assert "[api]" in view.content


# ---------------------------------------------------------------------------
# Rust view — create-game and play-game
# ---------------------------------------------------------------------------


def _make_rust_state() -> state_module.State:
    return state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="lib",
                language="rust",
                files=(state_module.CodeFile(path="src/lib.rs", content=_RUST_SRC),),
            ),
        ),
    )


def test_rust_create_game_state_view_api_surface() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "coding",
        "artifact_id": "lib",
        "goal": "Build a Rust library",
        "northstar_markdown": "# Goal\n\nBuild a Rust library",
        "output_path": Path(".baps-workspace/output"),
        "max_iterations": 1,
        "spec_path": None,
    }
    with patch("baps.plugins.language_rust.subprocess.run", return_value=_rust_docker_mock()):
        view = CodingProjectAdapter().build_create_game_state_view(_make_rust_state(), config)
    assert "src/lib.rs" in view.content
    assert "pub fn add" in view.content
    assert "_private" not in view.content
    assert "[api]" in view.content
    assert "Returns the sum of two integers." in view.content


def test_rust_play_game_state_view_target_full_no_extraction() -> None:
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="lib",
                language="rust",
                files=(
                    state_module.CodeFile(path="src/lib.rs", content=_RUST_SRC),
                    state_module.CodeFile(path="src/util.rs", content="pub fn noop() {}\n"),
                ),
            ),
        ),
    )
    spec = GameSpec(
        objective="Improve add",
        target_artifact_id="lib",
        allowed_delta_type="DeltaCodingState",
        success_condition="add updated",
        target_entity="src/lib.rs",
    )
    _util_index = {
        "items": [
            {
                "kind": "fn",
                "name": "noop",
                "pub": True,
                "signature": "pub fn noop()",
                "doc": None,
                "is_test": False,
                "body_start": 1,
                "body_end": 1,
            }
        ]
    }
    util_mock = MagicMock()
    util_mock.stdout = json.dumps(_util_index)
    util_mock.returncode = 0
    with patch("baps.plugins.language_rust.subprocess.run", return_value=util_mock):
        view = CodingProjectAdapter().build_state_view(state, spec)
    assert "src/lib.rs" in view.content
    assert "[full]" in view.content
    assert "a + b" in view.content
    assert "src/util.rs" in view.content
    assert "[api]" in view.content
    assert "pub fn noop" in view.content


# ---------------------------------------------------------------------------
# Zig view — create-game and play-game
# ---------------------------------------------------------------------------


def _make_zig_state() -> state_module.State:
    return state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="lib",
                language="zig",
                files=(state_module.CodeFile(path="src/main.zig", content=_ZIG_SRC),),
            ),
        ),
    )


def test_zig_create_game_state_view_api_surface() -> None:
    config = {
        "workspace": Path(".baps-workspace"),
        "project_type": "coding",
        "artifact_id": "lib",
        "goal": "Build a Zig library",
        "northstar_markdown": "# Goal\n\nBuild a Zig library",
        "output_path": Path(".baps-workspace/output"),
        "max_iterations": 1,
        "spec_path": None,
    }
    with patch("baps.plugins.language_zig.subprocess.run", return_value=_zig_docker_mock()):
        view = CodingProjectAdapter().build_create_game_state_view(_make_zig_state(), config)
    assert "src/main.zig" in view.content
    assert "pub fn add" in view.content
    assert "_private" not in view.content
    assert "[api]" in view.content
    assert "Adds two integers." in view.content


def test_zig_play_game_state_view_target_full_no_extraction() -> None:
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.CodingArtifact(
                id="lib",
                language="zig",
                files=(
                    state_module.CodeFile(path="src/main.zig", content=_ZIG_SRC),
                    state_module.CodeFile(path="src/util.zig", content="pub fn noop() void {}\n"),
                ),
            ),
        ),
    )
    spec = GameSpec(
        objective="Improve add",
        target_artifact_id="lib",
        allowed_delta_type="DeltaCodingState",
        success_condition="add updated",
        target_entity="src/main.zig",
    )
    _util_index = {
        "items": [
            {
                "kind": "fn",
                "name": "noop",
                "pub": True,
                "signature": "pub fn noop() void",
                "doc": None,
                "is_test": False,
                "body_start": 1,
                "body_end": 1,
            }
        ]
    }
    util_mock = MagicMock()
    util_mock.stdout = json.dumps(_util_index)
    util_mock.returncode = 0
    with patch("baps.plugins.language_zig.subprocess.run", return_value=util_mock):
        view = CodingProjectAdapter().build_state_view(state, spec)
    assert "src/main.zig" in view.content
    assert "[full]" in view.content
    assert "return a + b" in view.content
    assert "src/util.zig" in view.content
    assert "[api]" in view.content
    assert "pub fn noop" in view.content
