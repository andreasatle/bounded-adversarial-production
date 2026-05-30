"""Authoritative state types, delta operations, artifact registry, and state mutation helpers."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from enum import StrEnum
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny, field_validator


class Disposition(StrEnum):
    """Valid disposition values for Red and Referee role decisions."""

    accept = "accept"
    revise = "revise"
    reject = "reject"


class StopReason(StrEnum):
    """Identifies why the orchestration loop terminated."""

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
    """Raise ValueError if value normalises to whitespace-only; used as a Pydantic field validator."""
    if not unicodedata.normalize("NFKC", value).strip():
        raise ValueError("must be a non-empty string")
    return value


def _coerce_state_artifact(value: object) -> StateArtifact:
    """Deserialize a raw value into the most specific StateArtifact subtype based on its kind field."""
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
    """Base class for all artifacts stored in State; identified by id and kind."""

    id: str
    kind: str

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_kind = field_validator("kind")(_require_non_empty)

    def render_as_text(self) -> str:
        """Return a text representation of this artifact for prompt consumption."""
        return ""


class Section(BaseModel):
    """A named, bounded body of text that is the structural unit of a DocumentArtifact."""

    model_config = ConfigDict(extra="forbid")
    title: Annotated[str, Field(strict=True)]
    body: Annotated[str, Field(strict=True)]
    source_hash: str | None = None

    _validate_title = field_validator("title")(_require_non_empty)

    @field_validator("body")
    @classmethod
    def _validate_body(cls, value: str) -> str:
        """Validate that body is non-empty and within the byte size limit."""
        _require_non_empty(value)
        if len(value.encode("utf-8")) > _MAX_SECTION_BODY_BYTES:
            raise ValueError(f"section body must not exceed {_MAX_SECTION_BODY_BYTES} bytes")
        return value


class DocumentArtifact(StateArtifact):
    """A document-type artifact composed of an ordered sequence of named Sections."""

    kind: Literal["document"] = "document"
    sections: tuple[Section, ...] = ()

    def render_as_text(self) -> str:
        """Return all section bodies joined by double newlines."""
        return "\n\n".join(section.body for section in self.sections)

    def apply_delta(self, delta: DeltaState) -> DocumentArtifact:
        """Apply a document delta (append/modify/delete section) and return the updated artifact."""
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
    """A single file stored inside a CodingArtifact, identified by a relative path."""

    path: Annotated[str, Field(strict=True)]
    content: Annotated[str, Field(strict=True)]

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        """Validate that path is non-empty and within the byte limit."""
        _require_non_empty(value)
        if len(value.encode("utf-8")) > _MAX_CODEFILE_PATH_BYTES:
            raise ValueError(f"file path must not exceed {_MAX_CODEFILE_PATH_BYTES} bytes")
        return value

    @field_validator("content")
    @classmethod
    def _validate_content_length(cls, value: str) -> str:
        """Validate that content is within the byte size limit."""
        if len(value.encode("utf-8")) > _MAX_CODEFILE_CONTENT_BYTES:
            raise ValueError(f"file content must not exceed {_MAX_CODEFILE_CONTENT_BYTES} bytes")
        return value


class CodingArtifact(StateArtifact):
    """A coding-type artifact storing a set of source files keyed by relative path."""

    kind: Literal["coding"] = "coding"
    language: str = "python"
    files: tuple[CodeFile, ...] = ()

    def apply_delta(self, delta: DeltaState) -> CodingArtifact:
        """Apply a coding delta (write/delete file(s)) and return the updated artifact."""
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
    """Payload for the append_section operation: a Section to append to a document."""

    model_config = ConfigDict(extra="forbid")
    section: Section


class ModifySectionDelta(BaseModel):
    """Payload for the modify_section operation: identifies the target section and provides the new body."""

    model_config = ConfigDict(extra="forbid")
    section_title: str
    new_body: str

    _validate_section_title = field_validator("section_title")(_require_non_empty)

    @field_validator("new_body")
    @classmethod
    def _validate_new_body(cls, value: str) -> str:
        """Validate that new_body is non-empty and within the byte size limit."""
        _require_non_empty(value)
        if len(value.encode("utf-8")) > _MAX_SECTION_BODY_BYTES:
            raise ValueError(f"section body must not exceed {_MAX_SECTION_BODY_BYTES} bytes")
        return value


class DeleteSectionDelta(BaseModel):
    """Payload for the delete_section operation: identifies the section to remove by title."""

    model_config = ConfigDict(extra="forbid")
    section_title: str

    _validate_section_title = field_validator("section_title")(_require_non_empty)


class WriteFileDelta(BaseModel):
    """Payload for the write_file operation: a single CodeFile to write."""

    model_config = ConfigDict(extra="forbid")
    file: CodeFile


class WriteFilesDelta(BaseModel):
    """Payload for the write_files operation: one or more CodeFiles to write atomically."""

    model_config = ConfigDict(extra="forbid")
    files: tuple[CodeFile, ...]

    @field_validator("files")
    @classmethod
    def _validate_non_empty(cls, files: tuple) -> tuple:
        """Validate that at least one file is present in the write_files payload."""
        if not files:
            raise ValueError("write_files payload must contain at least one file")
        return files


class DeleteFileDelta(BaseModel):
    """Payload for the delete_file operation: the relative path of the file to remove."""

    model_config = ConfigDict(extra="forbid")
    path: str

    _validate_path = field_validator("path")(_require_non_empty)


class DeltaState(BaseModel):
    """Base class for all typed delta operations; identifies the target artifact."""

    artifact_id: str

    _validate_artifact_id = field_validator("artifact_id")(_require_non_empty)


class DeltaDocumentState(DeltaState):
    """Delta that appends a new section to a document artifact."""

    operation: Literal["append_section"]
    payload: AppendSectionDelta


class DeltaModifyDocumentState(DeltaState):
    """Delta that replaces the body of an existing named section in a document artifact."""

    operation: Literal["modify_section"]
    payload: ModifySectionDelta


class DeltaDeleteDocumentState(DeltaState):
    """Delta that removes a named section from a document artifact."""

    operation: Literal["delete_section"]
    payload: DeleteSectionDelta


class DeltaCodingState(DeltaState):
    """Delta that writes (creates or replaces) a single file in a coding artifact."""

    operation: Literal["write_file"]
    payload: WriteFileDelta


class DeltaCodingBatchState(DeltaState):
    """Delta that writes (creates or replaces) multiple files in a coding artifact atomically."""

    operation: Literal["write_files"]
    payload: WriteFilesDelta


class DeltaDeleteCodingState(DeltaState):
    """Delta that removes a file from a coding artifact."""

    operation: Literal["delete_file"]
    payload: DeleteFileDelta


class GameSpec(BaseModel):
    """Describes a single atomic gap-closing task: objective, target, allowed delta, and success condition."""

    objective: str
    target_artifact_id: str
    allowed_delta_type: str
    success_condition: str
    context_chain: tuple[str, ...] = ()
    max_words: int | None = None
    target_entity: str | None = None

    _validate_objective = field_validator("objective")(_require_non_empty)
    _validate_target_artifact_id = field_validator("target_artifact_id")(_require_non_empty)
    _validate_allowed_delta_type = field_validator("allowed_delta_type")(_require_non_empty)
    _validate_success_condition = field_validator("success_condition")(_require_non_empty)


class SubGapSpec(BaseModel):
    """A single decomposed sub-gap description within a DecomposeSpec."""

    description: str
    _validate_description = field_validator("description")(_require_non_empty)


class DecomposeSpec(BaseModel):
    """Returned by create_game to indicate the gap should be decomposed into ordered sub-gaps."""

    rationale: str
    sub_gaps: tuple[SubGapSpec, ...]
    _validate_rationale = field_validator("rationale")(_require_non_empty)


class RedFinding(BaseModel):
    """Structured output from the Red role containing its disposition and adversarial findings."""

    disposition: Disposition
    rationale: str
    success_condition_met: bool | None = None
    findings: tuple[str, ...] = ()

    _validate_rationale = field_validator("rationale")(_require_non_empty)


class RefereeDecision(BaseModel):
    """Structured output from the Referee role with the final accept/revise/reject decision."""

    disposition: Disposition
    rationale: str
    red_override: bool | None = None
    improvement_hints: tuple[str, ...] = ()

    _validate_rationale = field_validator("rationale")(_require_non_empty)


class PlayGameRuntime(BaseModel):
    """Tracks the current-best and integration-eligible deltas as play_game attempts progress."""

    current_best_delta: SerializeAsAny[DeltaState] | None = None
    integration_eligible_delta: SerializeAsAny[DeltaState] | None = None


def apply_referee_decision_to_runtime(
    runtime: PlayGameRuntime,
    candidate_delta: DeltaState,
    decision: RefereeDecision,
) -> PlayGameRuntime:
    """Return an updated PlayGameRuntime reflecting the Referee's accept/revise/reject decision."""
    if decision.disposition == Disposition.accept:
        accepted = candidate_delta.model_copy(deep=True)
        return PlayGameRuntime(
            current_best_delta=accepted,
            integration_eligible_delta=accepted.model_copy(deep=True),
        )
    if decision.disposition == Disposition.revise:
        # Revise updates search guidance via feedback but is not integration-eligible
        # and must not promote the candidate to current_best_delta. Keep both fields
        # unchanged so current_best_delta only ever holds an accepted candidate.
        return PlayGameRuntime(
            current_best_delta=(
                runtime.current_best_delta.model_copy(deep=True)
                if runtime.current_best_delta is not None
                else None
            ),
            integration_eligible_delta=(
                runtime.integration_eligible_delta.model_copy(deep=True)
                if runtime.integration_eligible_delta is not None
                else None
            ),
        )
    # Reject: wrong direction — discard candidate, keep previous progress state.
    return PlayGameRuntime(
        current_best_delta=(
            runtime.current_best_delta.model_copy(deep=True)
            if runtime.current_best_delta is not None
            else None
        ),
        integration_eligible_delta=(
            runtime.integration_eligible_delta.model_copy(deep=True)
            if runtime.integration_eligible_delta is not None
            else None
        ),
    )


