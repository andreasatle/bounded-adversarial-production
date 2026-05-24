from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from baps.models import ToolCall, ToolDefinition
from baps.northstar_projection import ProjectionType, StateView
from baps.project_adapter import (
    VerificationResult,
    _config_artifact_id,
    _config_northstar_markdown,
    render_blue_prompt_core,
)
from baps.state import (
    DeltaState,
    DocumentArtifact,
    GameSpec,
    NorthStar,
    State,
    StateUpdateProposal,
)
from baps.document_adapter import (
    build_northstar_artifact_from_markdown,
    document_artifact_from_state,
    parse_document_delta_json,
    derive_document_state_update_from_delta,
    render_document_artifact_markdown,
)


_SOURCE_PATH_MARKER = "<!-- audit:source_path="
_DEFAULT_SOURCE_PATTERNS = (
    "*.py", "*.go", "*.rs", "*.js", "*.ts", "*.java", "*.c", "*.cpp", "*.h",
    "*.yaml", "*.yml", "*.json", "*.toml", "*.tf", "*.sh", "*.md", "*.txt",
)
_DEFAULT_MAX_FILE_LINES = 150

_FENCE_LANGUAGE: dict[str, str] = {
    ".py": "python", ".go": "go", ".rs": "rust", ".js": "javascript",
    ".ts": "typescript", ".java": "java", ".c": "c", ".cpp": "cpp", ".h": "c",
    ".yaml": "yaml", ".yml": "yaml", ".json": "json", ".toml": "toml",
    ".tf": "hcl", ".sh": "bash", ".md": "markdown",
}


def _fence_lang(path: Path) -> str:
    return _FENCE_LANGUAGE.get(path.suffix.lower(), "")
_DEFAULT_MAX_TOTAL_LINES = 3000


def _embed_source_path(northstar_markdown: str, source_path: str) -> str:
    return f"{_SOURCE_PATH_MARKER}{source_path} -->\n\n{northstar_markdown}"


def _extract_source_path(state: State) -> Path | None:
    content = state.northstar.render_content()
    if _SOURCE_PATH_MARKER not in content:
        return None
    start = content.index(_SOURCE_PATH_MARKER) + len(_SOURCE_PATH_MARKER)
    end = content.find(" -->", start)
    if end == -1:
        return None
    return Path(content[start:end])


def _collect_source_files(
    source_path: Path, patterns: tuple[str, ...]
) -> list[Path]:
    seen: set[Path] = set()
    files: list[Path] = []
    for pattern in patterns:
        for candidate in sorted(source_path.rglob(pattern)):
            if candidate.is_file() and candidate not in seen:
                seen.add(candidate)
                files.append(candidate)
    return files


