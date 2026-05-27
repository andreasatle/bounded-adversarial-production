from __future__ import annotations

import hashlib
import json
import unicodedata
from enum import StrEnum
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny, model_validator, field_validator


class Disposition(StrEnum):
    accept = "accept"
    revise = "revise"
    reject = "reject"


class StopReason(StrEnum):
    ITERATION_LIMIT_REACHED = "iteration_limit_reached"
    CREATE_GAME_NO_NEW_GAME = "create_game_no_new_game"
    PLAY_GAME_NO_DELTA = "play_game_no_delta"
    NO_STATE_CHANGE = "no_state_change"
    NORTHSTAR_UPDATE_PROPOSED = "northstar_update_proposed"
    MAX_DEPTH_REACHED = "max_depth_reached"
    NOT_RUN = "not_run"
    ERROR = "error"
    UNKNOWN = "unknown"


_MAX_SECTION_BODY_BYTES = 65536
_MAX_CODEFILE_PATH_BYTES = 4096
_MAX_CODEFILE_CONTENT_BYTES = 65536


def _require_non_empty(value: str) -> str:
    if not unicodedata.normalize("NFKC", value).strip():
        raise ValueError("must be a non-empty string")
    return value


def _coerce_state_artifact(value: object) -> StateArtifact:
    if isinstance(value, (DocumentArtifact, CodingArtifact, StateArtifact)):
        return value
    if not isinstance(value, dict):
        raise TypeError("artifact entries must be StateArtifact-compatible values")
    kind = value.get("kind")
    if kind == "document":
        return DocumentArtifact.model_validate(value)
    if kind == "coding":
        return CodingArtifact.model_validate(value)
    return StateArtifact.model_validate(value)


class StateArtifact(BaseModel):
    id: str
    kind: str

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_kind = field_validator("kind")(_require_non_empty)

    def render_as_text(self) -> str:
        return ""


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Annotated[str, Field(strict=True)]
    body: Annotated[str, Field(strict=True)]
    source_hash: str | None = None

    _validate_title = field_validator("title")(_require_non_empty)

    @field_validator("body")
    @classmethod
    def _validate_body(cls, value: str) -> str:
        _require_non_empty(value)
        if len(value.encode("utf-8")) > _MAX_SECTION_BODY_BYTES:
            raise ValueError(f"section body must not exceed {_MAX_SECTION_BODY_BYTES} bytes")
        return value


class DocumentArtifact(StateArtifact):
    kind: Literal["document"] = "document"
    sections: tuple[Section, ...] = ()

    def render_as_text(self) -> str:
        return "\n\n".join(section.body for section in self.sections)

    def apply_delta(self, delta: DeltaState) -> DocumentArtifact:
        if isinstance(delta, DeltaDocumentState):
            return DocumentArtifact(
                id=self.id,
                sections=(*self.sections, delta.payload.section),
            )
        if isinstance(delta, DeltaModifyDocumentState):
            title = delta.payload.section_title
            if not any(s.title == title for s in self.sections):
                raise ValueError(
                    f"modify_section: no section with title {title!r} in artifact {self.id!r}"
                )
            return DocumentArtifact(
                id=self.id,
                sections=tuple(
                    Section(title=s.title, body=delta.payload.new_body)
                    if s.title == title
                    else s
                    for s in self.sections
                ),
            )
        if isinstance(delta, DeltaDeleteDocumentState):
            title = delta.payload.section_title
            if not any(s.title == title for s in self.sections):
                raise ValueError(
                    f"delete_section: no section with title {title!r} in artifact {self.id!r}"
                )
            return DocumentArtifact(
                id=self.id,
                sections=tuple(s for s in self.sections if s.title != title),
            )
        raise ValueError(
            f"DocumentArtifact does not support delta type: {type(delta).__name__}"
        )


