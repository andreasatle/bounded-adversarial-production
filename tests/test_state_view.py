from pathlib import Path

from baps.state.state import (
    GameSpec,
)
from baps.adapters.document_adapter import DocumentProjectAdapter
from baps.adapters.coding_adapter import CodingProjectAdapter
import baps.state.state as state_module


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
    state = run_module.create_state(config)
    adapter = CodingProjectAdapter()
    view = adapter.build_create_game_state_view(state, config)
    assert view.content.startswith("=== StateView Start ===")
    assert view.content.endswith("=== StateView End ===")
    assert "--- NorthStar ---" in view.content
    assert "--- State Artifacts ---" in view.content
    assert "## Artifact: main-codebase" in view.content
    assert "kind: coding" in view.content
    assert "No files." in view.content


def test_coding_create_game_state_view_includes_file_contents() -> None:

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(
            id="main-codebase",
            files=(
                state_module.CodeFile(path="src/hello.py", content="def hello():\n    return 'hi'\n"),
            ),
        ),),
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


def test_coding_create_game_state_view_truncates_long_files() -> None:

    long_content = "\n".join(f"line_{i} = {i}" for i in range(100))
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.CodingArtifact(
            id="main-codebase",
            files=(state_module.CodeFile(path="src/big.py", content=long_content),),
        ),),
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
    assert "more lines" in view.content
    assert "line_0 = 0" in view.content
    assert "line_99 = 99" not in view.content
