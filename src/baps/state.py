from __future__ import annotations

import hashlib
import json
from typing import Literal, Protocol

from pydantic import BaseModel, Field, SerializeAsAny, model_validator, field_validator


def _require_non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("must be a non-empty string")
    return value


def _coerce_state_artifact(value: object) -> StateArtifact:
    if isinstance(value, DocumentArtifact):
        return value
    if isinstance(value, CodingArtifact):
        return value
    if isinstance(value, StateArtifact):
        return value
    if isinstance(value, dict):
        if "sections" in value:
            return DocumentArtifact.model_validate(value)
        if "files" in value:
            return CodingArtifact.model_validate(value)
        return StateArtifact.model_validate(value)
    raise TypeError("artifact entries must be StateArtifact-compatible values")


class StateArtifact(BaseModel):
    id: str
    kind: str

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_kind = field_validator("kind")(_require_non_empty)


class Section(BaseModel):
    title: str
    body: str

    _validate_title = field_validator("title")(_require_non_empty)
    _validate_body = field_validator("body")(_require_non_empty)


class DocumentArtifact(StateArtifact):
    kind: Literal["document"] = "document"
    sections: tuple[Section, ...] = ()


class CodeFile(BaseModel):
    path: str
    content: str

    _validate_path = field_validator("path")(_require_non_empty)


class CodingArtifact(StateArtifact):
    kind: Literal["coding"] = "coding"
    files: tuple[CodeFile, ...] = ()


class AppendSectionDelta(BaseModel):
    section: Section


class WriteFileDelta(BaseModel):
    file: CodeFile


class DeltaState(BaseModel):
    artifact_id: str

    _validate_artifact_id = field_validator("artifact_id")(_require_non_empty)


class DeltaDocumentState(DeltaState):
    operation: Literal["append_section"]
    payload: AppendSectionDelta


class DeltaCodingState(DeltaState):
    operation: Literal["write_file"]
    payload: WriteFileDelta


class GameSpec(BaseModel):
    objective: str
    target_artifact_id: str
    allowed_delta_type: str
    success_condition: str

    _validate_objective = field_validator("objective")(_require_non_empty)
    _validate_target_artifact_id = field_validator("target_artifact_id")(_require_non_empty)
    _validate_allowed_delta_type = field_validator("allowed_delta_type")(_require_non_empty)
    _validate_success_condition = field_validator("success_condition")(_require_non_empty)


class RedFinding(BaseModel):
    disposition: Literal["accept", "revise", "reject"]
    rationale: str

    _validate_rationale = field_validator("rationale")(_require_non_empty)


class RefereeDecision(BaseModel):
    disposition: Literal["accept", "revise", "reject"]
    rationale: str

    _validate_rationale = field_validator("rationale")(_require_non_empty)


class PlayGameRuntime(BaseModel):
    current_best_delta: SerializeAsAny[DeltaState] | None = None


def apply_referee_decision_to_runtime(
    runtime: PlayGameRuntime,
    candidate_delta: DeltaState,
    decision: RefereeDecision,
) -> PlayGameRuntime:
    if decision.disposition == "accept":
        return PlayGameRuntime(current_best_delta=candidate_delta.model_copy(deep=True))
    if decision.disposition == "revise":
        return PlayGameRuntime(
            current_best_delta=(
                runtime.current_best_delta.model_copy(deep=True)
                if runtime.current_best_delta is not None
                else None
            )
        )
    if decision.disposition == "reject":
        return PlayGameRuntime(
            current_best_delta=(
                runtime.current_best_delta.model_copy(deep=True)
                if runtime.current_best_delta is not None
                else None
            )
        )
    raise ValueError(f"unsupported referee disposition: {decision.disposition}")


class NorthStar(BaseModel):
    artifacts: tuple[SerializeAsAny[StateArtifact], ...]

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
    northstar: NorthStar
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

    @model_validator(mode="after")
    def _validate_northstar_and_state_artifact_disjointness(self) -> "State":
        northstar_ids = {artifact.id for artifact in self.northstar.artifacts}
        state_ids = {artifact.id for artifact in self.artifacts}
        overlap = northstar_ids.intersection(state_ids)
        if overlap:
            raise ValueError(
                "northstar and state artifacts must not share ids; "
                f"overlap: {sorted(overlap)}"
            )
        return self


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
    payload: dict[str, object] = Field(default_factory=dict)
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
    northstar: tuple[str, ...] = ()
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
    for artifact in state.northstar.artifacts:
        if artifact.id == resolved_artifact_id:
            return artifact
    for artifact in state.artifacts:
        if artifact.id == resolved_artifact_id:
            return artifact
    raise ValueError(f"artifact id not found in state: {resolved_artifact_id}")


