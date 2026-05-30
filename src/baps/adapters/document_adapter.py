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
    DeltaDeleteDocumentState,
    DeltaDocumentState,
    DeltaModifyDocumentState,
    DeltaState,
    DocumentArtifact,
    GameSpec,
    Section,
    State,
)




def _first_sentence(text: str) -> str:
    """Return the first sentence of *text* (up to the first period, or 100 chars)."""
    idx = text.find(".")
    if idx != -1 and idx < 150:
        return text[: idx + 1].strip()
    return text[:100].strip()


def _build_module_research_tools(
    filters: list[str],
    list_desc: str,
    fetch_desc: str,
    entity_desc: str,
) -> list[ToolDefinition]:
    """Build and return module research tools."""
    filter_prop: dict = {
        "type": "string",
        "enum": filters,
        "description": f"Detail level. Options: {', '.join(filters)}. Omit for names and counts only.",
    }
    return [
        ToolDefinition(
            name="list_modules",
            description=list_desc,
            parameters={
                "type": "object",
                "properties": {"filter": filter_prop},
                "required": [],
            },
        ),
        ToolDefinition(
            name="fetch_module",
            description=fetch_desc,
            parameters={
                "type": "object",
                "properties": {
                    "module_id": {
                        "type": "string",
                        "description": "Identifier of the unit (from list_modules output).",
                    },
                    "filter": filter_prop,
                },
                "required": ["module_id"],
            },
        ),
        ToolDefinition(
            name="fetch_entity",
            description=entity_desc,
            parameters={
                "type": "object",
                "properties": {
                    "module_id": {
                        "type": "string",
                        "description": "Identifier of the containing unit.",
                    },
                    "entity_id": {
                        "type": "string",
                        "description": "Name of the entity within the unit.",
                    },
                    "filter": filter_prop,
                },
                "required": ["module_id", "entity_id"],
            },
        ),
    ]


def build_northstar_artifact_from_markdown(markdown: str) -> DocumentArtifact:
    """Build and return northstar artifact from markdown."""
    fingerprint = hashlib.sha256(markdown.encode("utf-8")).hexdigest()[:12]
    return DocumentArtifact(
        id=f"northstar:{fingerprint}",
        sections=(Section(title="NorthStar", body=markdown),),
    )


def document_artifact_from_state(state: State, artifact_id: str) -> DocumentArtifact:
    """Handle document artifact from state."""
    artifact = next((a for a in state.artifacts if a.id == artifact_id), None)
    if artifact is None:
        raise ValueError(f"create_game target artifact not found in state: {artifact_id}")
    if not isinstance(artifact, DocumentArtifact):
        raise ValueError(f"create_game target artifact must be DocumentArtifact: {artifact_id}")
    return artifact


def build_document_create_game_state_view(state: State, config: dict[str, Any]) -> StateView:
    """Build and return document create game state view."""
    target_artifact = document_artifact_from_state(state, _config_artifact_id(config))
    northstar_content = _config_northstar_markdown(config)
    section_summaries = [
        {"title": sanitize_model_title(section.title), "body": sanitize_model_string(section.body)}
        for section in target_artifact.sections
    ]
    metadata = {
        "target_artifact": {
            "id": target_artifact.id,
            "kind": target_artifact.kind,
            "sections": section_summaries,
        },
    }
    section_lines: list[str] = []
    if target_artifact.sections:
        for section in target_artifact.sections:
            section_lines.append(f"### {sanitize_model_title(section.title)}")
            section_lines.append(sanitize_model_string(section.body))
            section_lines.append("")
    else:
        section_lines.append("No sections.")

    return assemble_state_view(
        stage="create-game",
        artifact_id=target_artifact.id,
        projection_type=ProjectionType.CREATE_GAME,
        inner_lines=[
            "--- NorthStar ---",
            "",
            northstar_content if northstar_content else "No NorthStar content.",
            "",
            "--- State Artifacts ---",
            "",
            f"## Artifact: {target_artifact.id}",
            "",
            f"kind: {target_artifact.kind}",
            "",
            "### Current Sections",
            "",
            *section_lines,
            "",
        ],
        metadata=metadata,
    )


