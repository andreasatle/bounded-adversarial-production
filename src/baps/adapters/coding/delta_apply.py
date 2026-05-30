from __future__ import annotations

from baps.state.state import CodeFile, DeltaCodingBatchState, DeltaCodingState, DeltaDeleteCodingState, DeltaState


def _normalize_coding_export_content(content: str) -> str:
    """Unescape JSON-encoded escape sequences in file content when no real newlines are present."""
    if "\n" in content:
        return content
    if "\\n" not in content and "\\t" not in content and '\\"' not in content:
        return content
    return content.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')


def _apply_delta_to_files(
    current_files: tuple[CodeFile, ...],
    delta: DeltaState,
) -> list[CodeFile]:
    """Apply a coding delta to a file list, replacing or removing the affected file."""
    files = list(current_files)
    if isinstance(delta, DeltaCodingBatchState):
        for new_file in delta.payload.files:
            files = [f for f in files if f.path != new_file.path]
            files.append(new_file)
    elif isinstance(delta, DeltaCodingState):
        new_file = delta.payload.file
        files = [f for f in files if f.path != new_file.path]
        files.append(new_file)
    elif isinstance(delta, DeltaDeleteCodingState):
        files = [f for f in files if f.path != delta.payload.path]
    return files
