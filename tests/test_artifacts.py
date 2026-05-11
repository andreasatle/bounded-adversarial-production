import json
from pathlib import Path

import pytest

from baps.artifacts import ArtifactHandler, DocumentArtifactAdapter
from baps.schemas import Artifact


def test_create_makes_expected_directories_and_metadata(tmp_path: Path) -> None:
    adapter = DocumentArtifactAdapter(tmp_path)
    artifact = Artifact(id="doc-1", type="document", metadata={"owner": "team-a"})

    result = adapter.create(artifact)

    artifact_dir = tmp_path / "doc-1"
    assert (artifact_dir / "current").is_dir()
    assert (artifact_dir / "current" / "main.md").is_file()
    assert (artifact_dir / "versions").is_dir()
    assert (artifact_dir / "changes").is_dir()
    metadata = json.loads((artifact_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata == artifact.model_dump(mode="json")
    assert result.artifact_id == "doc-1"


def test_create_rejects_non_document_type(tmp_path: Path) -> None:
    adapter = DocumentArtifactAdapter(tmp_path)
    artifact = Artifact(id="doc-1", type="code")

    with pytest.raises(ValueError):
        adapter.create(artifact)


def test_create_rejects_existing_artifact_directory(tmp_path: Path) -> None:
    adapter = DocumentArtifactAdapter(tmp_path)
    artifact = Artifact(id="doc-1", type="document")
    (tmp_path / "doc-1").mkdir()

    with pytest.raises(FileExistsError):
        adapter.create(artifact)


def test_snapshot_creates_v001_from_current_contents(tmp_path: Path) -> None:
    adapter = DocumentArtifactAdapter(tmp_path)
    artifact = Artifact(id="doc-1", type="document")
    adapter.create(artifact)
    (tmp_path / "doc-1" / "current" / "note.txt").write_text("hello", encoding="utf-8")

    version = adapter.snapshot(artifact)

    version_dir = tmp_path / "doc-1" / "versions" / "v001"
    assert version.version_id == "v001"
    assert version.path == str(version_dir)
    assert (version_dir / "note.txt").read_text(encoding="utf-8") == "hello"


def test_snapshot_creates_v002_after_v001_exists(tmp_path: Path) -> None:
    adapter = DocumentArtifactAdapter(tmp_path)
    artifact = Artifact(id="doc-1", type="document")
    adapter.create(artifact)
    current = tmp_path / "doc-1" / "current"
    current.joinpath("note.txt").write_text("one", encoding="utf-8")
    first = adapter.snapshot(artifact)
    assert first.version_id == "v001"

    current.joinpath("note.txt").write_text("two", encoding="utf-8")
    second = adapter.snapshot(artifact)
    assert second.version_id == "v002"
    assert (tmp_path / "doc-1" / "versions" / "v002" / "note.txt").read_text(encoding="utf-8") == "two"


def test_snapshot_preserves_current_file_contents(tmp_path: Path) -> None:
    adapter = DocumentArtifactAdapter(tmp_path)
    artifact = Artifact(id="doc-1", type="document")
    adapter.create(artifact)
    current = tmp_path / "doc-1" / "current"
    current.joinpath("a.txt").write_text("A", encoding="utf-8")
    current.joinpath("b.txt").write_text("B", encoding="utf-8")

    adapter.snapshot(artifact)

    version_dir = tmp_path / "doc-1" / "versions" / "v001"
    assert (version_dir / "a.txt").read_text(encoding="utf-8") == "A"
    assert (version_dir / "b.txt").read_text(encoding="utf-8") == "B"


def test_snapshot_rejects_missing_artifact_or_current_directory(tmp_path: Path) -> None:
    adapter = DocumentArtifactAdapter(tmp_path)
    artifact = Artifact(id="doc-1", type="document")

    with pytest.raises(FileNotFoundError):
        adapter.snapshot(artifact)


def test_handler_delegates_create_to_document_adapter(tmp_path: Path) -> None:
    handler = ArtifactHandler(adapters={"document": DocumentArtifactAdapter(tmp_path)})
    artifact = Artifact(id="doc-1", type="document")

    result = handler.create(artifact)

    assert result.artifact_id == "doc-1"
    assert (tmp_path / "doc-1" / "metadata.json").exists()


def test_handler_delegates_snapshot_to_document_adapter(tmp_path: Path) -> None:
    handler = ArtifactHandler(adapters={"document": DocumentArtifactAdapter(tmp_path)})
    artifact = Artifact(id="doc-1", type="document")
    handler.create(artifact)
    (tmp_path / "doc-1" / "current" / "note.txt").write_text("hello", encoding="utf-8")

    version = handler.snapshot(artifact)

    assert version.version_id == "v001"
    assert (tmp_path / "doc-1" / "versions" / "v001" / "note.txt").read_text(encoding="utf-8") == "hello"


def test_handler_rejects_unknown_artifact_type_on_create(tmp_path: Path) -> None:
    handler = ArtifactHandler(adapters={"document": DocumentArtifactAdapter(tmp_path)})
    artifact = Artifact(id="doc-1", type="unknown")

    with pytest.raises(ValueError):
        handler.create(artifact)


def test_handler_rejects_unknown_artifact_type_on_snapshot(tmp_path: Path) -> None:
    handler = ArtifactHandler(adapters={"document": DocumentArtifactAdapter(tmp_path)})
    artifact = Artifact(id="doc-1", type="unknown")

    with pytest.raises(ValueError):
        handler.snapshot(artifact)


def test_propose_change_stores_proposed_and_change_json(tmp_path: Path) -> None:
    adapter = DocumentArtifactAdapter(tmp_path)
    artifact = Artifact(id="doc-1", type="document")
    adapter.create(artifact)
    (tmp_path / "doc-1" / "current" / "main.md").write_text("old\n", encoding="utf-8")

    change = adapter.propose_change(artifact=artifact, description="update body", new_content="new\n")

    change_dir = tmp_path / "doc-1" / "changes" / change.change_id
    assert (change_dir / "proposed.md").read_text(encoding="utf-8") == "new\n"
    payload = json.loads((change_dir / "change.json").read_text(encoding="utf-8"))
    assert payload["artifact_id"] == "doc-1"
    assert payload["change_id"] == "c001"
    assert payload["description"] == "update body"


def test_propose_change_creates_non_empty_unified_diff(tmp_path: Path) -> None:
    adapter = DocumentArtifactAdapter(tmp_path)
    artifact = Artifact(id="doc-1", type="document")
    adapter.create(artifact)
    (tmp_path / "doc-1" / "current" / "main.md").write_text("old\n", encoding="utf-8")

    change = adapter.propose_change(artifact=artifact, description="update body", new_content="new\n")

    assert change.diff is not None
    assert change.diff.strip() != ""
    assert "--- current/main.md" in change.diff
    assert "+++ proposed/main.md" in change.diff


def test_propose_change_uses_unversioned_when_current_version_is_none(tmp_path: Path) -> None:
    adapter = DocumentArtifactAdapter(tmp_path)
    artifact = Artifact(id="doc-1", type="document")
    adapter.create(artifact)

    change = adapter.propose_change(artifact=artifact, description="update body", new_content="new\n")
    assert change.base_version == "unversioned"


def test_apply_change_replaces_current_and_creates_new_version(tmp_path: Path) -> None:
    adapter = DocumentArtifactAdapter(tmp_path)
    artifact = Artifact(id="doc-1", type="document")
    adapter.create(artifact)
    current_main = tmp_path / "doc-1" / "current" / "main.md"
    current_main.write_text("old\n", encoding="utf-8")
    change = adapter.propose_change(artifact=artifact, description="apply me", new_content="new\n")

    version = adapter.apply_change(artifact=artifact, change_id=change.change_id)

    assert current_main.read_text(encoding="utf-8") == "new\n"
    assert version.version_id == "v001"
    assert (tmp_path / "doc-1" / "versions" / "v001" / "main.md").read_text(encoding="utf-8") == "new\n"


def test_rollback_restores_current_from_previous_version(tmp_path: Path) -> None:
    adapter = DocumentArtifactAdapter(tmp_path)
    artifact = Artifact(id="doc-1", type="document")
    adapter.create(artifact)
    current_main = tmp_path / "doc-1" / "current" / "main.md"
    current_main.write_text("first\n", encoding="utf-8")
    adapter.snapshot(artifact)
    current_main.write_text("second\n", encoding="utf-8")
    adapter.snapshot(artifact)

    restored = adapter.rollback(artifact=artifact, version_id="v001")

    assert restored.version_id == "v001"
    assert current_main.read_text(encoding="utf-8") == "first\n"


def test_handler_delegates_propose_apply_and_rollback(tmp_path: Path) -> None:
    handler = ArtifactHandler(adapters={"document": DocumentArtifactAdapter(tmp_path)})
    artifact = Artifact(id="doc-1", type="document")
    handler.create(artifact)
    current_main = tmp_path / "doc-1" / "current" / "main.md"
    current_main.write_text("old\n", encoding="utf-8")

    change = handler.propose_change(artifact=artifact, description="update", new_content="new\n")
    version = handler.apply_change(artifact=artifact, change_id=change.change_id)
    assert version.version_id == "v001"
    current_main.write_text("broken\n", encoding="utf-8")
    restored = handler.rollback(artifact=artifact, version_id="v001")

    assert restored.version_id == "v001"
    assert current_main.read_text(encoding="utf-8") == "new\n"


def test_handler_rejects_unknown_artifact_type_for_new_methods(tmp_path: Path) -> None:
    handler = ArtifactHandler(adapters={"document": DocumentArtifactAdapter(tmp_path)})
    artifact = Artifact(id="doc-1", type="unknown")

    with pytest.raises(ValueError):
        handler.propose_change(artifact=artifact, description="d", new_content="n")
    with pytest.raises(ValueError):
        handler.apply_change(artifact=artifact, change_id="c001")
    with pytest.raises(ValueError):
        handler.rollback(artifact=artifact, version_id="v001")
