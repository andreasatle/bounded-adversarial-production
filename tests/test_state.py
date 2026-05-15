import pytest
from pydantic import ValidationError

from baps.state import (
    apply_state_update,
    DocumentArtifactAdapter,
    find_state_artifact,
    GitRepositoryArtifactAdapter,
    NorthStar,
    State,
    StateArtifact,
    StateArtifactRegistry,
    StateUpdateProposal,
    StateUpdateTarget,
    validate_state_artifacts,
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


def test_state_update_target_accepts_valid_values() -> None:
    target = StateUpdateTarget(artifact_id="artifact-1", section="intro")
    assert target.artifact_id == "artifact-1"
    assert target.section == "intro"


@pytest.mark.parametrize("bad_artifact_id", ["", "   ", "\n\t"])
def test_state_update_target_rejects_empty_artifact_id(bad_artifact_id: str) -> None:
    with pytest.raises(ValidationError):
        StateUpdateTarget(artifact_id=bad_artifact_id)


@pytest.mark.parametrize("bad_section", ["", "   ", "\n\t"])
def test_state_update_target_rejects_empty_section_when_provided(bad_section: str) -> None:
    with pytest.raises(ValidationError):
        StateUpdateTarget(artifact_id="artifact-1", section=bad_section)


def test_state_update_proposal_accepts_valid_values() -> None:
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="artifact-1", section="intro"),
        summary="Update introduction wording.",
        payload={"key": "value"},
    )
    assert proposal.id == "proposal-1"
    assert proposal.target.artifact_id == "artifact-1"
    assert proposal.summary == "Update introduction wording."
    assert proposal.payload == {"key": "value"}


@pytest.mark.parametrize("bad_id", ["", "   ", "\n\t"])
def test_state_update_proposal_rejects_empty_id(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        StateUpdateProposal(
            id=bad_id,
            target=StateUpdateTarget(artifact_id="artifact-1"),
            summary="Valid summary",
        )


@pytest.mark.parametrize("bad_summary", ["", "   ", "\n\t"])
def test_state_update_proposal_rejects_empty_summary(bad_summary: str) -> None:
    with pytest.raises(ValidationError):
        StateUpdateProposal(
            id="proposal-1",
            target=StateUpdateTarget(artifact_id="artifact-1"),
            summary=bad_summary,
        )


def test_state_update_proposal_payload_default_is_isolated_per_instance() -> None:
    first = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="artifact-1"),
        summary="First summary",
    )
    second = StateUpdateProposal(
        id="proposal-2",
        target=StateUpdateTarget(artifact_id="artifact-2"),
        summary="Second summary",
    )

    first.payload["mutated"] = "yes"
    assert first.payload == {"mutated": "yes"}
    assert second.payload == {}


def test_find_state_artifact_finds_northstar_artifact() -> None:
    state = State(
        northstar=NorthStar(
            artifacts=(
                StateArtifact(id="northstar-1", kind="document"),
                StateArtifact(id="northstar-2", kind="git_repository"),
            )
        ),
        artifacts=(StateArtifact(id="state-1", kind="document"),),
    )
    artifact = find_state_artifact(state, "northstar-2")
    assert artifact.id == "northstar-2"
    assert artifact.kind == "git_repository"


def test_find_state_artifact_finds_ordinary_state_artifact() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="northstar-1", kind="document"),)),
        artifacts=(StateArtifact(id="state-1", kind="git_repository"),),
    )
    artifact = find_state_artifact(state, "state-1")
    assert artifact.id == "state-1"
    assert artifact.kind == "git_repository"


@pytest.mark.parametrize("bad_artifact_id", ["", "   ", "\n\t"])
def test_find_state_artifact_rejects_empty_or_whitespace_artifact_id(
    bad_artifact_id: str,
) -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="northstar-1", kind="document"),)),
    )
    with pytest.raises(ValueError, match="non-empty string"):
        find_state_artifact(state, bad_artifact_id)


def test_find_state_artifact_raises_for_missing_artifact_id() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="northstar-1", kind="document"),)),
        artifacts=(StateArtifact(id="state-1", kind="git_repository"),),
    )
    with pytest.raises(ValueError, match="artifact id not found in state"):
        find_state_artifact(state, "missing")


def test_apply_state_update_raises_value_error_for_missing_target_artifact() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="northstar-1", kind="document"),)),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="missing"),
        summary="Attempt update on unknown artifact.",
    )
    with pytest.raises(ValueError, match="artifact id not found in state"):
        apply_state_update(state, proposal)


def test_apply_state_update_raises_not_implemented_for_northstar_target() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="northstar-1", kind="document"),)),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="northstar-1"),
        summary="Attempt update on known northstar artifact.",
    )
    with pytest.raises(NotImplementedError, match="not implemented yet"):
        apply_state_update(state, proposal)


def test_apply_state_update_raises_not_implemented_for_ordinary_target() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="northstar-1", kind="document"),)),
        artifacts=(StateArtifact(id="state-1", kind="git_repository"),),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="state-1"),
        summary="Attempt update on known ordinary state artifact.",
    )
    with pytest.raises(NotImplementedError, match="not implemented yet"):
        apply_state_update(state, proposal)


