from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field, model_validator, field_validator


def _require_non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("must be a non-empty string")
    return value


class StateArtifact(BaseModel):
    id: str
    kind: str

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_kind = field_validator("kind")(_require_non_empty)


class NorthStar(BaseModel):
    artifacts: tuple[StateArtifact, ...]

    @field_validator("artifacts")
    @classmethod
    def _validate_unique_artifact_ids(
        cls, artifacts: tuple[StateArtifact, ...]
    ) -> tuple[StateArtifact, ...]:
        ids = [artifact.id for artifact in artifacts]
        if len(ids) != len(set(ids)):
            raise ValueError("northstar artifact ids must be unique")
        return artifacts


class State(BaseModel):
    northstar: NorthStar
    artifacts: tuple[StateArtifact, ...] = ()

    @field_validator("artifacts")
    @classmethod
    def _validate_unique_artifact_ids(
        cls, artifacts: tuple[StateArtifact, ...]
    ) -> tuple[StateArtifact, ...]:
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
    target_artifact_id = proposal.target.artifact_id
    existing = find_state_artifact(state, target_artifact_id)

    operation = proposal.payload.get("operation")
    if operation != "replace_artifact":
        raise NotImplementedError(
            f"unsupported state update operation: {operation!r}; supported: 'replace_artifact'"
        )

    if "artifact" not in proposal.payload:
        raise ValueError("replace_artifact operation requires payload['artifact']")
    replacement = StateArtifact.model_validate(proposal.payload["artifact"])

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


def build_default_state_artifact_registry() -> StateArtifactRegistry:
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())
    registry.register(GitRepositoryArtifactAdapter())
    return registry