class CodeFile(BaseModel):
    path: Annotated[str, Field(strict=True)]
    content: Annotated[str, Field(strict=True)]

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        _require_non_empty(value)
        if len(value.encode("utf-8")) > _MAX_CODEFILE_PATH_BYTES:
            raise ValueError(f"file path must not exceed {_MAX_CODEFILE_PATH_BYTES} bytes")
        return value

    @field_validator("content")
    @classmethod
    def _validate_content_length(cls, value: str) -> str:
        if len(value.encode("utf-8")) > _MAX_CODEFILE_CONTENT_BYTES:
            raise ValueError(f"file content must not exceed {_MAX_CODEFILE_CONTENT_BYTES} bytes")
        return value


class CodingArtifact(StateArtifact):
    kind: Literal["coding"] = "coding"
    language: str = "python"
    files: tuple[CodeFile, ...] = ()

    def apply_delta(self, delta: DeltaState) -> CodingArtifact:
        if isinstance(delta, DeltaCodingState):
            files_by_path = {f.path: f for f in self.files}
            files_by_path[delta.payload.file.path] = delta.payload.file
            return CodingArtifact(id=self.id, language=self.language, files=tuple(files_by_path.values()))
        if isinstance(delta, DeltaCodingBatchState):
            files_by_path = {f.path: f for f in self.files}
            for incoming in delta.payload.files:
                files_by_path[incoming.path] = incoming
            return CodingArtifact(id=self.id, language=self.language, files=tuple(files_by_path.values()))
        if isinstance(delta, DeltaDeleteCodingState):
            path = delta.payload.path
            if not any(f.path == path for f in self.files):
                raise ValueError(
                    f"delete_file: no file with path {path!r} in artifact {self.id!r}"
                )
            return CodingArtifact(
                id=self.id,
                language=self.language,
                files=tuple(f for f in self.files if f.path != path),
            )
        raise ValueError(
            f"CodingArtifact does not support delta type: {type(delta).__name__}"
        )


class AppendSectionDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section: Section


class ModifySectionDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section_title: str
    new_body: str

    _validate_section_title = field_validator("section_title")(_require_non_empty)

    @field_validator("new_body")
    @classmethod
    def _validate_new_body(cls, value: str) -> str:
        _require_non_empty(value)
        if len(value.encode("utf-8")) > _MAX_SECTION_BODY_BYTES:
            raise ValueError(f"section body must not exceed {_MAX_SECTION_BODY_BYTES} bytes")
        return value


class DeleteSectionDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section_title: str

    _validate_section_title = field_validator("section_title")(_require_non_empty)


class WriteFileDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file: CodeFile


class WriteFilesDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: tuple[CodeFile, ...]

    @field_validator("files")
    @classmethod
    def _validate_non_empty(cls, files: tuple) -> tuple:
        if not files:
            raise ValueError("write_files payload must contain at least one file")
        return files


class DeleteFileDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str

    _validate_path = field_validator("path")(_require_non_empty)


class DeltaState(BaseModel):
    artifact_id: str

    _validate_artifact_id = field_validator("artifact_id")(_require_non_empty)


class DeltaDocumentState(DeltaState):
    operation: Literal["append_section"]
    payload: AppendSectionDelta


class DeltaModifyDocumentState(DeltaState):
    operation: Literal["modify_section"]
    payload: ModifySectionDelta


class DeltaDeleteDocumentState(DeltaState):
    operation: Literal["delete_section"]
    payload: DeleteSectionDelta


class DeltaCodingState(DeltaState):
    operation: Literal["write_file"]
    payload: WriteFileDelta


class DeltaCodingBatchState(DeltaState):
    operation: Literal["write_files"]
    payload: WriteFilesDelta


class DeltaDeleteCodingState(DeltaState):
    operation: Literal["delete_file"]
    payload: DeleteFileDelta


# ---------------------------------------------------------------------------
# Typed payload models for StateUpdateProposal
# ---------------------------------------------------------------------------

class AppendSectionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["append_section"] = "append_section"
    section: Section


class ModifySectionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["modify_section"] = "modify_section"
    section_title: str
    new_body: str

    _validate_section_title = field_validator("section_title")(_require_non_empty)

    @field_validator("new_body")
    @classmethod
    def _validate_new_body(cls, value: str) -> str:
        _require_non_empty(value)
        if len(value.encode("utf-8")) > _MAX_SECTION_BODY_BYTES:
            raise ValueError(f"section body must not exceed {_MAX_SECTION_BODY_BYTES} bytes")
        return value


class DeleteSectionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["delete_section"] = "delete_section"
    section_title: str

    _validate_section_title = field_validator("section_title")(_require_non_empty)


class WriteFilePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["write_file"] = "write_file"
    file: CodeFile


class WriteFilesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["write_files"] = "write_files"
    files: tuple[CodeFile, ...]

    @field_validator("files")
    @classmethod
    def _validate_non_empty(cls, files: tuple) -> tuple:
        if not files:
            raise ValueError("write_files payload must contain at least one file")
        return files


class DeleteFilePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["delete_file"] = "delete_file"
    path: str

    _validate_path = field_validator("path")(_require_non_empty)


class NoFindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["no_finding"] = "no_finding"
    file: str
    rationale: str

    _validate_file = field_validator("file")(_require_non_empty)
    _validate_rationale = field_validator("rationale")(_require_non_empty)


class AddArtifactPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["add_artifact"] = "add_artifact"
    artifact: dict[str, object]


class ReplaceArtifactPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["replace_artifact"] = "replace_artifact"
    artifact: dict[str, object]


StateUpdatePayload = Annotated[
    AppendSectionPayload
    | ModifySectionPayload
    | DeleteSectionPayload
    | WriteFilePayload
    | WriteFilesPayload
    | DeleteFilePayload
    | NoFindingPayload
    | AddArtifactPayload
    | ReplaceArtifactPayload,
    Field(discriminator="operation"),
]


class GameSpec(BaseModel):
    objective: str
    target_artifact_id: str
    allowed_delta_type: str
    success_condition: str
    context_chain: tuple[str, ...] = ()
    max_words: int | None = None

    _validate_objective = field_validator("objective")(_require_non_empty)
    _validate_target_artifact_id = field_validator("target_artifact_id")(_require_non_empty)
    _validate_allowed_delta_type = field_validator("allowed_delta_type")(_require_non_empty)
    _validate_success_condition = field_validator("success_condition")(_require_non_empty)


class SubGapSpec(BaseModel):
    description: str
    _validate_description = field_validator("description")(_require_non_empty)


class DecomposeSpec(BaseModel):
    rationale: str
    sub_gaps: tuple[SubGapSpec, ...]
    _validate_rationale = field_validator("rationale")(_require_non_empty)


class RedFinding(BaseModel):
    disposition: Disposition
    rationale: str
    success_condition_met: bool | None = None
    findings: tuple[str, ...] = ()

    _validate_rationale = field_validator("rationale")(_require_non_empty)


class RefereeDecision(BaseModel):
    disposition: Disposition
    rationale: str
    red_override: bool | None = None
    improvement_hints: tuple[str, ...] = ()

    _validate_rationale = field_validator("rationale")(_require_non_empty)


class PlayGameRuntime(BaseModel):
    current_best_delta: SerializeAsAny[DeltaState] | None = None


def apply_referee_decision_to_runtime(
    runtime: PlayGameRuntime,
    candidate_delta: DeltaState,
    decision: RefereeDecision,
) -> PlayGameRuntime:
    if decision.disposition in (Disposition.accept, Disposition.revise):
        # Accept: done. Revise: promising — promote as best fallback for exhausted attempts.
        return PlayGameRuntime(current_best_delta=candidate_delta.model_copy(deep=True))
    # Reject: wrong direction — discard candidate, keep previous best.
    return PlayGameRuntime(
        current_best_delta=(
            runtime.current_best_delta.model_copy(deep=True)
            if runtime.current_best_delta is not None
            else None
        )
    )