def test_apply_state_update_does_not_mutate_input_state() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="northstar-1", kind="document"),)),
        artifacts=(StateArtifact(id="state-1", kind="git_repository"),),
    )
    before = state.model_dump(mode="json")
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="state-1"),
        summary="No-op because implementation is pending.",
    )

    with pytest.raises(NotImplementedError):
        apply_state_update(state, proposal)

    after = state.model_dump(mode="json")
    assert after == before


def test_validate_state_artifacts_validates_all_northstar_artifacts() -> None:
    calls: list[str] = []

    class DocumentTrackingAdapter:
        kind = "document"

        def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
            calls.append(artifact.id)
            return artifact

    class GitTrackingAdapter:
        kind = "git_repository"

        def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
            calls.append(artifact.id)
            return artifact

    state = State(
        northstar=NorthStar(
            artifacts=(
                StateArtifact(id="n-doc", kind="document"),
                StateArtifact(id="n-git", kind="git_repository"),
            )
        ),
    )
    registry = StateArtifactRegistry()
    registry.register(DocumentTrackingAdapter())
    registry.register(GitTrackingAdapter())

    _ = validate_state_artifacts(state, registry)
    assert calls == ["n-doc", "n-git"]


def test_validate_state_artifacts_validates_all_ordinary_artifacts() -> None:
    calls: list[str] = []

    class DocumentTrackingAdapter:
        kind = "document"

        def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
            calls.append(artifact.id)
            return artifact

    class GitTrackingAdapter:
        kind = "git_repository"

        def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
            calls.append(artifact.id)
            return artifact

    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="northstar", kind="document"),)),
        artifacts=(
            StateArtifact(id="s-doc", kind="document"),
            StateArtifact(id="s-git", kind="git_repository"),
        ),
    )
    registry = StateArtifactRegistry()
    registry.register(DocumentTrackingAdapter())
    registry.register(GitTrackingAdapter())

    _ = validate_state_artifacts(state, registry)
    assert calls == ["northstar", "s-doc", "s-git"]


def test_validate_state_artifacts_preserves_ordering() -> None:
    state = State(
        northstar=NorthStar(
            artifacts=(
                StateArtifact(id="n1", kind="document"),
                StateArtifact(id="n2", kind="git_repository"),
            )
        ),
        artifacts=(
            StateArtifact(id="s1", kind="document"),
            StateArtifact(id="s2", kind="git_repository"),
        ),
    )
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())
    registry.register(GitRepositoryArtifactAdapter())

    validated = validate_state_artifacts(state, registry)
    assert [artifact.id for artifact in validated.northstar.artifacts] == ["n1", "n2"]
    assert [artifact.id for artifact in validated.artifacts] == ["s1", "s2"]


def test_validate_state_artifacts_preserves_northstar_ordinary_separation() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
        artifacts=(StateArtifact(id="s1", kind="git_repository"),),
    )
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())
    registry.register(GitRepositoryArtifactAdapter())

    validated = validate_state_artifacts(state, registry)
    assert [artifact.id for artifact in validated.northstar.artifacts] == ["n1"]
    assert [artifact.id for artifact in validated.artifacts] == ["s1"]


def test_validate_state_artifacts_raises_for_unknown_northstar_artifact_kind() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="unknown"),)),
    )
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())

    with pytest.raises(ValueError, match="unknown artifact kind"):
        validate_state_artifacts(state, registry)


def test_validate_state_artifacts_raises_for_unknown_ordinary_artifact_kind() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
        artifacts=(StateArtifact(id="s1", kind="unknown"),),
    )
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())

    with pytest.raises(ValueError, match="unknown artifact kind"):
        validate_state_artifacts(state, registry)


def test_validate_state_artifacts_raises_if_adapter_changes_id() -> None:
    class ChangingIdAdapter:
        kind = "document"

        def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
            return StateArtifact(id=f"{artifact.id}-changed", kind=artifact.kind)

    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
    )
    registry = StateArtifactRegistry()
    registry.register(ChangingIdAdapter())

    with pytest.raises(ValueError, match="must not change artifact id"):
        validate_state_artifacts(state, registry)


def test_validate_state_artifacts_raises_if_adapter_changes_kind() -> None:
    class ChangingKindAdapter:
        kind = "document"

        def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
            return StateArtifact(id=artifact.id, kind="git_repository")

    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
    )
    registry = StateArtifactRegistry()
    registry.register(ChangingKindAdapter())

    with pytest.raises(ValueError, match="must not change artifact kind"):
        validate_state_artifacts(state, registry)


def test_validate_state_artifacts_does_not_mutate_input_state() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
        artifacts=(StateArtifact(id="s1", kind="git_repository"),),
    )
    before = state.model_dump(mode="json")
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())
    registry.register(GitRepositoryArtifactAdapter())

    _ = validate_state_artifacts(state, registry)

    after = state.model_dump(mode="json")
    assert after == before
