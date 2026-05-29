from __future__ import annotations

from typing import Any

from baps.adapters.project_adapter import _config_artifact_id, _config_northstar_markdown, sanitize_model_string, sanitize_model_title
from baps.northstar.northstar_projection import ProjectionType, StateView, assemble_state_view
from baps.state.state import GameSpec, State

from .common import coding_artifact_from_state


def build_coding_create_game_state_view(state: State, config: dict[str, Any]) -> StateView:
    artifact_id = _config_artifact_id(config)
    target_artifact = coding_artifact_from_state(state, artifact_id)
    northstar_content = _config_northstar_markdown(config)

    _MAX_LINES_PER_FILE = 30

    file_lines: list[str] = []
    if target_artifact.files:
        for file in target_artifact.files:
            file_lines.append(f"### {sanitize_model_title(file.path)}")
            file_lines.append("")
            lines = file.content.splitlines()
            displayed = lines[:_MAX_LINES_PER_FILE] if len(lines) > _MAX_LINES_PER_FILE else lines
            fence = "````" if "```" in "\n".join(displayed) else "```"
            file_lines.append(fence)
            file_lines.extend(sanitize_model_string(line) for line in displayed)
            if len(lines) > _MAX_LINES_PER_FILE:
                file_lines.append(f"... ({len(lines) - _MAX_LINES_PER_FILE} more lines)")
            file_lines.append(fence)
            file_lines.append("")
    else:
        file_lines.append("No files.")

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
            f"files: {len(target_artifact.files)}",
            "",
            "### Current Files",
            "",
            *file_lines,
        ],
        metadata={
            "target_artifact_id": target_artifact.id,
            "language": target_artifact.language,
            "files": [file.model_dump(mode="json") for file in target_artifact.files],
        },
    )


def build_coding_state_view(state: State, game_spec: GameSpec) -> StateView:
    artifact = coding_artifact_from_state(state, game_spec.target_artifact_id)
    file_lines: list[str] = []
    if artifact.files:
        for file in artifact.files:
            file_lines.append(f"### {sanitize_model_title(file.path)}")
            file_lines.append("")
            fence = "````" if "```" in file.content else "```"
            file_lines.append(fence)
            file_lines.append(sanitize_model_string(file.content))
            file_lines.append(fence)
            file_lines.append("")
    else:
        file_lines.append("No files.")

    return assemble_state_view(
        stage="blue",
        artifact_id=artifact.id,
        projection_type=ProjectionType.PLAY_GAME,
        inner_lines=[
            "--- State Artifacts ---",
            "",
            f"## Artifact: {artifact.id}",
            "",
            f"kind: {artifact.kind}",
            "",
            "### Current Files",
            "",
            *file_lines,
        ],
        metadata={
            "target_artifact_id": artifact.id,
            "language": artifact.language,
            "files": [file.model_dump(mode="json") for file in artifact.files],
        },
    )