class NorthStar(BaseModel):
    artifacts: tuple[SerializeAsAny[StateArtifact], ...]

    def render_content(self) -> str:
        """Render all artifact text representations joined for prompt consumption."""
        parts = [a.render_as_text() for a in self.artifacts]
        return "\n\n".join(p for p in parts if p).strip()

    @field_validator("artifacts", mode="before")
    @classmethod
    def _coerce_artifact_types(
        cls, artifacts: object
    ) -> tuple[SerializeAsAny[StateArtifact], ...]:
        if not isinstance(artifacts, (list, tuple)):
            raise TypeError("northstar artifacts must be a list or tuple")
        return tuple(_coerce_state_artifact(artifact) for artifact in artifacts)

    @field_validator("artifacts")
    @classmethod
    def _validate_unique_artifact_ids(
        cls, artifacts: tuple[SerializeAsAny[StateArtifact], ...]
    ) -> tuple[SerializeAsAny[StateArtifact], ...]:
        ids = [artifact.id for artifact in artifacts]
        if len(ids) != len(set(ids)):
            raise ValueError("northstar artifact ids must be unique")
        return artifacts


class State(BaseModel):
    artifacts: tuple[SerializeAsAny[StateArtifact], ...] = ()

    @field_validator("artifacts", mode="before")
    @classmethod
    def _coerce_artifact_types(
        cls, artifacts: object
    ) -> tuple[SerializeAsAny[StateArtifact], ...]:
        if not isinstance(artifacts, (list, tuple)):
            raise TypeError("state artifacts must be a list or tuple")
        return tuple(_coerce_state_artifact(artifact) for artifact in artifacts)

    @field_validator("artifacts")
    @classmethod
    def _validate_unique_artifact_ids(
        cls, artifacts: tuple[SerializeAsAny[StateArtifact], ...]
    ) -> tuple[SerializeAsAny[StateArtifact], ...]:
        ids = [artifact.id for artifact in artifacts]
        if len(ids) != len(set(ids)):
            raise ValueError("state artifact ids must be unique")
        return artifacts


class StateUpdateTarget(BaseModel):
    artifact_id: str
    section: str | None = None

    _validate_artifact_id = field_validator("artifact_id")(_require_non_empty)

    @field_validator("section")
    @classmethod
    def _validate_optional_section(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)


class StateUpdateProposal(BaseModel):
    id: str
    target: StateUpdateTarget
    summary: str
    payload: StateUpdatePayload
    base_state_fingerprint: str | None = None

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_summary = field_validator("summary")(_require_non_empty)

    @field_validator("base_state_fingerprint")
    @classmethod
    def _validate_optional_base_state_fingerprint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)


class StateProjection(BaseModel):
    artifacts: tuple[str, ...] = ()