class NorthStar(BaseModel):
    """Immutable NorthStar holding goal artifacts used to scope the automated pipeline."""

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
        """Deserialize each artifact entry to the most specific StateArtifact subtype."""
        if not isinstance(artifacts, (list, tuple)):
            raise TypeError("northstar artifacts must be a list or tuple")
        return tuple(_coerce_state_artifact(artifact) for artifact in artifacts)

    @field_validator("artifacts")
    @classmethod
    def _validate_unique_artifact_ids(
        cls, artifacts: tuple[SerializeAsAny[StateArtifact], ...]
    ) -> tuple[SerializeAsAny[StateArtifact], ...]:
        """Raise ValueError if any two NorthStar artifacts share an id."""
        ids = [artifact.id for artifact in artifacts]
        if len(ids) != len(set(ids)):
            raise ValueError("northstar artifact ids must be unique")
        return artifacts


class State(BaseModel):
    """The authoritative runtime state: a tuple of typed artifacts keyed by unique id."""

    artifacts: tuple[SerializeAsAny[StateArtifact], ...] = ()

    @field_validator("artifacts", mode="before")
    @classmethod
    def _coerce_artifact_types(
        cls, artifacts: object
    ) -> tuple[SerializeAsAny[StateArtifact], ...]:
        """Deserialize each artifact entry to the most specific StateArtifact subtype."""
        if not isinstance(artifacts, (list, tuple)):
            raise TypeError("state artifacts must be a list or tuple")
        return tuple(_coerce_state_artifact(artifact) for artifact in artifacts)

    @field_validator("artifacts")
    @classmethod
    def _validate_unique_artifact_ids(
        cls, artifacts: tuple[SerializeAsAny[StateArtifact], ...]
    ) -> tuple[SerializeAsAny[StateArtifact], ...]:
        """Raise ValueError if any two State artifacts share an id."""
        ids = [artifact.id for artifact in artifacts]
        if len(ids) != len(set(ids)):
            raise ValueError("state artifact ids must be unique")
        return artifacts