def apply_state_update(state: State, proposal: StateUpdateProposal) -> State:
    operation = proposal.payload.get("operation")
    if operation == "write_file":
        target_artifact_id = proposal.target.artifact_id
        existing = find_state_artifact(state, target_artifact_id)
        if not isinstance(existing, CodingArtifact):
            raise ValueError("write_file operation requires a CodingArtifact target")
        if "file" not in proposal.payload:
            raise ValueError("write_file operation requires payload['file']")
        incoming_file = CodeFile.model_validate(proposal.payload["file"])

        replaced = False
        updated_files: list[CodeFile] = []
        for existing_file in existing.files:
            if existing_file.path == incoming_file.path:
                updated_files.append(incoming_file)
                replaced = True
            else:
                updated_files.append(existing_file)
        if not replaced:
            updated_files.append(incoming_file)

        replacement = CodingArtifact(
            id=existing.id,
            files=tuple(updated_files),
        )

        northstar_replaced = False
        new_northstar_artifacts: list[StateArtifact] = []
        for artifact in state.northstar.artifacts:
            if artifact.id == target_artifact_id:
                new_northstar_artifacts.append(replacement)
                northstar_replaced = True
            else:
                new_northstar_artifacts.append(artifact)

        if northstar_replaced:
            return State(
                northstar=NorthStar(artifacts=tuple(new_northstar_artifacts)),
                artifacts=state.artifacts,
            )

        new_state_artifacts: list[StateArtifact] = []
        for artifact in state.artifacts:
            if artifact.id == target_artifact_id:
                new_state_artifacts.append(replacement)
            else:
                new_state_artifacts.append(artifact)

        return State(
            northstar=state.northstar,
            artifacts=tuple(new_state_artifacts),
        )

    if operation == "append_section":
        target_artifact_id = proposal.target.artifact_id
        existing = find_state_artifact(state, target_artifact_id)
        if not isinstance(existing, DocumentArtifact):
            raise ValueError("append_section operation requires a DocumentArtifact target")
        if "section" not in proposal.payload:
            raise ValueError("append_section operation requires payload['section']")
        appended_section = Section.model_validate(proposal.payload["section"])
        replacement = DocumentArtifact(
            id=existing.id,
            sections=(*existing.sections, appended_section),
        )

        northstar_replaced = False
        new_northstar_artifacts: list[StateArtifact] = []
        for artifact in state.northstar.artifacts:
            if artifact.id == target_artifact_id:
                new_northstar_artifacts.append(replacement)
                northstar_replaced = True
            else:
                new_northstar_artifacts.append(artifact)

        if northstar_replaced:
            return State(
                northstar=NorthStar(artifacts=tuple(new_northstar_artifacts)),
                artifacts=state.artifacts,
            )

        new_state_artifacts: list[StateArtifact] = []
        for artifact in state.artifacts:
            if artifact.id == target_artifact_id:
                new_state_artifacts.append(replacement)
            else:
                new_state_artifacts.append(artifact)

        return State(
            northstar=state.northstar,
            artifacts=tuple(new_state_artifacts),
        )

    if operation == "add_artifact":
        if "artifact" not in proposal.payload:
            raise ValueError("add_artifact operation requires payload['artifact']")
        artifact_payload = proposal.payload["artifact"]
        if isinstance(artifact_payload, dict) and "sections" in artifact_payload:
            added_artifact = DocumentArtifact.model_validate(artifact_payload)
        elif isinstance(artifact_payload, dict) and "files" in artifact_payload:
            added_artifact = CodingArtifact.model_validate(artifact_payload)
        else:
            added_artifact = StateArtifact.model_validate(artifact_payload)
        return State(
            northstar=state.northstar,
            artifacts=(*state.artifacts, added_artifact),
        )

    target_artifact_id = proposal.target.artifact_id
    existing = find_state_artifact(state, target_artifact_id)

    if operation != "replace_artifact":
        raise NotImplementedError(
            "unsupported state update operation: "
            f"{operation!r}; supported: 'replace_artifact', 'add_artifact', 'append_section', 'write_file'"
        )

    if "artifact" not in proposal.payload:
        raise ValueError("replace_artifact operation requires payload['artifact']")
    replacement = _coerce_state_artifact(proposal.payload["artifact"])

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

    northstar_replaced = False
    new_northstar_artifacts: list[StateArtifact] = []
    for artifact in state.northstar.artifacts:
        if artifact.id == target_artifact_id:
            new_northstar_artifacts.append(replacement)
            northstar_replaced = True
        else:
            new_northstar_artifacts.append(artifact)

    if northstar_replaced:
        return State(
            northstar=NorthStar(artifacts=tuple(new_northstar_artifacts)),
            artifacts=state.artifacts,
        )

    new_state_artifacts: list[StateArtifact] = []
    for artifact in state.artifacts:
        if artifact.id == target_artifact_id:
            new_state_artifacts.append(replacement)
        else:
            new_state_artifacts.append(artifact)

    return State(
        northstar=state.northstar,
        artifacts=tuple(new_state_artifacts),
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

    validated_northstar_artifacts = tuple(
        _validate_one(artifact) for artifact in state.northstar.artifacts
    )
    validated_state_artifacts = tuple(_validate_one(artifact) for artifact in state.artifacts)

    return State(
        northstar=NorthStar(artifacts=validated_northstar_artifacts),
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

    projected_northstar = tuple(_project_one(artifact) for artifact in state.northstar.artifacts)
    projected_artifacts = tuple(_project_one(artifact) for artifact in state.artifacts)
    return StateProjection(northstar=projected_northstar, artifacts=projected_artifacts)


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
