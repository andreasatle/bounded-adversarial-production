from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from baps.northstar_projection import ProjectionType, StateView
from baps.project_adapter import VerificationResult, render_blue_prompt_core
from baps.state import (
    DeltaDocumentState,
    DeltaState,
    DocumentArtifact,
    GameSpec,
    NorthStar,
    Section,
    State,
    StateUpdateProposal,
    StateUpdateTarget,
)


def _config_artifact_id(config: dict[str, Any]) -> str:
    if "artifact_id" not in config:
        raise ValueError("artifact_id must be non-empty")
    value = str(config["artifact_id"])
    if value.strip() == "":
        raise ValueError("artifact_id must be non-empty")
    return value


def _config_northstar_markdown(config: dict[str, Any]) -> str:
    value = str(config.get("northstar_markdown", ""))
    if value.strip() == "":
        raise ValueError("northstar_markdown must be non-empty")
    return value


def _normalize_json_candidate(text: str) -> str:
    normalized = text.strip()
    fence_pattern = re.compile(
        r"\A```(?:json)?[ \t]*\n(?P<body>[\s\S]*?)\n```[ \t]*\Z",
        re.IGNORECASE,
    )
    fence_match = fence_pattern.match(normalized)
    if fence_match is not None:
        normalized = fence_match.group("body").strip()
    return normalized


def build_northstar_artifact_from_markdown(markdown: str) -> DocumentArtifact:
    fingerprint = hashlib.sha256(markdown.encode("utf-8")).hexdigest()[:12]
    return DocumentArtifact(
        id=f"northstar:{fingerprint}",
        sections=(Section(title="NorthStar", body=markdown),),
    )


def document_artifact_from_state(state: State, artifact_id: str) -> DocumentArtifact:
    artifact = next((a for a in state.artifacts if a.id == artifact_id), None)
    if artifact is None:
        raise ValueError(f"create_game target artifact not found in state: {artifact_id}")
    if not isinstance(artifact, DocumentArtifact):
        raise ValueError(f"create_game target artifact must be DocumentArtifact: {artifact_id}")
    return artifact


def build_document_create_game_state_view(state: State, config: dict[str, Any]) -> StateView:
    target_artifact = document_artifact_from_state(state, _config_artifact_id(config))
    northstar_content_parts: list[str] = []
    for artifact in state.northstar.artifacts:
        if isinstance(artifact, DocumentArtifact):
            for section in artifact.sections:
                northstar_content_parts.append(section.body)
    northstar_content = "\n\n".join(northstar_content_parts).strip()
    section_summaries = [
        {"title": section.title, "body": section.body}
        for section in target_artifact.sections
    ]
    metadata = {
        "northstar_content": northstar_content,
        "target_artifact": {
            "id": target_artifact.id,
            "kind": target_artifact.kind,
            "sections": section_summaries,
        },
        "state_summary": {
            "northstar_artifact_ids": [artifact.id for artifact in state.northstar.artifacts],
            "artifact_ids": [artifact.id for artifact in state.artifacts],
        },
    }
    section_lines: list[str] = []
    if target_artifact.sections:
        for section in target_artifact.sections:
            section_lines.append(f"### {section.title}")
            section_lines.append(section.body)
            section_lines.append("")
    else:
        section_lines.append("No sections.")

    content = "\n".join(
        [
            "=== StateView Start ===",
            "",
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
            "=== StateView End ===",
        ]
    ).rstrip()
    input_fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return StateView(
        id=f"state-view:create-game:{target_artifact.id}:{input_fingerprint[:12]}",
        projection_type=ProjectionType.NORTH_STAR,
        content=content,
        input_fingerprint=input_fingerprint,
        metadata=metadata,
    )