def _render_source_listing(files: list[Path], source_path: Path) -> str:
    if not files:
        return "  (no source files found)"
    lines = []
    for f in files:
        rel = f.relative_to(source_path)
        try:
            line_count = len(f.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            line_count = 0
        lines.append(f"  {rel} ({line_count} lines)")
    return "\n".join(lines)


def _render_source_content(
    files: list[Path],
    source_path: Path,
    max_file_lines: int,
    max_total_lines: int,
) -> str:
    if not files:
        return "(no source files found)"
    parts: list[str] = []
    total = 0
    for f in files:
        rel = f.relative_to(source_path)
        if total >= max_total_lines:
            parts.append(f"### {rel}\n\n(omitted — total line budget reached)")
            continue
        try:
            raw = f.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            parts.append(f"### {rel}\n\n(unreadable: {exc})")
            continue
        lines = raw.splitlines()
        if len(lines) > max_file_lines:
            body = "\n".join(lines[:max_file_lines])
            body += f"\n... ({len(lines) - max_file_lines} more lines)"
            total += max_file_lines
        else:
            body = raw
            total += len(lines)
        lang = _fence_lang(f)
        parts.append(f"### {rel}\n\n```{lang}\n{body}\n```")
    return "\n\n".join(parts)


def build_audit_create_game_state_view(state: State, config: dict[str, Any]) -> StateView:
    artifact_id = _config_artifact_id(config)
    artifact = document_artifact_from_state(state, artifact_id)
    northstar_content = state.northstar.render_content()

    source_path = _extract_source_path(state)
    if source_path is not None and source_path.exists():
        patterns = tuple(config.get("source_include", _DEFAULT_SOURCE_PATTERNS))
        files = _collect_source_files(source_path, patterns)
        source_block = _render_source_listing(files, source_path)
        source_header = f"Source root: {source_path}"
    else:
        source_block = "(source_path not configured or does not exist)"
        source_header = "Source root: (unknown)"

    section_lines: list[str] = []
    if artifact.sections:
        for section in artifact.sections:
            section_lines.append(f"### {section.title}")
            section_lines.append(section.body[:300] + ("..." if len(section.body) > 300 else ""))
            section_lines.append("")
    else:
        section_lines.append("No findings yet.")

    content = "\n".join([
        "=== StateView Start ===",
        "",
        "--- NorthStar ---",
        "",
        northstar_content if northstar_content else "No NorthStar content.",
        "",
        "--- Source Files ---",
        "",
        source_header,
        source_block,
        "",
        "--- Audit Report (current) ---",
        "",
        f"## Artifact: {artifact.id}",
        f"findings so far: {len(artifact.sections)}",
        "",
        *section_lines,
        "=== StateView End ===",
    ]).rstrip()

    input_fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return StateView(
        id=f"state-view:create-game:{artifact.id}:{input_fingerprint[:12]}",
        projection_type=ProjectionType.NORTH_STAR,
        content=content,
        input_fingerprint=input_fingerprint,
        metadata={
            "target_artifact_id": artifact.id,
            "findings_count": len(artifact.sections),
        },
    )


def build_audit_play_game_state_view(state: State, game_spec: GameSpec) -> StateView:
    artifact = document_artifact_from_state(state, game_spec.target_artifact_id)

    source_path = _extract_source_path(state)
    if source_path is not None and source_path.exists():
        files = _collect_source_files(source_path, _DEFAULT_SOURCE_PATTERNS)
        source_content = _render_source_content(
            files, source_path, _DEFAULT_MAX_FILE_LINES, _DEFAULT_MAX_TOTAL_LINES
        )
        source_header = f"Source root: {source_path}"
    else:
        source_content = "(source_path not configured or does not exist)"
        source_header = "Source root: (unknown)"

    section_lines: list[str] = []
    if artifact.sections:
        for section in artifact.sections:
            section_lines.append(f"### {section.title}")
            section_lines.append("")
            section_lines.append(section.body)
            section_lines.append("")
    else:
        section_lines.append("No findings yet.")

    content = "\n".join([
        "=== StateView Start ===",
        "",
        "--- Source Code (read-only) ---",
        "",
        source_header,
        "",
        source_content,
        "",
        "--- Audit Report (current findings) ---",
        "",
        f"## Artifact: {artifact.id}",
        "",
        *section_lines,
        "=== StateView End ===",
    ]).rstrip()

    input_fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return StateView(
        id=f"state-view:blue:{artifact.id}:{input_fingerprint[:12]}",
        projection_type=ProjectionType.NORTH_STAR,
        content=content,
        input_fingerprint=input_fingerprint,
        metadata={
            "target_artifact_id": artifact.id,
            "findings_count": len(artifact.sections),
        },
    )


_FINDING_FORMAT = (
    "Audit finding format (append_section or modify_section delta):\n"
    "- title: concise issue name (e.g. 'Prompt injection via unvalidated model output')\n"
    "- body must contain all of the following:\n"
    "    Location: file path and relevant line numbers\n"
    "    Severity: Critical / High / Medium / Low\n"
    "    Description: what the issue is and how it can be exploited or misused\n"
    "    Evidence: exact excerpt from the source shown in StateView\n"
    "    Recommendation: specific, actionable fix\n"
    "- One finding per delta. Do not bundle multiple issues into one section.\n"
    "- Do not invent findings — every finding must cite a specific excerpt from the source.\n"
    "- Do not repeat findings already present in the report.\n"
    "- Source is read-only context — do not propose changes to it in the finding body.\n"
)

_RED_SUPPLEMENT = (
    "Security adversarial review:\n"
    "- Verify that every excerpt quoted in Evidence actually appears verbatim in the source shown in StateView.\n"
    "- Challenge whether the finding is exploitable or harmful in practice, not just theoretically possible.\n"
    "- Challenge the Severity — is it overstated (raise that) or understated (raise that too)?\n"
    "- Verify the Recommendation actually addresses the root cause, not just a symptom.\n"
    "- Note if a related, more severe issue was missed that Blue should have caught.\n"
    "- Reject vague findings that lack specific file:line evidence.\n"
)

_REFEREE_SUPPLEMENT = (
    "Audit referee criteria:\n"
    "- Accept if: finding cites a specific excerpt, the issue is plausible, "
    "severity is justified by the evidence, and recommendation is concrete.\n"
    "- Reject if: finding is vague or hypothetical, evidence is fabricated or misquotes source, "
    "or finding duplicates an existing report section.\n"
    "- Revise if: finding identifies a real issue but severity or recommendation needs correction.\n"
)

_CREATE_GAME_SUPPLEMENT = (
    "Audit CreateGame constraints:\n"
    "- Each game targets one specific area or subsystem — do not create broad games.\n"
    "- Prefer areas not yet covered by existing report sections.\n"
    "- The game objective should name the specific file or subsystem to analyze.\n"
    "- success_condition should require a finding with Location, Severity, Evidence, and Recommendation.\n"
)


class AuditProjectAdapter:
    project_type = "audit"
    supported_delta_type = "DeltaDocumentState"

    def create_initial_state(self, config: dict[str, object]) -> State:
        northstar_markdown = _config_northstar_markdown(config)
        source_path = str(config.get("source_path", ""))
        if not source_path.strip():
            raise ValueError("source_path must be non-empty for audit project type")
        northstar_with_meta = _embed_source_path(northstar_markdown, source_path)
        northstar_artifact = build_northstar_artifact_from_markdown(northstar_with_meta)
        return State(
            northstar=NorthStar(artifacts=(northstar_artifact,)),
            artifacts=(DocumentArtifact(id=_config_artifact_id(config), sections=()),),
        )

    def build_create_game_state_view(self, state: State, config: dict[str, object]) -> StateView:
        return build_audit_create_game_state_view(state, config)

    def render_create_game_prompt_supplement(
        self,
        state: State,
        config: dict[str, object],
        state_view: StateView,
        verification_result: VerificationResult | None,
    ) -> str:
        del state, config, state_view, verification_result
        return _CREATE_GAME_SUPPLEMENT

    def normalize_game_spec(
        self, game_spec: GameSpec, state: State, config: dict[str, object]
    ) -> GameSpec:
        del state, config
        return game_spec

    def build_state_view(self, state: State, game_spec: GameSpec) -> StateView:
        return build_audit_play_game_state_view(state, game_spec)

    def render_blue_prompt(
        self,
        state_view: StateView,
        game_spec: GameSpec,
        attempt_number: int,
        previous_feedback: dict[str, object] | None,
    ) -> str:
        return render_blue_prompt_core(
            state_view=state_view,
            game_spec=game_spec,
            attempt_number=attempt_number,
            previous_feedback=previous_feedback,
            project_delta_instructions=_FINDING_FORMAT,
        )

    def render_red_prompt_supplement(
        self,
        state_view: StateView,
        game_spec: GameSpec,
        delta_state: DeltaState,
        verification_result: VerificationResult | None,
    ) -> str:
        del state_view, game_spec, delta_state, verification_result
        return _RED_SUPPLEMENT

    def render_referee_prompt_supplement(
        self,
        state_view: StateView,
        game_spec: GameSpec,
        delta_state: DeltaState,
        verification_result: VerificationResult | None,
    ) -> str:
        del state_view, game_spec, delta_state, verification_result
        return _REFEREE_SUPPLEMENT

    def build_blue_output_format(self) -> str | dict | None:
        return None

    def build_blue_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="append_section",
                description="Append a new audit finding to the report.",
                parameters={
                    "type": "object",
                    "properties": {
                        "artifact_id": {"type": "string", "description": "Target audit report artifact ID"},
                        "title": {"type": "string", "description": "Concise vulnerability name"},
                        "body": {
                            "type": "string",
                            "description": "Finding body with Location, Severity, Description, Evidence, Recommendation",
                        },
                    },
                    "required": ["artifact_id", "title", "body"],
                },
            ),
            ToolDefinition(
                name="modify_section",
                description="Revise an existing audit finding in the report.",
                parameters={
                    "type": "object",
                    "properties": {
                        "artifact_id": {"type": "string", "description": "Target audit report artifact ID"},
                        "section_title": {"type": "string", "description": "Exact title of the finding to revise"},
                        "new_body": {"type": "string", "description": "Revised finding body"},
                    },
                    "required": ["artifact_id", "section_title", "new_body"],
                },
            ),
        ]

    def tool_call_to_delta(self, tool_call: ToolCall) -> DeltaState:
        from baps.state import DeltaDocumentState, DeltaModifyDocumentState, AppendSectionDelta, Section, ModifySectionDelta
        args = tool_call.arguments
        if tool_call.name == "append_section":
            try:
                artifact_id = str(args["artifact_id"])
                title = str(args["title"])
                body = str(args["body"])
            except KeyError as exc:
                raise ValueError(f"missing required tool argument: {exc}") from exc
            try:
                return DeltaDocumentState.model_validate({
                    "artifact_id": artifact_id,
                    "operation": "append_section",
                    "payload": {"section": {"title": title, "body": body}},
                })
            except Exception as exc:
                raise ValueError(f"tool call failed DeltaDocumentState validation: {exc}") from exc
        if tool_call.name == "modify_section":
            try:
                artifact_id = str(args["artifact_id"])
                section_title = str(args["section_title"])
                new_body = str(args["new_body"])
            except KeyError as exc:
                raise ValueError(f"missing required tool argument: {exc}") from exc
            try:
                return DeltaModifyDocumentState.model_validate({
                    "artifact_id": artifact_id,
                    "operation": "modify_section",
                    "payload": {"section_title": section_title, "new_body": new_body},
                })
            except Exception as exc:
                raise ValueError(f"tool call failed DeltaModifyDocumentState validation: {exc}") from exc
        raise ValueError(f"unexpected tool: {tool_call.name!r}")

    def parse_blue_delta(self, text: str) -> DeltaState:
        return parse_document_delta_json(text)

    def delta_to_state_update(self, delta_state: DeltaState) -> StateUpdateProposal:
        return derive_document_state_update_from_delta(delta_state)

    def export_state(self, state: State, output_path: Path, artifact_id: str) -> bool:
        artifact = document_artifact_from_state(state, artifact_id)
        rendered = render_document_artifact_markdown(artifact)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        before = output_path.read_text(encoding="utf-8") if output_path.exists() else None
        changed = before != rendered
        if changed:
            output_path.write_text(rendered, encoding="utf-8")
        return changed
