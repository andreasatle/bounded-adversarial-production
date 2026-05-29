from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from baps.models.model_output import parse_model_output
from baps.models.models import ToolCall, ToolDefinition
from baps.northstar.northstar_projection import ProjectionType, StateView, assemble_state_view
from baps.adapters.project_adapter import (
    VerificationResult,
    _config_artifact_id,
    _config_northstar_markdown,
    render_blue_prompt_core,
    sanitize_model_string,
    sanitize_model_title,
)

if TYPE_CHECKING:
    from baps.game.roles import PlayGameFeedback
    from baps.summarizer.summarizer import SummarizationContext
from baps.state.state import (
    DeltaState,
    DocumentArtifact,
    GameSpec,
    Section,
    State,
)
from baps.adapters.document_adapter import (
    document_artifact_from_state,
    export_document_artifact,
    parse_document_delta_json,
)


_SOURCE_PATH_MARKER = "<!-- audit:source_path="
_AUDIT_META_ARTIFACT_ID_PREFIX = "audit:meta:"
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


def _get_northstar_from_state(state: State) -> str:
    """Extract the northstar markdown content stored in the audit meta artifact."""
    for artifact in state.artifacts:
        if isinstance(artifact, DocumentArtifact) and artifact.id.startswith(_AUDIT_META_ARTIFACT_ID_PREFIX):
            for section in artifact.sections:
                if section.title == "northstar":
                    return section.body
    return ""


def _extract_source_path(northstar_markdown: str) -> Path | None:
    content = northstar_markdown
    if _SOURCE_PATH_MARKER not in content:
        return None
    start = content.index(_SOURCE_PATH_MARKER) + len(_SOURCE_PATH_MARKER)
    end = content.find(" -->", start)
    if end == -1:
        return None
    return Path(content[start:end])


def _compute_source_hash(source_path: Path, patterns: tuple[str, ...]) -> str:
    files = _collect_source_files(source_path, patterns)
    h = hashlib.sha256()
    for f in files:
        try:
            h.update(f.read_bytes())
        except OSError:
            pass
    return h.hexdigest()[:16]


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
    northstar_markdown = _config_northstar_markdown(config)
    northstar_content = northstar_markdown

    source_path_str = str(config.get("source_path", "")).strip()
    source_path = Path(source_path_str) if source_path_str else None
    if source_path is not None and source_path.exists():
        patterns = tuple(config.get("source_include") or _DEFAULT_SOURCE_PATTERNS)
        files = _collect_source_files(source_path, patterns)
        current_hash = _compute_source_hash(source_path, patterns)
        source_block = _render_source_listing(files, source_path)
        source_header = f"Source root: {source_path}"
    else:
        current_hash = None
        source_block = "(source_path not configured or does not exist)"
        source_header = "Source root: (unknown)"

    section_lines: list[str] = []
    stale_count = 0
    if artifact.sections:
        for section in artifact.sections:
            is_stale = (
                current_hash is not None
                and section.source_hash is not None
                and section.source_hash != current_hash
            )
            if is_stale:
                stale_count += 1
            stale_marker = " [STALE — source changed]" if is_stale else ""
            section_lines.append(f"### {sanitize_model_title(section.title)}{stale_marker}")
            body_preview = section.body[:300] + ("..." if len(section.body) > 300 else "")
            section_lines.append(sanitize_model_string(body_preview))
            section_lines.append("")
    else:
        section_lines.append("No findings yet.")

    stale_note = f", {stale_count} stale" if stale_count else ""
    return assemble_state_view(
        stage="create-game",
        artifact_id=artifact.id,
        projection_type=ProjectionType.CREATE_GAME,
        inner_lines=[
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
            f"findings so far: {len(artifact.sections)}{stale_note}",
            "",
            *section_lines,
        ],
        metadata={
            "target_artifact_id": artifact.id,
            "findings_count": len(artifact.sections),
            "stale_findings_count": stale_count,
        },
    )