def build_document_state_view(
    state: State,
    game_spec: GameSpec,
    summarization_context: SummarizationContext | None = None,
) -> StateView:
    """Build and return document state view."""
    target_artifact = next(
        (artifact for artifact in state.artifacts if artifact.id == game_spec.target_artifact_id),
        None,
    )
    if target_artifact is None:
        raise ValueError(
            f"state_view target artifact not found in state: {game_spec.target_artifact_id}"
        )
    if not isinstance(target_artifact, DocumentArtifact):
        raise ValueError(
            "state_view only supports document artifact targets; "
            f"got: {target_artifact.kind}"
        )
    sections = [
        {"title": sanitize_model_title(section.title), "body": sanitize_model_string(section.body)}
        for section in target_artifact.sections
    ]
    metadata = {
        "target_artifact_id": target_artifact.id,
        "sections": sections,
    }
    target_entity = game_spec.target_entity
    section_lines: list[str] = []
    if target_artifact.sections:
        for section in target_artifact.sections:
            if target_entity is not None and section.title != target_entity:
                summary = (
                    summarization_context.summarize(section.body, objective=game_spec.objective)
                    if summarization_context is not None
                    else None
                )
                if summary is not None:
                    section_lines.append(f"### {sanitize_model_title(section.title)} [summary]")
                    section_lines.append("")
                    section_lines.append(summary)
                    section_lines.append("")
                    continue
                section_lines.append(f"### {sanitize_model_title(section.title)} [full]")
            elif target_entity is not None:
                section_lines.append(f"### {sanitize_model_title(section.title)} [full]")
            else:
                section_lines.append(f"### {sanitize_model_title(section.title)}")
            section_lines.append("")
            section_lines.append(sanitize_model_string(section.body))
            section_lines.append("")
    else:
        section_lines.append("No sections.")

    return assemble_state_view(
        stage="blue",
        artifact_id=target_artifact.id,
        projection_type=ProjectionType.PLAY_GAME,
        inner_lines=[
            "--- State Artifacts ---",
            "",
            f"## Artifact: {target_artifact.id}",
            "",
            f"kind: {target_artifact.kind}",
            "",
            "### Current Sections",
            "",
            *section_lines,
        ],
        metadata=metadata,
    )


def render_document_blue_prompt(
    state_view: StateView,
    game_spec: GameSpec,
    attempt_number: int,
    previous_feedback: PlayGameFeedback | None,
) -> str:
    """Render and return document blue prompt."""
    document_delta_instructions = (
        "Document delta rules:\n"
        "- section.title and section.body must be non-empty strings.\n"
        'Invalid example, do not output: "body": ""\n'
        "Use append_section to add a new section:\n"
        "{\n"
        '  "artifact_id": "<game_spec.target_artifact_id>",\n'
        '  "operation": "append_section",\n'
        '  "payload": {\n'
        '    "section": {\n'
        '      "title": "<section title>",\n'
        '      "body": "Concrete non-empty section body text."\n'
        "    }\n"
        "  }\n"
        "}\n"
        "Use modify_section to rewrite an existing section's body:\n"
        "{\n"
        '  "artifact_id": "<game_spec.target_artifact_id>",\n'
        '  "operation": "modify_section",\n'
        '  "payload": {\n'
        '    "section_title": "<exact title of existing section>",\n'
        '    "new_body": "Replacement body text."\n'
        "  }\n"
        "}\n"
        "Use delete_section to remove a section that is no longer needed:\n"
        "{\n"
        '  "artifact_id": "<game_spec.target_artifact_id>",\n'
        '  "operation": "delete_section",\n'
        '  "payload": {\n'
        '    "section_title": "<exact title of section to delete>"\n'
        "  }\n"
        "}"
    )
    return render_blue_prompt_core(
        state_view=state_view,
        game_spec=game_spec,
        attempt_number=attempt_number,
        previous_feedback=previous_feedback,
        project_delta_instructions=document_delta_instructions,
    )


_BLUE_DOCUMENT_KEYS = frozenset({"artifact_id", "operation", "payload"})


def parse_document_delta_json(text: str, workspace: Path | None = None) -> DeltaDocumentState | DeltaModifyDocumentState:
    """Parse and return document delta json."""
    parsed, _ = parse_model_output(text, _BLUE_DOCUMENT_KEYS, context="blue:document", workspace=workspace)
    if not _BLUE_DOCUMENT_KEYS.issubset(parsed.keys()):
        raise ValueError(
            "blue model output must contain keys: artifact_id, operation, payload"
        )

    operation = parsed.get("operation")
    if operation == "modify_section":
        try:
            return DeltaModifyDocumentState.model_validate(parsed)
        except Exception as exc:
            raise ValueError(
                f"blue model output failed DeltaModifyDocumentState validation: {exc}"
            ) from exc

    if operation == "delete_section":
        try:
            return DeltaDeleteDocumentState.model_validate(parsed)
        except Exception as exc:
            raise ValueError(
                f"blue model output failed DeltaDeleteDocumentState validation: {exc}"
            ) from exc

    try:
        return DeltaDocumentState.model_validate(parsed)
    except Exception as exc:
        raise ValueError(
            f"blue model output failed DeltaDocumentState validation: {exc}"
        ) from exc


