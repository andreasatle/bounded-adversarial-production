import json
from pathlib import Path

import pytest

from baps.state_sources import (
    MarkdownFileStateSourceAdapter,
    StateManifest,
    StateSourceDeclaration,
    load_state_manifest,
)


def test_state_source_declaration_validation() -> None:
    declaration = StateSourceDeclaration(id="readme", kind="markdown_doc", ref="README.md")
    assert declaration.authority == "context"

    with pytest.raises(ValueError):
        StateSourceDeclaration(id=" ", kind="markdown_doc", ref="README.md")
    with pytest.raises(ValueError):
        StateSourceDeclaration(id="readme", kind=" ", ref="README.md")
    with pytest.raises(ValueError):
        StateSourceDeclaration(id="readme", kind="markdown_doc", ref=" ")
    with pytest.raises(ValueError):
        StateSourceDeclaration(id="readme", kind="markdown_doc", ref="README.md", authority=" ")


def test_state_manifest_validation_and_unique_ids() -> None:
    manifest = StateManifest(
        project_id="baps",
        sources=[StateSourceDeclaration(id="readme", kind="markdown_doc", ref="README.md")],
    )
    assert manifest.project_id == "baps"

    with pytest.raises(ValueError):
        StateManifest(project_id=" ", sources=[StateSourceDeclaration(id="a", kind="markdown_doc", ref="x.md")])
    with pytest.raises(ValueError):
        StateManifest(project_id="baps", sources=[])
    with pytest.raises(ValueError, match="source ids must be unique"):
        StateManifest(
            project_id="baps",
            sources=[
                StateSourceDeclaration(id="dup", kind="markdown_doc", ref="a.md"),
                StateSourceDeclaration(id="dup", kind="markdown_doc", ref="b.md"),
            ],
        )


def test_load_state_manifest_valid(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "project_id": "baps",
                "sources": [
                    {
                        "id": "readme",
                        "kind": "markdown_doc",
                        "ref": "README.md",
                        "authority": "context",
                        "metadata": {"priority": 1},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    manifest = load_state_manifest(path)
    assert manifest.project_id == "baps"
    assert manifest.sources[0].id == "readme"


def test_load_state_manifest_missing_file_fails(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_state_manifest(tmp_path / "missing.json")


def test_load_state_manifest_invalid_json_fails(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_state_manifest(path)


def test_load_state_manifest_invalid_schema_fails(tmp_path: Path) -> None:
    path = tmp_path / "bad-schema.json"
    path.write_text(json.dumps({"project_id": "baps"}), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid StateManifest schema"):
        load_state_manifest(path)


def test_markdown_file_state_source_adapter_reads_markdown(tmp_path: Path) -> None:
    adapter = MarkdownFileStateSourceAdapter()
    file_path = tmp_path / "doc.md"
    file_path.write_text("# Title\n\nBody", encoding="utf-8")
    declaration = StateSourceDeclaration(id="doc", kind="markdown_doc", ref=str(file_path))

    loaded = adapter.load_text(declaration)
    assert loaded == "# Title\n\nBody"


def test_markdown_file_state_source_adapter_unsupported_kind_fails(tmp_path: Path) -> None:
    adapter = MarkdownFileStateSourceAdapter()
    file_path = tmp_path / "doc.md"
    file_path.write_text("content", encoding="utf-8")
    declaration = StateSourceDeclaration(id="doc", kind="text_file", ref=str(file_path))

    with pytest.raises(ValueError, match="unsupported state source kind"):
        adapter.load_text(declaration)


def test_markdown_file_state_source_adapter_missing_file_fails(tmp_path: Path) -> None:
    adapter = MarkdownFileStateSourceAdapter()
    declaration = StateSourceDeclaration(id="doc", kind="markdown_doc", ref=str(tmp_path / "missing.md"))

    with pytest.raises(FileNotFoundError):
        adapter.load_text(declaration)


def test_state_source_metadata_default_isolated() -> None:
    a = StateSourceDeclaration(id="a", kind="markdown_doc", ref="a.md")
    b = StateSourceDeclaration(id="b", kind="markdown_doc", ref="b.md")
    a.metadata["x"] = 1
    assert "x" not in b.metadata


def test_load_checked_in_state_manifest_and_read_sources() -> None:
    manifest_path = Path("examples/state_manifests/baps_project_state.json")
    manifest = load_state_manifest(manifest_path)

    assert manifest.project_id.strip()
    source_ids = {source.id for source in manifest.sources}
    assert "architecture" in source_ids
    assert "future_direction" in source_ids

    adapter = MarkdownFileStateSourceAdapter()
    for source in manifest.sources:
        if source.kind == "markdown_doc":
            loaded = adapter.load_text(source)
            assert loaded.strip()