def build_audit_play_game_state_view(state: State, game_spec: GameSpec) -> StateView:
    artifact = document_artifact_from_state(state, game_spec.target_artifact_id)

    northstar_markdown = _get_northstar_from_state(state)
    source_path = _extract_source_path(northstar_markdown)
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
            section_lines.append(f"### {sanitize_model_title(section.title)}")
            section_lines.append("")
            section_lines.append(sanitize_model_string(section.body))
            section_lines.append("")
    else:
        section_lines.append("No findings yet.")

    return assemble_state_view(
        stage="blue",
        artifact_id=artifact.id,
        projection_type=ProjectionType.PLAY_GAME,
        inner_lines=[
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
        ],
        metadata={
            "target_artifact_id": artifact.id,
            "findings_count": len(artifact.sections),
        },
    )


_FINDING_FORMAT = (
    "Produce exactly one of the following delta types:\n"
    "\n"
    "OPTION A — append_section (vulnerability found):\n"
    "- title: concise issue name (e.g. 'Prompt injection via unvalidated model output')\n"
    "- body must contain all of the following:\n"
    "    Location: file path and relevant line numbers\n"
    "    Severity: Critical / High / Medium / Low\n"
    "    Description: what the issue is and how it can be exploited or misused\n"
    "    Evidence: exact excerpt from the source shown in StateView\n"
    "    Recommendation: specific, actionable fix\n"
    "- One finding per delta. Do not bundle multiple issues into one section.\n"
    "- Do not invent findings — every finding must cite a specific excerpt.\n"
    "- Do not repeat findings already present in the report.\n"
    "\n"
    "OPTION B — no_finding (nothing actionable found):\n"
    "- Use this when you have genuinely inspected the target and found no exploitable issue.\n"
    "- file: the specific file or subsystem you audited\n"
    "- rationale: what you checked and why it is safe — must reference specific code paths,\n"
    "  not a generic statement. Red will reject vague rationales.\n"
    "- Do not use no_finding as a shortcut — a weak rationale will be rejected.\n"
    "\n"
    "Source is read-only context — do not propose changes to it in any delta body.\n"
)

_RED_SUPPLEMENT = (
    "Security adversarial review:\n"
    "\n"
    "For finding deltas (append_section / modify_section):\n"
    "- Verify every excerpt quoted in Evidence appears verbatim in the source shown in StateView.\n"
    "- Challenge whether the finding is exploitable in practice, not just theoretically possible.\n"
    "- Challenge the Severity — is it overstated (raise that) or understated (raise that too)?\n"
    "- Verify the Recommendation addresses the root cause, not just a symptom.\n"
    "- Note if a related, more severe issue was missed.\n"
    "- Reject vague findings that lack specific file:line evidence.\n"
    "\n"
    "For no_finding deltas:\n"
    "- Challenge whether Blue actually inspected the relevant code paths.\n"
    "- Reject if the rationale does not reference specific functions, variables, or control flow.\n"
    "- Reject if a real vulnerability is visible in the source shown in StateView.\n"
    "- Accept only if the rationale is specific and the inspection appears genuine.\n"
)

_REFEREE_SUPPLEMENT = (
    "Audit referee criteria:\n"
    "\n"
    "For finding deltas (append_section / modify_section):\n"
    "- Accept if: specific excerpt cited, issue is plausible, severity justified, recommendation concrete.\n"
    "- Reject if: vague, hypothetical, fabricated/misquoted evidence, or duplicates existing section.\n"
    "- Revise if: real issue but severity or recommendation needs correction.\n"
    "\n"
    "For no_finding deltas:\n"
    "- Accept if: rationale names specific code paths checked and explains why they are safe.\n"
    "- Reject if: rationale is generic, cursory, or misses an obvious issue in the source.\n"
)

_CREATE_GAME_SUPPLEMENT = (
    "Audit CreateGame constraints:\n"
    "- Each game targets one specific area or subsystem — do not create broad games.\n"
    "- Prefer areas not yet covered by existing report sections (findings or no_finding coverage notes).\n"
    "- The game objective should name the specific file or subsystem to analyze.\n"
    "- success_condition should require either a finding with evidence or a no_finding with specific rationale.\n"
)


