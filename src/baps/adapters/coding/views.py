"""Builds CreateGame and PlayGame StateViews for coding-type projects."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from baps.adapters.project_adapter import _config_artifact_id, _config_northstar_markdown, sanitize_model_string, sanitize_model_title
from baps.northstar.northstar_projection import ProjectionType, StateView, assemble_state_view
from baps.state.state import GameSpec, State

if TYPE_CHECKING:
    from baps.summarizer.summarizer import SummarizationContext

from .common import coding_artifact_from_state


def build_coding_create_game_state_view(
    state: State,
    config: dict[str, Any],
    summarization_context: SummarizationContext | None = None,
) -> StateView:
    """Build the CreateGame StateView for a coding project, including NorthStar and current files."""
    artifact_id = _config_artifact_id(config)
    target_artifact = coding_artifact_from_state(state, artifact_id)
    northstar_content = _config_northstar_markdown(config)

    _MAX_LINES_PER_FILE = 30

    file_lines: list[str] = []
    if target_artifact.files:
        for file in target_artifact.files:
            lines = file.content.splitlines()
            line_count = len(lines)
            file_lines.append(f"### {sanitize_model_title(file.path)} ({line_count} lines)")
            file_lines.append("")
            summary = (
                summarization_context.summarize(file.content, objective=None)
                if summarization_context is not None
                else None
            )
            if summary is not None:
                file_lines.append(summary)
            else:
                displayed = lines[:_MAX_LINES_PER_FILE] if line_count > _MAX_LINES_PER_FILE else lines
                fence = "````" if "```" in "\n".join(displayed) else "```"
                file_lines.append(fence)
                file_lines.extend(sanitize_model_string(line) for line in displayed)
                if line_count > _MAX_LINES_PER_FILE:
                    file_lines.append(f"... ({line_count - _MAX_LINES_PER_FILE} more lines)")
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


def build_coding_state_view(
    state: State,
    game_spec: GameSpec,
    summarization_context: SummarizationContext | None = None,
) -> StateView:
    """Build the PlayGame StateView for a coding project, with per-file summaries when a summarizer is available."""
    artifact = coding_artifact_from_state(state, game_spec.target_artifact_id)
    target_entity = game_spec.target_entity
    file_lines: list[str] = []
    if artifact.files:
        for file in artifact.files:
            line_count = len(file.content.splitlines())
            if target_entity is not None and file.path != target_entity:
                summary = (
                    summarization_context.summarize(file.content, objective=game_spec.objective)
                    if summarization_context is not None
                    else None
                )
                if summary is not None:
                    file_lines.append(f"### {sanitize_model_title(file.path)} ({line_count} lines) [summary]")
                    file_lines.append("")
                    file_lines.append(summary)
                    file_lines.append("")
                    continue
                file_lines.append(f"### {sanitize_model_title(file.path)} ({line_count} lines) [full]")
            elif target_entity is not None:
                file_lines.append(f"### {sanitize_model_title(file.path)} ({line_count} lines) [full]")
            else:
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
