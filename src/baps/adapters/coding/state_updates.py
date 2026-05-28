from __future__ import annotations

from baps.state.state import (
    DeleteFilePayload,
    DeltaCodingBatchState,
    DeltaCodingState,
    DeltaDeleteCodingState,
    DeltaState,
    StateUpdateProposal,
    StateUpdateTarget,
    WriteFilePayload,
    WriteFilesPayload,
)


def derive_coding_state_update_from_delta(delta_state: DeltaState) -> StateUpdateProposal:
    if isinstance(delta_state, DeltaCodingBatchState):
        paths = ", ".join(f.path for f in delta_state.payload.files)
        return StateUpdateProposal(
            id=f"state-update:{delta_state.artifact_id}:write_files:{len(delta_state.payload.files)}",
            target=StateUpdateTarget(artifact_id=delta_state.artifact_id),
            summary=(
                f"Write {len(delta_state.payload.files)} file(s) "
                f"({paths}) in coding artifact {delta_state.artifact_id}"
            ),
            payload=WriteFilesPayload(files=delta_state.payload.files),
        )
    if isinstance(delta_state, DeltaCodingState):
        return StateUpdateProposal(
            id=f"state-update:{delta_state.artifact_id}:write_file:{delta_state.payload.file.path}",
            target=StateUpdateTarget(artifact_id=delta_state.artifact_id),
            summary=(
                f"Write file '{delta_state.payload.file.path}' "
                f"in coding artifact {delta_state.artifact_id}"
            ),
            payload=WriteFilePayload(file=delta_state.payload.file),
        )
    if isinstance(delta_state, DeltaDeleteCodingState):
        return StateUpdateProposal(
            id=f"state-update:{delta_state.artifact_id}:delete_file:{delta_state.payload.path}",
            target=StateUpdateTarget(artifact_id=delta_state.artifact_id),
            summary=f"Delete file '{delta_state.payload.path}' from coding artifact {delta_state.artifact_id}",
            payload=DeleteFilePayload(path=delta_state.payload.path),
        )
    raise ValueError(f"unsupported delta type for integration: {type(delta_state).__name__}")