def fingerprint_state(state: State) -> str:
    canonical = json.dumps(
        state.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_update_base_state(state: State, proposal: StateUpdateProposal) -> bool:
    if proposal.base_state_fingerprint is None:
        return True
    return proposal.base_state_fingerprint == fingerprint_state(state)


def find_state_artifact(state: State, artifact_id: str) -> StateArtifact:
    resolved_artifact_id = _require_non_empty(artifact_id)
    for artifact in state.artifacts:
        if artifact.id == resolved_artifact_id:
            return artifact
    raise ValueError(f"artifact id not found in state: {resolved_artifact_id}")


def _replace_artifact_in_state(
    state: State, artifact_id: str, replacement: StateArtifact
) -> State:
    new_artifacts = tuple(
        replacement if a.id == artifact_id else a
        for a in state.artifacts
    )
    return State(artifacts=new_artifacts)


def apply_state_update(state: State, proposal: StateUpdateProposal) -> State:
    """Apply a StateUpdateProposal to State.

    For operations that have typed DeltaState equivalents (append_section,
    modify_section, delete_section, write_file, write_files, delete_file,
    no_finding), delegates to apply_state_delta so all durable mutation flows
    through the single canonical path.

    Operations add_artifact and replace_artifact have no typed delta equivalent
    and are handled directly here.
    """
    p = proposal.payload
    target_artifact_id = proposal.target.artifact_id

    if isinstance(p, WriteFilePayload):
        return apply_state_delta(state, DeltaCodingState(
            artifact_id=target_artifact_id,
            operation="write_file",
            payload=WriteFileDelta(file=p.file),
        ))

    if isinstance(p, WriteFilesPayload):
        return apply_state_delta(state, DeltaCodingBatchState(
            artifact_id=target_artifact_id,
            operation="write_files",
            payload=WriteFilesDelta(files=p.files),
        ))

    if isinstance(p, AppendSectionPayload):
        return apply_state_delta(state, DeltaDocumentState(
            artifact_id=target_artifact_id,
            operation="append_section",
            payload=AppendSectionDelta(section=p.section),
        ))

    if isinstance(p, ModifySectionPayload):
        return apply_state_delta(state, DeltaModifyDocumentState(
            artifact_id=target_artifact_id,
            operation="modify_section",
            payload=ModifySectionDelta(section_title=p.section_title, new_body=p.new_body),
        ))

    if isinstance(p, DeleteSectionPayload):
        return apply_state_delta(state, DeltaDeleteDocumentState(
            artifact_id=target_artifact_id,
            operation="delete_section",
            payload=DeleteSectionDelta(section_title=p.section_title),
        ))

    if isinstance(p, DeleteFilePayload):
        return apply_state_delta(state, DeltaDeleteCodingState(
            artifact_id=target_artifact_id,
            operation="delete_file",
            payload=DeleteFileDelta(path=p.path),
        ))

    if isinstance(p, NoFindingPayload):
        return apply_state_delta(state, DeltaDocumentState(
            artifact_id=target_artifact_id,
            operation="append_section",
            payload=AppendSectionDelta(section=Section(
                title=f"Audited: {p.file}",
                body=p.rationale,
            )),
        ))

    if isinstance(p, AddArtifactPayload):
        artifact_data = p.artifact
        if "sections" in artifact_data:
            added_artifact = DocumentArtifact.model_validate(artifact_data)
        elif "files" in artifact_data:
            added_artifact = CodingArtifact.model_validate(artifact_data)
        else:
            added_artifact = StateArtifact.model_validate(artifact_data)
        return State(artifacts=(*state.artifacts, added_artifact))

    # isinstance(p, ReplaceArtifactPayload)
    existing = find_state_artifact(state, target_artifact_id)
    replacement = _coerce_state_artifact(p.artifact)

    if replacement.id != target_artifact_id:
        raise ValueError(
            "replacement artifact id must match proposal.target.artifact_id: "
            f"expected {target_artifact_id}, got {replacement.id}"
        )
    if replacement.kind != existing.kind:
        raise ValueError(
            "replacement artifact kind must match existing artifact kind: "
            f"expected {existing.kind}, got {replacement.kind}"
        )

    return _replace_artifact_in_state(state, target_artifact_id, replacement)


def apply_state_delta(state: State, delta: DeltaState) -> State:
    """Apply a typed DeltaState directly to State via the artifact's own apply_delta method."""
    artifact_id = delta.artifact_id
    artifact = next((a for a in state.artifacts if a.id == artifact_id), None)
    if artifact is None:
        raise ValueError(f"mutable artifact not found in state: {artifact_id!r}")
    if not hasattr(artifact, "apply_delta"):
        raise ValueError(
            f"artifact kind {artifact.kind!r} does not implement apply_delta"
        )
    updated = artifact.apply_delta(delta)
    return State(
        artifacts=tuple(updated if a.id == artifact_id else a for a in state.artifacts),
    )


def validate_state_artifacts(state: State, registry: StateArtifactRegistry) -> State:
    def _validate_one(artifact: StateArtifact) -> StateArtifact:
        if isinstance(artifact, DocumentArtifact):
            return artifact
        if isinstance(artifact, CodingArtifact):
            return artifact
        adapter = registry.resolve(artifact.kind)
        validated = adapter.validate_artifact(artifact)
        if validated.id != artifact.id:
            raise ValueError(
                f"adapter must not change artifact id: expected {artifact.id}, got {validated.id}"
            )
        if validated.kind != artifact.kind:
            raise ValueError(
                "adapter must not change artifact kind: "
                f"expected {artifact.kind}, got {validated.kind}"
            )
        return validated

    validated_state_artifacts = tuple(_validate_one(artifact) for artifact in state.artifacts)

    return State(
        artifacts=validated_state_artifacts,
    )


def project_state(state: State, registry: StateArtifactRegistry) -> StateProjection:
    def _project_one(artifact: StateArtifact) -> str:
        if isinstance(artifact, DocumentArtifact):
            titles = ", ".join(section.title for section in artifact.sections) or "no sections"
            projection = f"document artifact: {artifact.id} ({titles})"
            if not projection.strip():
                raise ValueError(
                    f"artifact projection must be a non-empty string for artifact id: {artifact.id}"
                )
            return projection
        if isinstance(artifact, CodingArtifact):
            paths = ", ".join(file.path for file in artifact.files) or "no files"
            projection = f"coding artifact: {artifact.id} ({paths})"
            if not projection.strip():
                raise ValueError(
                    f"artifact projection must be a non-empty string for artifact id: {artifact.id}"
                )
            return projection
        adapter = registry.resolve(artifact.kind)
        projection = adapter.project_artifact(artifact)
        if not projection.strip():
            raise ValueError(
                f"artifact projection must be a non-empty string for artifact id: {artifact.id}"
            )
        return projection

    projected_artifacts = tuple(_project_one(artifact) for artifact in state.artifacts)
    return StateProjection(artifacts=projected_artifacts)


class StateArtifactAdapter(Protocol):
    kind: str

    def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
        ...

    def project_artifact(self, artifact: StateArtifact) -> str:
        ...


class StateArtifactRegistry:
    def __init__(self):
        self._adapters: dict[str, StateArtifactAdapter] = {}

    def register(self, adapter: StateArtifactAdapter) -> None:
        kind = adapter.kind
        if not kind.strip():
            raise ValueError("adapter kind must be a non-empty string")
        if kind in self._adapters:
            raise ValueError(f"adapter kind already registered: {kind}")
        self._adapters[kind] = adapter

    def resolve(self, kind: str) -> StateArtifactAdapter:
        adapter = self._adapters.get(kind)
        if adapter is None:
            raise ValueError(f"unknown artifact kind: {kind}")
        return adapter


class DocumentArtifactAdapter:
    kind = "document"

    def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
        return artifact

    def project_artifact(self, artifact: StateArtifact) -> str:
        return f"document artifact: {artifact.id}"


class GitRepositoryArtifactAdapter:
    kind = "git_repository"

    def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
        return artifact

    def project_artifact(self, artifact: StateArtifact) -> str:
        return f"git repository artifact: {artifact.id}"


class CodingArtifactAdapter:
    kind = "coding"

    def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
        return artifact

    def project_artifact(self, artifact: StateArtifact) -> str:
        return f"coding artifact: {artifact.id}"


def build_default_state_artifact_registry() -> StateArtifactRegistry:
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())
    registry.register(CodingArtifactAdapter())
    registry.register(GitRepositoryArtifactAdapter())
    return registry
