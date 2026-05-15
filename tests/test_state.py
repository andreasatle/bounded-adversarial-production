import pytest
from pydantic import ValidationError

from baps.state import (
    DocumentArtifactAdapter,
    GitRepositoryArtifactAdapter,
    NorthStar,
    State,
    StateArtifact,
    StateArtifactRegistry,
)


def test_state_artifact_accepts_valid_id_and_kind() -> None:
    artifact = StateArtifact(id="artifact-1", kind="document")
    assert artifact.id == "artifact-1"
    assert artifact.kind == "document"


@pytest.mark.parametrize("bad_id", ["", "   ", "\n\t"])
def test_state_artifact_rejects_empty_or_whitespace_id(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        StateArtifact(id=bad_id, kind="document")


@pytest.mark.parametrize("bad_kind", ["", "   ", "\n\t"])
def test_state_artifact_rejects_empty_or_whitespace_kind(bad_kind: str) -> None:
    with pytest.raises(ValidationError):
        StateArtifact(id="artifact-1", kind=bad_kind)


def test_northstar_contains_state_artifact_instances() -> None:
    northstar = NorthStar(
        artifacts=(
            StateArtifact(id="a1", kind="document"),
            StateArtifact(id="a2", kind="git_repository"),
        )
    )
    assert isinstance(northstar.artifacts[0], StateArtifact)
    assert isinstance(northstar.artifacts[1], StateArtifact)


def test_northstar_is_not_instance_or_subclass_of_state_artifact() -> None:
    northstar = NorthStar(artifacts=(StateArtifact(id="a1", kind="document"),))
    assert not isinstance(northstar, StateArtifact)
    assert not issubclass(NorthStar, StateArtifact)


def test_state_requires_northstar() -> None:
    with pytest.raises(ValidationError):
        State.model_validate({})


def test_state_artifacts_defaults_to_empty_tuple() -> None:
    state = State(northstar=NorthStar(artifacts=(StateArtifact(id="a1", kind="document"),)))
    assert state.artifacts == ()


def test_state_artifacts_accepts_state_artifact_instances() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
        artifacts=(
            StateArtifact(id="a1", kind="document"),
            StateArtifact(id="a2", kind="git_repository"),
        ),
    )
    assert len(state.artifacts) == 2
    assert all(isinstance(artifact, StateArtifact) for artifact in state.artifacts)


def test_registry_resolves_registered_adapter() -> None:
    registry = StateArtifactRegistry()
    adapter = DocumentArtifactAdapter()
    registry.register(adapter)
    assert registry.resolve("document") is adapter


def test_registry_rejects_duplicate_adapter_kind() -> None:
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(DocumentArtifactAdapter())


def test_registry_rejects_empty_adapter_kind() -> None:
    class EmptyKindAdapter:
        kind = "   "

        def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
            return artifact

    registry = StateArtifactRegistry()
    with pytest.raises(ValueError, match="non-empty string"):
        registry.register(EmptyKindAdapter())


def test_registry_raises_for_unknown_artifact_kind() -> None:
    registry = StateArtifactRegistry()
    with pytest.raises(ValueError, match="unknown artifact kind"):
        registry.resolve("unknown")


def test_document_and_git_adapters_return_artifact_unchanged() -> None:
    artifact = StateArtifact(id="a1", kind="document")
    document_adapter = DocumentArtifactAdapter()
    git_adapter = GitRepositoryArtifactAdapter()

    assert document_adapter.validate_artifact(artifact) is artifact
    assert git_adapter.validate_artifact(artifact) is artifact


def test_northstar_rejects_duplicate_artifact_ids() -> None:
    with pytest.raises(ValidationError, match="northstar artifact ids must be unique"):
        NorthStar(
            artifacts=(
                StateArtifact(id="dup", kind="document"),
                StateArtifact(id="dup", kind="git_repository"),
            )
        )


def test_state_rejects_duplicate_ordinary_artifact_ids() -> None:
    with pytest.raises(ValidationError, match="state artifact ids must be unique"):
        State(
            northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
            artifacts=(
                StateArtifact(id="dup", kind="document"),
                StateArtifact(id="dup", kind="git_repository"),
            ),
        )


def test_state_rejects_overlap_between_northstar_and_state_artifact_ids() -> None:
    with pytest.raises(
        ValidationError,
        match="northstar and state artifacts must not share ids",
    ):
        State(
            northstar=NorthStar(artifacts=(StateArtifact(id="shared", kind="document"),)),
            artifacts=(StateArtifact(id="shared", kind="git_repository"),),
        )


def test_state_accepts_distinct_northstar_and_state_artifact_ids() -> None:
    state = State(
        northstar=NorthStar(
            artifacts=(
                StateArtifact(id="northstar-1", kind="document"),
                StateArtifact(id="northstar-2", kind="git_repository"),
            )
        ),
        artifacts=(
            StateArtifact(id="state-1", kind="document"),
            StateArtifact(id="state-2", kind="git_repository"),
        ),
    )

    assert [artifact.id for artifact in state.northstar.artifacts] == [
        "northstar-1",
        "northstar-2",
    ]
    assert [artifact.id for artifact in state.artifacts] == ["state-1", "state-2"]