class StateProjection(BaseModel):
    """A read-only projection of State as ordered text strings, one per artifact."""

    artifacts: tuple[str, ...] = ()


def fingerprint_state(state: State) -> str:
    """Return a deterministic SHA-256 hex fingerprint of the canonically serialised State."""
    canonical = json.dumps(
        state.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def find_state_artifact(state: State, artifact_id: str) -> StateArtifact:
    """Return the artifact with the given id from State, raising ValueError if not found."""
    resolved_artifact_id = _require_non_empty(artifact_id)
    for artifact in state.artifacts:
        if artifact.id == resolved_artifact_id:
            return artifact
    raise ValueError(f"artifact id not found in state: {resolved_artifact_id}")


def _replace_artifact_in_state(
    state: State, artifact_id: str, replacement: StateArtifact
) -> State:
    """Return a new State with the artifact matching artifact_id replaced by replacement."""
    new_artifacts = tuple(
        replacement if a.id == artifact_id else a
        for a in state.artifacts
    )
    return State(artifacts=new_artifacts)


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
    """Validate all artifacts in State through their registered adapters and return the validated State."""
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
    """Project each artifact in State to a non-empty text string and return a StateProjection."""
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
    """Protocol for kind-specific artifact validation and text projection."""

    kind: str

    def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
        """Validate the artifact and return it (or a corrected version) unchanged in id/kind."""
        ...

    def project_artifact(self, artifact: StateArtifact) -> str:
        """Return a non-empty text projection of the artifact for StateProjection."""
        ...


class StateArtifactRegistry:
    """Maps artifact kind strings to their StateArtifactAdapter implementations."""

    def __init__(self):
        """Initialize the instance."""
        self._adapters: dict[str, StateArtifactAdapter] = {}

    def register(self, adapter: StateArtifactAdapter) -> None:
        """Register an adapter for its kind, raising ValueError if the kind is already registered."""
        kind = adapter.kind
        if not kind.strip():
            raise ValueError("adapter kind must be a non-empty string")
        if kind in self._adapters:
            raise ValueError(f"adapter kind already registered: {kind}")
        self._adapters[kind] = adapter

    def resolve(self, kind: str) -> StateArtifactAdapter:
        """Return the adapter for the given kind, raising ValueError if not registered."""
        adapter = self._adapters.get(kind)
        if adapter is None:
            raise ValueError(f"unknown artifact kind: {kind}")
        return adapter


class DocumentArtifactAdapter:
    """Adapter for document-kind artifacts; passes through validation and returns a simple projection."""

    kind = "document"

    def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
        """Return the artifact unchanged (document artifacts self-validate via Pydantic)."""
        return artifact

    def project_artifact(self, artifact: StateArtifact) -> str:
        """Return a one-line text label for the document artifact."""
        return f"document artifact: {artifact.id}"


class CodingArtifactAdapter:
    """Adapter for coding-kind artifacts; passes through validation and returns a simple projection."""

    kind = "coding"

    def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
        """Return the artifact unchanged (coding artifacts self-validate via Pydantic)."""
        return artifact

    def project_artifact(self, artifact: StateArtifact) -> str:
        """Return a one-line text label for the coding artifact."""
        return f"coding artifact: {artifact.id}"


def build_default_state_artifact_registry() -> StateArtifactRegistry:
    """Create and return a registry pre-loaded with the document and coding adapters."""
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())
    registry.register(CodingArtifactAdapter())
    return registry
