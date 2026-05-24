from __future__ import annotations

import json
from pathlib import Path

import pytest

import baps.state as state_module
from baps.audit_adapter import (
    AuditProjectAdapter,
    _embed_source_path,
    _extract_source_path,
    _collect_source_files,
    _fence_lang,
    _render_source_listing,
    _render_source_content,
    build_audit_create_game_state_view,
    build_audit_play_game_state_view,
)
from baps.models import ToolCall


# ---------------------------------------------------------------------------
# Source path embedding / extraction
# ---------------------------------------------------------------------------

def test_embed_and_extract_source_path_round_trips() -> None:
    embedded = _embed_source_path("# Audit Goal\n\nFind bugs.", "/some/path")
    state = _make_state_with_northstar(embedded)
    result = _extract_source_path(state)
    assert result == Path("/some/path")


def test_extract_source_path_returns_none_when_marker_absent() -> None:
    state = _make_state_with_northstar("# No marker here")
    assert _extract_source_path(state) is None


def test_embed_source_path_preserves_northstar_content() -> None:
    embedded = _embed_source_path("# Goal\n\nSecurity audit.", "/tmp/src")
    assert "# Goal" in embedded
    assert "Security audit." in embedded


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------

def test_collect_source_files_finds_py_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1")
    (tmp_path / "b.py").write_text("y = 2")
    (tmp_path / "c.txt").write_text("ignored")
    files = _collect_source_files(tmp_path, ("*.py",))
    names = {f.name for f in files}
    assert names == {"a.py", "b.py"}


def test_collect_source_files_recurses_into_subdirs(tmp_path: Path) -> None:
    sub = tmp_path / "src"
    sub.mkdir()
    (sub / "mod.py").write_text("pass")
    files = _collect_source_files(tmp_path, ("*.py",))
    assert any(f.name == "mod.py" for f in files)


def test_collect_source_files_returns_sorted(tmp_path: Path) -> None:
    for name in ["z.py", "a.py", "m.py"]:
        (tmp_path / name).write_text("")
    files = _collect_source_files(tmp_path, ("*.py",))
    names = [f.name for f in files]
    assert names == sorted(names)


