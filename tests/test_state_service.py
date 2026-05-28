from __future__ import annotations

from dataclasses import dataclass

from baps.state.state import (
    State,
    StateArtifact,
    StateArtifactRegistry,
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
