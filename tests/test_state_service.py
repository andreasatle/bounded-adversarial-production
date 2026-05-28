from __future__ import annotations

from dataclasses import dataclass

import pytest

from baps.state.state import (
    fingerprint_state,
    State,
    StateArtifact,
    StateArtifactRegistry,
    StateUpdateProposal,
    StateUpdateTarget,
)
from baps.state.state_service import StateService


@dataclass
class InMemoryStateStore:
    state: State

    def __post_init__(self) -> None:
        self.load_calls = 0
        self.save_calls = 0
        self.last_saved: State | None = None

    def load(self) -> State:
        self.load_calls += 1
        return self.state

    def save(self, state: State) -> None:
        self.save_calls += 1
        self.state = state
        self.last_saved = state


def _state() -> State:
    return State(
        artifacts=(
            StateArtifact(id="artifact-1", kind="document"),
            StateArtifact(id="artifact-2", kind="git_repository"),
        ),
    )


def _registry_with_counting_adapters(call_log: list[str]) -> StateArtifactRegistry:
    class DocumentAdapter:
        kind = "document"

        def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
            call_log.append(f"validate:document:{artifact.id}")
            return artifact

        def project_artifact(self, artifact: StateArtifact) -> str:
            return f"document artifact: {artifact.id}"

    class GitAdapter:
        kind = "git_repository"

        def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
            call_log.append(f"validate:git_repository:{artifact.id}")
            return artifact

        def project_artifact(self, artifact: StateArtifact) -> str:
            return f"git repository artifact: {artifact.id}"

    registry = StateArtifactRegistry()
    registry.register(DocumentAdapter())
    registry.register(GitAdapter())
    return registry


def test_load_state_delegates_to_store_load() -> None:
    store = InMemoryStateStore(state=_state())
    registry = _registry_with_counting_adapters([])
    service = StateService(store=store, registry=registry)

    loaded = service.load_state()

    assert store.load_calls == 1
    assert loaded == store.state


def test_validate_state_loads_and_validates_artifacts_through_registry() -> None:
    calls: list[str] = []
    store = InMemoryStateStore(state=_state())
    registry = _registry_with_counting_adapters(calls)
    service = StateService(store=store, registry=registry)

    validated = service.validate_state()

    assert store.load_calls == 1
    assert len(calls) == 2
    assert validated == store.state


# ---------------------------------------------------------------------------
# apply_update — NON-RUNTIME PATH
# These tests exercise StateService.apply_update (StateUpdateProposal envelope).
# The live orchestration path never calls apply_update; it calls apply_delta.
# apply_update is used only by tooling (baps-apply-northstar) and test fixtures.
# ---------------------------------------------------------------------------

def test_apply_update_loads_validates_applies_validates_saves_and_returns_state() -> None:
    calls: list[str] = []
    store = InMemoryStateStore(state=_state())
    registry = _registry_with_counting_adapters(calls)
    service = StateService(store=store, registry=registry)
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="artifact-1"),
        summary="Replace artifact",
        payload={
            "operation": "replace_artifact",
            "artifact": {"id": "artifact-1", "kind": "document"},
        },
    )

    updated = service.apply_update(proposal)

    assert store.load_calls == 1
    assert len(calls) == 3
    assert store.save_calls == 1
    assert store.last_saved == updated
    assert updated == store.state


def test_apply_update_does_not_save_when_proposal_construction_fails() -> None:
    from pydantic import ValidationError as PydanticValidationError
    store = InMemoryStateStore(state=_state())

    with pytest.raises(PydanticValidationError):
        StateUpdateProposal(
            id="proposal-1",
            target=StateUpdateTarget(artifact_id="artifact-1"),
            summary="Unsupported operation",
            payload={"operation": "unsupported_operation"},
        )

    assert store.load_calls == 0
    assert store.save_calls == 0


def test_service_does_not_mutate_original_loaded_state() -> None:
    original = _state()
    before = original.model_dump(mode="json")
    store = InMemoryStateStore(state=original)
    registry = _registry_with_counting_adapters([])
    service = StateService(store=store, registry=registry)
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="artifact-1"),
        summary="Replace artifact",
        payload={
            "operation": "replace_artifact",
            "artifact": {"id": "artifact-1", "kind": "document"},
        },
    )

    _ = service.apply_update(proposal)

    after = original.model_dump(mode="json")
    assert after == before


def test_apply_update_accepts_proposal_without_base_state_fingerprint() -> None:
    store = InMemoryStateStore(state=_state())
    registry = _registry_with_counting_adapters([])
    service = StateService(store=store, registry=registry)
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="artifact-1"),
        summary="Replace artifact",
        payload={
            "operation": "replace_artifact",
            "artifact": {"id": "artifact-1", "kind": "document"},
        },
    )

    updated = service.apply_update(proposal)

    assert isinstance(updated, State)
    assert store.save_calls == 1
    replaced = next(a for a in updated.artifacts if a.id == "artifact-1")
    assert replaced.kind == "document"
    sibling = next(a for a in updated.artifacts if a.id == "artifact-2")
    assert sibling.kind == "git_repository"


def test_apply_update_accepts_matching_base_state_fingerprint() -> None:
    state = _state()
    store = InMemoryStateStore(state=state)
    registry = _registry_with_counting_adapters([])
    service = StateService(store=store, registry=registry)
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="artifact-1"),
        summary="Replace artifact",
        payload={
            "operation": "replace_artifact",
            "artifact": {"id": "artifact-1", "kind": "document"},
        },
        base_state_fingerprint=fingerprint_state(state),
    )

    updated = service.apply_update(proposal)

    assert isinstance(updated, State)
    assert store.save_calls == 1
    replaced = next(a for a in updated.artifacts if a.id == "artifact-1")
    assert replaced.kind == "document"
    sibling = next(a for a in updated.artifacts if a.id == "artifact-2")
    assert sibling.kind == "git_repository"


def test_apply_update_rejects_non_matching_base_state_fingerprint() -> None:
    store = InMemoryStateStore(state=_state())
    registry = _registry_with_counting_adapters([])
    service = StateService(store=store, registry=registry)
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="artifact-1"),
        summary="Replace artifact",
        payload={
            "operation": "replace_artifact",
            "artifact": {"id": "artifact-1", "kind": "document"},
        },
        base_state_fingerprint="not-the-current-fingerprint",
    )

    with pytest.raises(ValueError, match="base_state_fingerprint"):
        service.apply_update(proposal)


def test_apply_update_fingerprint_rejection_does_not_save_updated_state() -> None:
    store = InMemoryStateStore(state=_state())
    registry = _registry_with_counting_adapters([])
    service = StateService(store=store, registry=registry)
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="artifact-1"),
        summary="Replace artifact",
        payload={
            "operation": "replace_artifact",
            "artifact": {"id": "artifact-1", "kind": "document"},
        },
        base_state_fingerprint="not-the-current-fingerprint",
    )

    with pytest.raises(ValueError, match="base_state_fingerprint"):
        service.apply_update(proposal)

    assert store.save_calls == 0
