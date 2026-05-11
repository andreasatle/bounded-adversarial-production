import json
from pathlib import Path

import pytest

from baps.artifacts import DocumentArtifactAdapter
from baps.schemas import Artifact


def test_create_makes_expected_directories_and_metadata(tmp_path: Path) -> None:
    adapter = DocumentArtifactAdapter(tmp_path)
    artifact = Artifact(id="doc-1", type="document", metadata={"owner": "team-a"})

    result = adapter.create(artifact)

    artifact_dir = tmp_path / "doc-1"
    assert (artifact_dir / "current").is_dir()
    assert (artifact_dir / "versions").is_dir()
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