def build_document_state_view(state: State, game_spec: GameSpec) -> StateView:
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
        {"title": section.title, "body": section.body}
        for section in target_artifact.sections
    ]
    metadata = {
        "target_artifact_id": target_artifact.id,
        "sections": sections,
    }
    section_lines: list[str] = []
    if target_artifact.sections:
        for section in target_artifact.sections:
            section_lines.append(f"### {section.title}")
            section_lines.append("")
            section_lines.append(section.body)
            section_lines.append("")
    else:
        section_lines.append("No sections.")

    content = "\n".join(
        [
            "=== StateView Start ===",
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
            "=== StateView End ===",
        ]
    ).rstrip()
    input_fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return StateView(
        id=f"state-view:blue:{target_artifact.id}:{input_fingerprint[:12]}",
        projection_type=ProjectionType.NORTH_STAR,
        content=content,
        input_fingerprint=input_fingerprint,
        metadata=metadata,
    )


def render_document_blue_prompt(
    state_view: StateView,
    game_spec: GameSpec,
    attempt_number: int,
    previous_feedback: dict[str, object] | None,
) -> str:
    document_delta_instructions = (
        "Document delta rules:\n"
        "- section.title and section.body must be non-empty strings.\n"
        'Invalid example, do not output: "body": ""\n'
        "Required JSON shape:\n"
        "{\n"
        '  "artifact_id": "<game_spec.target_artifact_id>",\n'
        '  "operation": "append_section",\n'
        '  "payload": {\n'
        '    "section": {\n'
        '      "title": "<section title>",\n'
        '      "body": "Concrete non-empty section body text."\n'
        "    }\n"
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


def parse_document_delta_json(text: str) -> DeltaDocumentState:
    normalized = _normalize_json_candidate(text)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ValueError("blue model output must be valid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("blue model output must be a JSON object")

    required_keys = {"artifact_id", "operation", "payload"}
    if set(parsed.keys()) != required_keys:
        raise ValueError(
            "blue model output must contain exactly keys: artifact_id, operation, payload"
        )

    try:
        return DeltaDocumentState.model_validate(parsed)
    except Exception as exc:
        raise ValueError(
            f"blue model output failed DeltaDocumentState validation: {exc}"
        ) from exc


def derive_document_state_update_from_delta(delta_state: DeltaState) -> StateUpdateProposal:
    if not isinstance(delta_state, DeltaDocumentState):
        raise ValueError(f"unsupported delta type for integration: {type(delta_state).__name__}")
    if delta_state.operation != "append_section":
        raise ValueError(f"unsupported delta operation for integration: {delta_state.operation}")
    return StateUpdateProposal(
        id=f"state-update:{delta_state.artifact_id}:append_section",
        target=StateUpdateTarget(artifact_id=delta_state.artifact_id),
        summary=(
            f"Append section '{delta_state.payload.section.title}' "
            f"to document artifact {delta_state.artifact_id}"
        ),
        payload={
            "operation": "append_section",
            "section": delta_state.payload.section.model_dump(mode="json"),
        },
    )


def render_document_artifact_markdown(artifact: DocumentArtifact) -> str:
    sections = [f"## {section.title}\n\n{section.body}" for section in artifact.sections]
    return "\n\n".join(sections)


class DocumentProjectAdapter:
    project_type = "document"
    supported_delta_type = "DeltaDocumentState"

    def create_initial_state(self, config: dict[str, object]) -> State:
        northstar_markdown = _config_northstar_markdown(config)
        northstar_artifact = build_northstar_artifact_from_markdown(northstar_markdown)
        return State(
            northstar=NorthStar(artifacts=(northstar_artifact,)),
            artifacts=(DocumentArtifact(id=_config_artifact_id(config), sections=()),),
        )

    def build_create_game_state_view(self, state: State, config: dict[str, object]) -> StateView:
        return build_document_create_game_state_view(state, config)

    def build_state_view(self, state: State, game_spec: GameSpec) -> StateView:
        return build_document_state_view(state, game_spec)

    def render_blue_prompt(
        self,
        state_view: StateView,
        game_spec: GameSpec,
        attempt_number: int,
        previous_feedback: dict[str, object] | None,
    ) -> str:
        return render_document_blue_prompt(
            state_view=state_view,
            game_spec=game_spec,
            attempt_number=attempt_number,
            previous_feedback=previous_feedback,
        )

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

    def verify_export(self, output_path: Path) -> VerificationResult | None:
        del output_path
        return None