class AuditProjectAdapter:
    project_type = "audit"
    supported_delta_type = "DeltaDocumentState"

    def __init__(self) -> None:
        self._current_source_hash: str | None = None

    def create_initial_state(self, config: dict[str, object]) -> State:
        northstar_markdown = _config_northstar_markdown(config)
        source_path = str(config.get("source_path", ""))
        if not source_path.strip():
            raise ValueError("source_path must be non-empty for audit project type")
        northstar_with_meta = _embed_source_path(northstar_markdown, source_path)
        fingerprint = hashlib.sha256(northstar_with_meta.encode("utf-8")).hexdigest()[:12]
        meta_artifact = DocumentArtifact(
            id=f"{_AUDIT_META_ARTIFACT_ID_PREFIX}{fingerprint}",
            sections=(Section(title="northstar", body=northstar_with_meta),),
        )
        return State(
            artifacts=(
                DocumentArtifact(id=_config_artifact_id(config), sections=()),
                meta_artifact,
            ),
        )

    def build_create_game_state_view(
        self,
        state: State,
        config: dict[str, object],
        summarization_context: SummarizationContext | None = None,
    ) -> StateView:
        del summarization_context
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

    def build_state_view(
        self,
        state: State,
        game_spec: GameSpec,
        summarization_context: SummarizationContext | None = None,
    ) -> StateView:
        del summarization_context
        source_path = _extract_source_path(_get_northstar_from_state(state))
        if source_path is not None and source_path.exists():
            self._current_source_hash = _compute_source_hash(source_path, _DEFAULT_SOURCE_PATTERNS)
        else:
            self._current_source_hash = None
        return build_audit_play_game_state_view(state, game_spec)

    def render_blue_prompt(
        self,
        state_view: StateView,
        game_spec: GameSpec,
        attempt_number: int,
        previous_feedback: PlayGameFeedback | None,
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
            ToolDefinition(
                name="no_finding",
                description=(
                    "Record that a file or subsystem was audited and no actionable finding was identified. "
                    "Use only when you have genuinely inspected the target. "
                    "Red will reject vague or generic rationales."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "artifact_id": {"type": "string", "description": "Target audit report artifact ID"},
                        "file": {"type": "string", "description": "File or subsystem audited"},
                        "rationale": {
                            "type": "string",
                            "description": (
                                "What was checked and why it is safe — "
                                "must reference specific functions, variables, or control flow"
                            ),
                        },
                    },
                    "required": ["artifact_id", "file", "rationale"],
                },
            ),
        ]

    def tool_call_to_delta(self, tool_call: ToolCall) -> DeltaState:
        from baps.state.state import DeltaDocumentState, DeltaModifyDocumentState
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
                    "payload": {"section": {"title": title, "body": body, "source_hash": self._current_source_hash}},
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
        if tool_call.name == "no_finding":
            try:
                artifact_id = str(args["artifact_id"])
                file = str(args["file"])
                rationale = str(args["rationale"])
            except KeyError as exc:
                raise ValueError(f"missing required tool argument: {exc}") from exc
            try:
                return DeltaDocumentState.model_validate({
                    "artifact_id": artifact_id,
                    "operation": "append_section",
                    "payload": {"section": {"title": f"Audited: {file}", "body": rationale, "source_hash": self._current_source_hash}},
                })
            except Exception as exc:
                raise ValueError(f"tool call failed DeltaDocumentState validation: {exc}") from exc
        raise ValueError(f"unexpected tool: {tool_call.name!r}")

    def parse_blue_delta(self, text: str) -> DeltaState:
        from baps.state.state import DeltaDocumentState
        _AUDIT_KEYS = frozenset({"artifact_id", "operation", "file", "rationale", "payload"})
        try:
            raw, _ = parse_model_output(text, _AUDIT_KEYS, context="blue:audit")
        except ValueError:
            return parse_document_delta_json(text)
        if raw.get("operation") == "no_finding":
            file = str(raw.get("file", ""))
            rationale = str(raw.get("rationale", ""))
            artifact_id = str(raw.get("artifact_id", ""))
            if not file or not rationale or not artifact_id:
                raise ValueError("no_finding delta missing required field (artifact_id, file, rationale)")
            return DeltaDocumentState.model_validate({
                "artifact_id": artifact_id,
                "operation": "append_section",
                "payload": {"section": {"title": f"Audited: {file}", "body": rationale, "source_hash": self._current_source_hash}},
            })
        return parse_document_delta_json(text)

    def export_state(self, state: State, output_path: Path, artifact_id: str) -> bool:
        return export_document_artifact(document_artifact_from_state(state, artifact_id), output_path)