def test_collect_source_files_no_duplicates_across_patterns(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("")
    files = _collect_source_files(tmp_path, ("*.py", "*.py"))
    assert len(files) == 1


# ---------------------------------------------------------------------------
# Source rendering
# ---------------------------------------------------------------------------

def test_render_source_listing_shows_paths_and_line_counts(tmp_path: Path) -> None:
    f = tmp_path / "foo.py"
    f.write_text("line1\nline2\nline3\n")
    files = _collect_source_files(tmp_path, ("*.py",))
    listing = _render_source_listing(files, tmp_path)
    assert "foo.py" in listing
    assert "3 lines" in listing


def test_render_source_listing_empty_when_no_files(tmp_path: Path) -> None:
    listing = _render_source_listing([], tmp_path)
    assert "no source files" in listing


def test_render_source_content_includes_file_content(tmp_path: Path) -> None:
    f = tmp_path / "mod.py"
    f.write_text("def foo():\n    return 42\n")
    files = [f]
    content = _render_source_content(files, tmp_path, max_file_lines=50, max_total_lines=500)
    assert "mod.py" in content
    assert "def foo()" in content
    assert "return 42" in content


def test_render_source_content_truncates_long_files(tmp_path: Path) -> None:
    f = tmp_path / "big.py"
    f.write_text("\n".join(f"line{i}" for i in range(200)))
    files = [f]
    content = _render_source_content(files, tmp_path, max_file_lines=10, max_total_lines=500)
    assert "more lines" in content
    assert "line0" in content
    assert "line199" not in content


def test_render_source_content_stops_at_total_budget(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"mod{i}.py").write_text("\n".join(f"x{i}_{j}" for j in range(100)))
    files = _collect_source_files(tmp_path, ("*.py",))
    content = _render_source_content(files, tmp_path, max_file_lines=100, max_total_lines=250)
    assert "total line budget reached" in content


# ---------------------------------------------------------------------------
# AuditProjectAdapter.create_initial_state
# ---------------------------------------------------------------------------

def test_audit_adapter_create_initial_state_requires_source_path() -> None:
    adapter = AuditProjectAdapter()
    with pytest.raises(ValueError, match="source_path"):
        adapter.create_initial_state({
            "artifact_id": "report",
            "northstar_markdown": "# Goal",
        })


def test_audit_adapter_create_initial_state_embeds_source_path() -> None:
    adapter = AuditProjectAdapter()
    state = adapter.create_initial_state({
        "artifact_id": "report",
        "northstar_markdown": "# Goal\n\nFind bugs.",
        "source_path": "/tmp/src",
    })
    recovered = _extract_source_path(state)
    assert recovered == Path("/tmp/src")


def test_audit_adapter_create_initial_state_has_empty_document_artifact() -> None:
    adapter = AuditProjectAdapter()
    state = adapter.create_initial_state({
        "artifact_id": "audit-report",
        "northstar_markdown": "# Goal",
        "source_path": "/tmp/src",
    })
    artifact = next(a for a in state.artifacts if a.id == "audit-report")
    assert isinstance(artifact, state_module.DocumentArtifact)
    assert artifact.sections == ()


# ---------------------------------------------------------------------------
# CreateGame StateView
# ---------------------------------------------------------------------------

def test_audit_create_game_state_view_includes_northstar(tmp_path: Path) -> None:
    adapter = AuditProjectAdapter()
    state = adapter.create_initial_state({
        "artifact_id": "report",
        "northstar_markdown": "# Security Audit Goal\n\nFind vulnerabilities.",
        "source_path": str(tmp_path),
    })
    config = {"artifact_id": "report", "source_path": str(tmp_path)}
    view = adapter.build_create_game_state_view(state, config)
    assert "Security Audit Goal" in view.content


def test_audit_create_game_state_view_includes_source_listing(tmp_path: Path) -> None:
    (tmp_path / "models.py").write_text("class Foo: pass\n")
    adapter = AuditProjectAdapter()
    state = adapter.create_initial_state({
        "artifact_id": "report",
        "northstar_markdown": "# Goal",
        "source_path": str(tmp_path),
    })
    config = {"artifact_id": "report", "source_path": str(tmp_path)}
    view = adapter.build_create_game_state_view(state, config)
    assert "models.py" in view.content


def test_audit_create_game_state_view_shows_existing_findings(tmp_path: Path) -> None:
    adapter = AuditProjectAdapter()
    state = adapter.create_initial_state({
        "artifact_id": "report",
        "northstar_markdown": "# Goal",
        "source_path": str(tmp_path),
    })
    state = _append_finding(state, "report", "SQL Injection", "Found in db.py line 42.")
    config = {"artifact_id": "report", "source_path": str(tmp_path)}
    view = adapter.build_create_game_state_view(state, config)
    assert "SQL Injection" in view.content


# ---------------------------------------------------------------------------
# PlayGame StateView
# ---------------------------------------------------------------------------

def test_audit_play_game_state_view_includes_source_content(tmp_path: Path) -> None:
    (tmp_path / "run.py").write_text("def run(): pass\n")
    adapter = AuditProjectAdapter()
    state = adapter.create_initial_state({
        "artifact_id": "report",
        "northstar_markdown": "# Goal",
        "source_path": str(tmp_path),
    })
    game_spec = state_module.GameSpec(
        objective="Audit run.py",
        target_artifact_id="report",
        allowed_delta_type="DeltaDocumentState",
        success_condition="finding with evidence",
    )
    view = adapter.build_state_view(state, game_spec)
    assert "def run()" in view.content
    assert "run.py" in view.content


def test_audit_play_game_state_view_source_read_only_label(tmp_path: Path) -> None:
    adapter = AuditProjectAdapter()
    state = adapter.create_initial_state({
        "artifact_id": "report",
        "northstar_markdown": "# Goal",
        "source_path": str(tmp_path),
    })
    game_spec = state_module.GameSpec(
        objective="Audit",
        target_artifact_id="report",
        allowed_delta_type="DeltaDocumentState",
        success_condition="finding",
    )
    view = adapter.build_state_view(state, game_spec)
    assert "read-only" in view.content


def test_audit_play_game_state_view_missing_source_path_graceful(tmp_path: Path) -> None:
    adapter = AuditProjectAdapter()
    state = adapter.create_initial_state({
        "artifact_id": "report",
        "northstar_markdown": "# Goal",
        "source_path": str(tmp_path / "nonexistent"),
    })
    game_spec = state_module.GameSpec(
        objective="Audit",
        target_artifact_id="report",
        allowed_delta_type="DeltaDocumentState",
        success_condition="finding",
    )
    view = adapter.build_state_view(state, game_spec)
    assert "not configured or does not exist" in view.content


# ---------------------------------------------------------------------------
# Blue prompt
# ---------------------------------------------------------------------------

def test_audit_blue_prompt_includes_finding_format(tmp_path: Path) -> None:
    adapter = AuditProjectAdapter()
    state = adapter.create_initial_state({
        "artifact_id": "report",
        "northstar_markdown": "# Goal",
        "source_path": str(tmp_path),
    })
    game_spec = state_module.GameSpec(
        objective="Find injection vulnerabilities",
        target_artifact_id="report",
        allowed_delta_type="DeltaDocumentState",
        success_condition="finding with evidence",
    )
    view = adapter.build_state_view(state, game_spec)
    prompt = adapter.render_blue_prompt(view, game_spec, 1, None)
    assert "Location" in prompt
    assert "Severity" in prompt
    assert "Evidence" in prompt
    assert "Recommendation" in prompt


# ---------------------------------------------------------------------------
# Red / Referee supplements
# ---------------------------------------------------------------------------

def test_audit_red_prompt_supplement_is_security_focused(tmp_path: Path) -> None:
    adapter = AuditProjectAdapter()
    state = adapter.create_initial_state({
        "artifact_id": "report",
        "northstar_markdown": "# Goal",
        "source_path": str(tmp_path),
    })
    game_spec = state_module.GameSpec(
        objective="Audit",
        target_artifact_id="report",
        allowed_delta_type="DeltaDocumentState",
        success_condition="finding",
    )
    view = adapter.build_state_view(state, game_spec)
    delta = state_module.DeltaDocumentState(
        artifact_id="report",
        operation="append_section",
        payload=state_module.AppendSectionDelta(
            section=state_module.Section(title="Finding", body="body")
        ),
    )
    supplement = adapter.render_red_prompt_supplement(view, game_spec, delta, None)
    assert "exploitable" in supplement
    assert "Severity" in supplement
    assert "Evidence" in supplement


def test_audit_referee_prompt_supplement_has_accept_reject_criteria(tmp_path: Path) -> None:
    adapter = AuditProjectAdapter()
    state = adapter.create_initial_state({
        "artifact_id": "report",
        "northstar_markdown": "# Goal",
        "source_path": str(tmp_path),
    })
    game_spec = state_module.GameSpec(
        objective="Audit",
        target_artifact_id="report",
        allowed_delta_type="DeltaDocumentState",
        success_condition="finding",
    )
    view = adapter.build_state_view(state, game_spec)
    delta = state_module.DeltaDocumentState(
        artifact_id="report",
        operation="append_section",
        payload=state_module.AppendSectionDelta(
            section=state_module.Section(title="Finding", body="body")
        ),
    )
    supplement = adapter.render_referee_prompt_supplement(view, game_spec, delta, None)
    assert "Accept" in supplement
    assert "Reject" in supplement


# ---------------------------------------------------------------------------
# Delta parsing / tool_call_to_delta
# ---------------------------------------------------------------------------

def test_audit_parse_blue_delta_append_section() -> None:
    adapter = AuditProjectAdapter()
    text = (
        '{"artifact_id": "report", "operation": "append_section", '
        '"payload": {"section": {"title": "XSS", "body": "Found in templates."}}}'
    )
    delta = adapter.parse_blue_delta(text)
    assert isinstance(delta, state_module.DeltaDocumentState)
    assert delta.payload.section.title == "XSS"


def test_audit_tool_call_append_section() -> None:
    adapter = AuditProjectAdapter()
    tool_call = ToolCall(
        name="append_section",
        arguments={"artifact_id": "report", "title": "SSRF", "body": "Found in http_client.py."},
    )
    delta = adapter.tool_call_to_delta(tool_call)
    assert isinstance(delta, state_module.DeltaDocumentState)
    assert delta.payload.section.title == "SSRF"


def test_audit_tool_call_modify_section() -> None:
    adapter = AuditProjectAdapter()
    tool_call = ToolCall(
        name="modify_section",
        arguments={
            "artifact_id": "report",
            "section_title": "SSRF",
            "new_body": "Updated evidence.",
        },
    )
    delta = adapter.tool_call_to_delta(tool_call)
    assert isinstance(delta, state_module.DeltaModifyDocumentState)
    assert delta.payload.section_title == "SSRF"


def test_audit_tool_call_unexpected_tool_raises() -> None:
    adapter = AuditProjectAdapter()
    tool_call = ToolCall(name="write_file", arguments={"path": "evil.py", "content": "rm -rf"})
    with pytest.raises(ValueError, match="unexpected tool"):
        adapter.tool_call_to_delta(tool_call)


def test_audit_tool_call_no_finding_produces_append_section() -> None:
    adapter = AuditProjectAdapter()
    tool_call = ToolCall(
        name="no_finding",
        arguments={
            "artifact_id": "report",
            "file": "src/baps/state.py",
            "rationale": "Checked State.apply_update and StateService boundary — no bypass paths found.",
        },
    )
    delta = adapter.tool_call_to_delta(tool_call)
    assert isinstance(delta, state_module.DeltaDocumentState)
    assert delta.operation == "append_section"
    assert delta.payload.section.title == "Audited: src/baps/state.py"
    assert "no bypass paths found" in delta.payload.section.body


def test_audit_tool_call_no_finding_missing_file_raises() -> None:
    adapter = AuditProjectAdapter()
    tool_call = ToolCall(
        name="no_finding",
        arguments={"artifact_id": "report", "rationale": "Looks fine."},
    )
    with pytest.raises(ValueError, match="missing required tool argument"):
        adapter.tool_call_to_delta(tool_call)


def test_audit_tool_call_no_finding_missing_rationale_raises() -> None:
    adapter = AuditProjectAdapter()
    tool_call = ToolCall(
        name="no_finding",
        arguments={"artifact_id": "report", "file": "run.py"},
    )
    with pytest.raises(ValueError, match="missing required tool argument"):
        adapter.tool_call_to_delta(tool_call)


def test_audit_parse_blue_delta_no_finding_json() -> None:
    adapter = AuditProjectAdapter()
    text = json.dumps({
        "artifact_id": "report",
        "operation": "no_finding",
        "file": "src/baps/run.py",
        "rationale": "Checked orchestration loop — all mutation goes through StateService.",
    })
    delta = adapter.parse_blue_delta(text)
    assert isinstance(delta, state_module.DeltaDocumentState)
    assert delta.operation == "append_section"
    assert delta.payload.section.title == "Audited: src/baps/run.py"
    assert "StateService" in delta.payload.section.body


def test_audit_parse_blue_delta_no_finding_missing_fields_raises() -> None:
    adapter = AuditProjectAdapter()
    text = json.dumps({
        "artifact_id": "report",
        "operation": "no_finding",
        "file": "run.py",
    })
    with pytest.raises(ValueError, match="no_finding delta missing required field"):
        adapter.parse_blue_delta(text)


def test_audit_blue_tools_includes_no_finding() -> None:
    adapter = AuditProjectAdapter()
    tools = adapter.build_blue_tools()
    names = {t.name for t in tools}
    assert "no_finding" in names
    assert "append_section" in names
    assert "modify_section" in names


def test_audit_no_finding_tool_requires_file_and_rationale() -> None:
    adapter = AuditProjectAdapter()
    tools = {t.name: t for t in adapter.build_blue_tools()}
    no_finding = tools["no_finding"]
    required = no_finding.parameters["required"]
    assert "file" in required
    assert "rationale" in required
    assert "artifact_id" in required


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def test_audit_export_writes_markdown(tmp_path: Path) -> None:
    adapter = AuditProjectAdapter()
    state = adapter.create_initial_state({
        "artifact_id": "report",
        "northstar_markdown": "# Goal",
        "source_path": str(tmp_path),
    })
    state = _append_finding(state, "report", "Buffer Overflow", "Found in parser.c line 99.")
    out = tmp_path / "report.md"
    changed = adapter.export_state(state, out, "report")
    assert changed is True
    content = out.read_text(encoding="utf-8")
    assert "Buffer Overflow" in content
    assert "Found in parser.c" in content


def test_audit_export_unchanged_returns_false(tmp_path: Path) -> None:
    adapter = AuditProjectAdapter()
    state = adapter.create_initial_state({
        "artifact_id": "report",
        "northstar_markdown": "# Goal",
        "source_path": str(tmp_path),
    })
    state = _append_finding(state, "report", "XSS", "Found in templates.")
    out = tmp_path / "report.md"
    adapter.export_state(state, out, "report")
    changed = adapter.export_state(state, out, "report")
    assert changed is False


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_audit_adapter_registered_in_default_adapters() -> None:
    from baps.project_adapter import resolve_project_type_adapter
    adapter = resolve_project_type_adapter("audit")
    assert isinstance(adapter, AuditProjectAdapter)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state_with_northstar(northstar_markdown: str) -> state_module.State:
    from baps.document_adapter import build_northstar_artifact_from_markdown
    northstar_artifact = build_northstar_artifact_from_markdown(northstar_markdown)
    return state_module.State(
        northstar=state_module.NorthStar(artifacts=(northstar_artifact,)),
        artifacts=(state_module.DocumentArtifact(id="report", sections=()),),
    )


def _append_finding(
    state: state_module.State, artifact_id: str, title: str, body: str
) -> state_module.State:
    from baps.state_service import StateService
    from baps.state_store import JsonStateStore
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        store = JsonStateStore(Path(tmpdir) / "state.json")
        store.save(state)
        from baps.state import build_default_state_artifact_registry
        service = StateService(store, build_default_state_artifact_registry())
        delta = state_module.DeltaDocumentState(
            artifact_id=artifact_id,
            operation="append_section",
            payload=state_module.AppendSectionDelta(
                section=state_module.Section(title=title, body=body)
            ),
        )
        from baps.document_adapter import derive_document_state_update_from_delta
        proposal = derive_document_state_update_from_delta(delta)
        return service.apply_update(proposal)


# ---------------------------------------------------------------------------
# _fence_lang — file-type agnostic fencing
# ---------------------------------------------------------------------------

def test_fence_lang_known_extensions() -> None:
    assert _fence_lang(Path("foo.py")) == "python"
    assert _fence_lang(Path("foo.go")) == "go"
    assert _fence_lang(Path("foo.rs")) == "rust"
    assert _fence_lang(Path("foo.yaml")) == "yaml"
    assert _fence_lang(Path("foo.yml")) == "yaml"
    assert _fence_lang(Path("foo.json")) == "json"
    assert _fence_lang(Path("foo.tf")) == "hcl"
    assert _fence_lang(Path("foo.sh")) == "bash"
    assert _fence_lang(Path("foo.md")) == "markdown"


def test_fence_lang_unknown_extension_returns_empty() -> None:
    assert _fence_lang(Path("foo.xyz")) == ""
    assert _fence_lang(Path("Makefile")) == ""


def test_render_source_content_uses_correct_fence_for_yaml(tmp_path: Path) -> None:
    f = tmp_path / "config.yaml"
    f.write_text("key: value\n")
    content = _render_source_content([f], tmp_path, max_file_lines=50, max_total_lines=500)
    assert "```yaml" in content


def test_render_source_content_uses_correct_fence_for_python(tmp_path: Path) -> None:
    f = tmp_path / "mod.py"
    f.write_text("x = 1\n")
    content = _render_source_content([f], tmp_path, max_file_lines=50, max_total_lines=500)
    assert "```python" in content


def test_render_source_content_unknown_extension_uses_empty_fence(tmp_path: Path) -> None:
    f = tmp_path / "Makefile"
    f.write_text("all:\n\techo done\n")
    content = _render_source_content([f], tmp_path, max_file_lines=50, max_total_lines=500)
    assert "```\n" in content


# ---------------------------------------------------------------------------
# Default patterns cover multiple file types
# ---------------------------------------------------------------------------

def test_default_source_patterns_cover_common_types(tmp_path: Path) -> None:
    from baps.audit_adapter import _DEFAULT_SOURCE_PATTERNS
    for name in ["mod.py", "main.go", "lib.rs", "app.js", "infra.tf", "config.yaml"]:
        (tmp_path / name).write_text("content")
    files = _collect_source_files(tmp_path, _DEFAULT_SOURCE_PATTERNS)
    names = {f.name for f in files}
    assert {"mod.py", "main.go", "lib.rs", "app.js", "infra.tf", "config.yaml"}.issubset(names)
