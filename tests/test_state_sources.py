import json
from pathlib import Path

import pytest

from baps.state_sources import (
    JsonlEventLogStateSourceAdapter,
    MarkdownFileStateSourceAdapter,
    StateManifest,
    StateSourceDeclaration,
    load_state_manifest,
    resolve_state_context,
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


def test_resolve_state_context_empty_source_ids_returns_empty_string() -> None:
    manifest = StateManifest(
        project_id="baps",
        sources=[StateSourceDeclaration(id="readme", kind="markdown_doc", ref="README.md")],
    )
    adapter = MarkdownFileStateSourceAdapter()
    assert resolve_state_context(manifest, [], adapter) == ""


def test_resolve_state_context_resolves_one_source(tmp_path: Path) -> None:
    file_path = tmp_path / "one.md"
    file_path.write_text("one-content", encoding="utf-8")
    manifest = StateManifest(
        project_id="baps",
        sources=[StateSourceDeclaration(id="one", kind="markdown_doc", ref=str(file_path), authority="context")],
    )
    adapter = MarkdownFileStateSourceAdapter()

    context = resolve_state_context(manifest, ["one"], adapter)
    assert "===== STATE SOURCE: one (markdown_doc, authority=context) =====" in context
    assert "one-content" in context


def test_resolve_state_context_resolves_multiple_sources_in_requested_order(tmp_path: Path) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("first-content", encoding="utf-8")
    second.write_text("second-content", encoding="utf-8")

    manifest = StateManifest(
        project_id="baps",
        sources=[
            StateSourceDeclaration(id="first", kind="markdown_doc", ref=str(first), authority="context"),
            StateSourceDeclaration(id="second", kind="markdown_doc", ref=str(second), authority="descriptive"),
        ],
    )
    adapter = MarkdownFileStateSourceAdapter()

    context = resolve_state_context(manifest, ["second", "first"], adapter)
    idx_second = context.find("STATE SOURCE: second")
    idx_first = context.find("STATE SOURCE: first")
    assert idx_second != -1
    assert idx_first != -1
    assert idx_second < idx_first


def test_resolve_state_context_missing_source_id_raises_value_error(tmp_path: Path) -> None:
    file_path = tmp_path / "one.md"
    file_path.write_text("one-content", encoding="utf-8")
    manifest = StateManifest(
        project_id="baps",
        sources=[StateSourceDeclaration(id="one", kind="markdown_doc", ref=str(file_path))],
    )
    adapter = MarkdownFileStateSourceAdapter()

    with pytest.raises(ValueError, match="state source id not found in manifest: missing"):
        resolve_state_context(manifest, ["missing"], adapter)


def test_resolve_state_context_missing_file_error_propagates(tmp_path: Path) -> None:
    missing = tmp_path / "missing.md"
    manifest = StateManifest(
        project_id="baps",
        sources=[StateSourceDeclaration(id="missing", kind="markdown_doc", ref=str(missing))],
    )
    adapter = MarkdownFileStateSourceAdapter()

    with pytest.raises(FileNotFoundError):
        resolve_state_context(manifest, ["missing"], adapter)


def test_resolve_state_context_checked_in_manifest_architecture_and_future_direction() -> None:
    manifest = load_state_manifest(Path("examples/state_manifests/baps_project_state.json"))
    adapter = MarkdownFileStateSourceAdapter()

    context = resolve_state_context(manifest, ["architecture", "future_direction"], adapter)
    assert "STATE SOURCE: architecture" in context
    assert "STATE SOURCE: future_direction" in context
    assert "authority=descriptive" in context
    assert "authority=directional" in context


def test_jsonl_event_log_state_source_adapter_reads_jsonl_exactly(tmp_path: Path) -> None:
    adapter = JsonlEventLogStateSourceAdapter()
    file_path = tmp_path / "events.jsonl"
    raw_content = (
        '{"id":"g:run:r0001:game_started","type":"game_started","payload":{"game_id":"g","run_id":"run"}}\n'
        '{"id":"g:run:game_completed","type":"game_completed","payload":{"game_id":"g","run_id":"run"}}\n'
    )
    file_path.write_text(raw_content, encoding="utf-8")
    declaration = StateSourceDeclaration(id="traces", kind="jsonl_event_log", ref=str(file_path))

    loaded = adapter.load_text(declaration)
    assert loaded == raw_content


def test_jsonl_event_log_state_source_adapter_unsupported_kind_fails(tmp_path: Path) -> None:
    adapter = JsonlEventLogStateSourceAdapter()
    file_path = tmp_path / "events.jsonl"
    file_path.write_text("{}", encoding="utf-8")
    declaration = StateSourceDeclaration(id="traces", kind="markdown_doc", ref=str(file_path))

    with pytest.raises(ValueError, match="unsupported state source kind for jsonl event log adapter"):
        adapter.load_text(declaration)


def test_jsonl_event_log_state_source_adapter_missing_file_fails(tmp_path: Path) -> None:
    adapter = JsonlEventLogStateSourceAdapter()
    declaration = StateSourceDeclaration(
        id="traces",
        kind="jsonl_event_log",
        ref=str(tmp_path / "missing.jsonl"),
    )

    with pytest.raises(FileNotFoundError):
        adapter.load_text(declaration)


def test_resolve_state_context_with_jsonl_event_log_adapter(tmp_path: Path) -> None:
    file_path = tmp_path / "events.jsonl"
    raw_content = '{"id":"e1","type":"x","payload":{}}\n'
    file_path.write_text(raw_content, encoding="utf-8")
    manifest = StateManifest(
        project_id="baps",
        sources=[
            StateSourceDeclaration(
                id="game_traces",
                kind="jsonl_event_log",
                ref=str(file_path),
                authority="evidence",
            )
        ],
    )
    adapter = JsonlEventLogStateSourceAdapter()

    context = resolve_state_context(manifest, ["game_traces"], adapter)
    assert "===== STATE SOURCE: game_traces (jsonl_event_log, authority=evidence) =====" in context
    assert raw_content in context