def render_document_artifact_markdown(artifact: DocumentArtifact) -> str:
    """Render and return document artifact markdown."""
    sections = [f"## {section.title}\n\n{section.body}" for section in artifact.sections]
    return "\n\n".join(sections)


def export_document_artifact(artifact: DocumentArtifact, output_path: Path) -> bool:
    """Export and return document artifact."""
    rendered = render_document_artifact_markdown(artifact)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    before = output_path.read_text(encoding="utf-8") if output_path.exists() else None
    changed = before != rendered
    if changed:
        output_path.write_text(rendered, encoding="utf-8")
    return changed


class DocumentProjectAdapter:
    """Implement the DocumentProjectAdapter project adapter."""
    project_type = "document"
    supported_delta_type = "DeltaDocumentState"

    def create_initial_state(self, config: dict[str, object]) -> State:
        """Create and return initial state."""
        return State(
            artifacts=(DocumentArtifact(id=_config_artifact_id(config), sections=()),),
        )

    def build_create_game_state_view(
        self,
        state: State,
        config: dict[str, object],
        summarization_context: SummarizationContext | None = None,
    ) -> StateView:
        """Build and return create game state view."""
        del summarization_context
        return build_document_create_game_state_view(state, config)

    def render_create_game_prompt_supplement(
        self,
        state: State,
        config: dict[str, object],
        state_view: StateView,
        verification_result: VerificationResult | None,
    ) -> str:
        """Render and return create game prompt supplement."""
        del state, config, state_view
        base = (
            "Document CreateGame constraints:\n"
            "- Use append_section to add a new section to the document.\n"
            "- Use modify_section to rewrite an existing section's body (section_title must match exactly).\n"
            "- Use delete_section to remove a section that is no longer needed (section_title must match exactly).\n"
        )
        if verification_result is None:
            return base
        return (
            f"{base}"
            "Document CreateGame verification evidence:\n"
            "- If evidence shows missing sections, prefer a game that appends those sections.\n"
            "- If evidence shows an empty export, prefer a game that adds foundational content.\n"
            "- If evidence shows stale or incorrect content, prefer a game that modifies the relevant section.\n"
        )

    def normalize_game_spec(
        self, game_spec: GameSpec, state: State, config: dict[str, object]
    ) -> GameSpec:
        """Normalize and return game spec."""
        del state, config
        return game_spec

    def build_state_view(
        self,
        state: State,
        game_spec: GameSpec,
        summarization_context: SummarizationContext | None = None,
    ) -> StateView:
        """Build and return state view."""
        return build_document_state_view(state, game_spec, summarization_context=summarization_context)

    def render_blue_prompt(
        self,
        state_view: StateView,
        game_spec: GameSpec,
        attempt_number: int,
        previous_feedback: dict[str, object] | None,
    ) -> str:
        """Render and return blue prompt."""
        return render_document_blue_prompt(
            state_view=state_view,
            game_spec=game_spec,
            attempt_number=attempt_number,
            previous_feedback=previous_feedback,
        )

    def render_red_prompt_supplement(
        self,
        state_view: StateView,
        game_spec: GameSpec,
        delta_state: DeltaState,
        verification_result: VerificationResult | None,
    ) -> str:
        """Render and return red prompt supplement."""
        del state_view, game_spec, delta_state, verification_result
        return ""

    def render_referee_prompt_supplement(
        self,
        state_view: StateView,
        game_spec: GameSpec,
        delta_state: DeltaState,
        verification_result: VerificationResult | None,
    ) -> str:
        """Render and return referee prompt supplement."""
        del state_view, game_spec, delta_state, verification_result
        return ""

    def supported_filters(self) -> list[str]:
        """Return supported values for ed filters."""
        return ["summary", "full"]

    def build_research_tools(self, role: str) -> list[ToolDefinition]:
        """Build and return research tools."""
        del role
        return []

    def build_create_game_research_tools(self, state: State) -> list:
        """Build and return create game research tools."""
        artifact = next(
            (a for a in state.artifacts if isinstance(a, DocumentArtifact) and a.sections),
            None,
        )
        if artifact is None:
            return []
        filters = self.supported_filters()
        return _build_module_research_tools(
            filters,
            list_desc="List document sections with title and word count.",
            fetch_desc="Get a document section by title.",
            entity_desc="Not supported for document artifacts.",
        )

    def execute_create_game_research_tool(
        self, tool_name: str, tool_input: dict, state: State
    ) -> str:
        """Execute and return create game research tool."""
        artifact = next(
            (a for a in state.artifacts if isinstance(a, DocumentArtifact)),
            None,
        )
        if tool_name == "list_modules":
            if artifact is None or not artifact.sections:
                return "(no sections)"
            filter_val = tool_input.get("filter")
            if filter_val is not None and filter_val not in self.supported_filters():
                return f"Unknown filter '{filter_val}'. Available filters: {', '.join(self.supported_filters())}"
            lines = []
            for sec in artifact.sections:
                word_count = len(sec.body.split())
                entry = f"{sec.title} ({word_count} words)"
                if filter_val == "summary":
                    first_sentence = _first_sentence(sec.body)
                    entry += f"\n  {first_sentence}"
                lines.append(entry)
            return "\n".join(lines)

        if tool_name == "fetch_module":
            module_id = tool_input.get("module_id", "")
            if not isinstance(module_id, str) or not module_id:
                return "tool_error: fetch_module requires a non-empty 'module_id' string"
            if artifact is None:
                return "tool_error: no document artifact found in state"
            section = next((s for s in artifact.sections if s.title == module_id), None)
            if section is None:
                available = sorted(s.title for s in artifact.sections)
                available_str = ", ".join(f"'{t}'" for t in available) if available else "(none)"
                return f"Section '{module_id}' not found. Available sections: {available_str}"
            filter_val = tool_input.get("filter")
            if filter_val is not None and filter_val not in self.supported_filters():
                return f"Unknown filter '{filter_val}'. Available filters: {', '.join(self.supported_filters())}"
            if filter_val is None:
                return f"{section.title} ({len(section.body.split())} words)"
            if filter_val == "summary":
                parts = section.body.split("\n\n")
                return parts[0].strip()
            return section.body  # "full"

        if tool_name == "fetch_entity":
            return (
                "tool_error: fetch_entity is not supported for document artifacts. "
                "Use fetch_module to retrieve section content."
            )

        if tool_name == "fetch_section":
            if artifact is None or not artifact.sections:
                return "tool_error: no document artifact with sections found in state"
            title = tool_input.get("title", "")
            if not isinstance(title, str) or not title:
                return "tool_error: fetch_section requires a non-empty 'title' string"
            section = next((s for s in artifact.sections if s.title == title), None)
            if section is None:
                available = sorted(s.title for s in artifact.sections)
                available_str = ", ".join(f"'{t}'" for t in available) if available else "(none)"
                return f"Section '{title}' not found in artifact. Available sections: {available_str}"
            return section.body

        return f"tool_error: unknown tool {tool_name!r}"

    def build_blue_output_format(self) -> str | dict | None:
        # Two valid operation shapes — return None so prompt instructions drive format
        # rather than a single rigid constrained-decoding schema.
        """Build and return blue output format."""
        return None

    def build_blue_tools(self) -> list[ToolDefinition]:
        """Build and return blue tools."""
        return [
            ToolDefinition(
                name="append_section",
                description="Append a new section to the document artifact.",
                parameters={
                    "type": "object",
                    "properties": {
                        "artifact_id": {
                            "type": "string",
                            "description": "Target document artifact ID",
                        },
                        "title": {
                            "type": "string",
                            "description": "Section title (non-empty)",
                        },
                        "body": {
                            "type": "string",
                            "description": "Section body text (non-empty)",
                        },
                    },
                    "required": ["artifact_id", "title", "body"],
                },
            ),
            ToolDefinition(
                name="modify_section",
                description="Rewrite the body of an existing section in the document artifact.",
                parameters={
                    "type": "object",
                    "properties": {
                        "artifact_id": {
                            "type": "string",
                            "description": "Target document artifact ID",
                        },
                        "section_title": {
                            "type": "string",
                            "description": "Exact title of the section to modify",
                        },
                        "new_body": {
                            "type": "string",
                            "description": "Replacement body text (non-empty)",
                        },
                    },
                    "required": ["artifact_id", "section_title", "new_body"],
                },
            ),
            ToolDefinition(
                name="delete_section",
                description="Remove a section from the document artifact.",
                parameters={
                    "type": "object",
                    "properties": {
                        "artifact_id": {
                            "type": "string",
                            "description": "Target document artifact ID",
                        },
                        "section_title": {
                            "type": "string",
                            "description": "Exact title of the section to delete",
                        },
                    },
                    "required": ["artifact_id", "section_title"],
                },
            ),
        ]

    def tool_call_to_delta(self, tool_call: ToolCall) -> DeltaState:
        """Handle tool call to delta."""
        args = tool_call.arguments
        if tool_call.name == "modify_section":
            try:
                artifact_id = str(args["artifact_id"])
                section_title = str(args["section_title"])
                new_body = str(args["new_body"])
            except KeyError as exc:
                raise ValueError(f"missing required tool argument: {exc}") from exc
            try:
                return DeltaModifyDocumentState.model_validate(
                    {
                        "artifact_id": artifact_id,
                        "operation": "modify_section",
                        "payload": {"section_title": section_title, "new_body": new_body},
                    }
                )
            except Exception as exc:
                raise ValueError(
                    f"tool call arguments failed DeltaModifyDocumentState validation: {exc}"
                ) from exc
        if tool_call.name == "append_section":
            try:
                artifact_id = str(args["artifact_id"])
                title = str(args["title"])
                body = str(args["body"])
            except KeyError as exc:
                raise ValueError(f"missing required tool argument: {exc}") from exc
            try:
                return DeltaDocumentState.model_validate(
                    {
                        "artifact_id": artifact_id,
                        "operation": "append_section",
                        "payload": {"section": {"title": title, "body": body}},
                    }
                )
            except Exception as exc:
                raise ValueError(
                    f"tool call arguments failed DeltaDocumentState validation: {exc}"
                ) from exc
        if tool_call.name == "delete_section":
            try:
                artifact_id = str(args["artifact_id"])
                section_title = str(args["section_title"])
            except KeyError as exc:
                raise ValueError(f"missing required tool argument: {exc}") from exc
            try:
                return DeltaDeleteDocumentState.model_validate(
                    {
                        "artifact_id": artifact_id,
                        "operation": "delete_section",
                        "payload": {"section_title": section_title},
                    }
                )
            except Exception as exc:
                raise ValueError(
                    f"tool call arguments failed DeltaDeleteDocumentState validation: {exc}"
                ) from exc
        raise ValueError(f"unexpected tool: {tool_call.name!r}")

    def parse_blue_delta(self, text: str) -> DeltaState:
        """Parse and return blue delta."""
        return parse_document_delta_json(text)

    def export_state(self, state: State, output_path: Path, artifact_id: str) -> bool:
        """Export and return state."""
        return export_document_artifact(document_artifact_from_state(state, artifact_id), output_path)

    def verify_export(
        self, output_path: Path, state: State, artifact_id: str, sandbox_mode: str = "docker"
    ) -> VerificationResult | None:
        """Verify and return export."""
        command = "document_export_consistency_check"
        cwd = str(output_path.parent)
        if not output_path.exists():
            return VerificationResult(
                command=command,
                cwd=cwd,
                exit_code=1,
                stdout="",
                stderr=f"export file missing: {output_path}",
                passed=False,
            )

        content = output_path.read_text(encoding="utf-8")
        if content.strip() == "":
            return VerificationResult(
                command=command,
                cwd=cwd,
                exit_code=1,
                stdout="",
                stderr="export file is empty",
                passed=False,
            )

        artifact = document_artifact_from_state(state, artifact_id)
        missing: list[str] = []
        for section in artifact.sections:
            if section.title not in content:
                missing.append(f"missing section title: {section.title}")
            if section.body.strip() and section.body not in content:
                missing.append(f"missing section body for title: {section.title}")

        if missing:
            return VerificationResult(
                command=command,
                cwd=cwd,
                exit_code=1,
                stdout="",
                stderr="; ".join(missing),
                passed=False,
            )

        return VerificationResult(
            command=command,
            cwd=cwd,
            exit_code=0,
            stdout="document export verification passed",
            stderr="",
            passed=True,
        )
