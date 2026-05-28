"""Tests for state mutation, registry, fingerprint, validation, and projection."""
import pytest

from baps.state.state import (
    build_default_state_artifact_registry,
    DocumentArtifactAdapter,
    find_state_artifact,
    fingerprint_state,
    GitRepositoryArtifactAdapter,
    State,
    StateArtifact,
    StateArtifactRegistry,
    StateProjection,
    project_state,
    validate_state_artifacts,
)


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

        def project_artifact(self, artifact: StateArtifact) -> str:
            return f"artifact: {artifact.id}"

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


def test_document_and_git_adapters_return_deterministic_projection_strings() -> None:
    artifact = StateArtifact(id="a1", kind="document")
    document_adapter = DocumentArtifactAdapter()
    git_adapter = GitRepositoryArtifactAdapter()

    assert document_adapter.project_artifact(artifact) == "document artifact: a1"
    assert git_adapter.project_artifact(artifact) == "git repository artifact: a1"


def test_fingerprint_state_is_deterministic_for_repeated_calls() -> None:
    state = State(
        artifacts=(
            StateArtifact(id="state-1", kind="document"),
            StateArtifact(id="state-2", kind="git_repository"),
        ),
    )

    first = fingerprint_state(state)
    second = fingerprint_state(state)

    assert first == second


def test_fingerprint_state_changes_when_artifact_order_changes() -> None:
    first_state = State(
        artifacts=(
            StateArtifact(id="state-1", kind="document"),
            StateArtifact(id="state-2", kind="git_repository"),
        ),
    )
    second_state = State(
        artifacts=(
            StateArtifact(id="state-2", kind="git_repository"),
            StateArtifact(id="state-1", kind="document"),
        ),
    )

    assert fingerprint_state(first_state) != fingerprint_state(second_state)


def test_fingerprint_state_changes_when_artifact_id_changes() -> None:
    first_state = State(
        artifacts=(StateArtifact(id="state-1", kind="document"),),
    )
    second_state = State(
        artifacts=(StateArtifact(id="state-2", kind="document"),),
    )

    assert fingerprint_state(first_state) != fingerprint_state(second_state)


def test_fingerprint_state_changes_when_artifact_kind_changes() -> None:
    first_state = State(
        artifacts=(StateArtifact(id="state-1", kind="document"),),
    )
    second_state = State(
        artifacts=(StateArtifact(id="state-1", kind="git_repository"),),
    )

    assert fingerprint_state(first_state) != fingerprint_state(second_state)


def test_find_state_artifact_finds_artifact_by_id() -> None:
    state = State(
        artifacts=(
            StateArtifact(id="artifact-1", kind="document"),
            StateArtifact(id="artifact-2", kind="git_repository"),
        ),
    )
    artifact = find_state_artifact(state, "artifact-2")
    assert artifact.id == "artifact-2"
    assert artifact.kind == "git_repository"


def test_find_state_artifact_finds_ordinary_state_artifact() -> None:
    state = State(
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
    )
    with pytest.raises(ValueError, match="non-empty string"):
        find_state_artifact(state, bad_artifact_id)


def test_find_state_artifact_raises_for_missing_artifact_id() -> None:
    state = State(
        artifacts=(StateArtifact(id="state-1", kind="git_repository"),),
    )
    with pytest.raises(ValueError, match="artifact id not found in state"):
        find_state_artifact(state, "missing")


def test_build_default_registry_resolves_document_adapter() -> None:
    registry = build_default_state_artifact_registry()
    adapter = registry.resolve("document")
    assert isinstance(adapter, DocumentArtifactAdapter)


def test_build_default_registry_resolves_git_repository_adapter() -> None:
    registry = build_default_state_artifact_registry()
    adapter = registry.resolve("git_repository")
    assert isinstance(adapter, GitRepositoryArtifactAdapter)


def test_build_default_registry_adapters_validate_artifacts_unchanged() -> None:
    registry = build_default_state_artifact_registry()
    document_artifact = StateArtifact(id="doc-1", kind="document")
    git_artifact = StateArtifact(id="repo-1", kind="git_repository")

    assert registry.resolve("document").validate_artifact(document_artifact) is document_artifact
    assert registry.resolve("git_repository").validate_artifact(git_artifact) is git_artifact


def test_build_default_registry_adapters_project_deterministic_strings() -> None:
    registry = build_default_state_artifact_registry()
    document_artifact = StateArtifact(id="doc-1", kind="document")
    git_artifact = StateArtifact(id="repo-1", kind="git_repository")

    assert (
        registry.resolve("document").project_artifact(document_artifact)
        == "document artifact: doc-1"
    )
    assert (
        registry.resolve("git_repository").project_artifact(git_artifact)
        == "git repository artifact: repo-1"
    )


def test_build_default_registry_returns_independent_instances() -> None:
    first = build_default_state_artifact_registry()
    second = build_default_state_artifact_registry()
    assert first is not second


def test_modifying_one_default_registry_does_not_affect_another() -> None:
    class CustomAdapter:
        kind = "custom"

        def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
            return artifact

        def project_artifact(self, artifact: StateArtifact) -> str:
            return f"custom artifact: {artifact.id}"

    first = build_default_state_artifact_registry()
    second = build_default_state_artifact_registry()
    first.register(CustomAdapter())

    assert first.resolve("custom").project_artifact(StateArtifact(id="x", kind="custom")) == "custom artifact: x"
    with pytest.raises(ValueError, match="unknown artifact kind"):
        second.resolve("custom")


def test_validate_state_artifacts_validates_all_state_artifacts() -> None:
    calls: list[str] = []

    class DocumentTrackingAdapter:
        kind = "document"

        def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
            calls.append(artifact.id)
            return artifact

        def project_artifact(self, artifact: StateArtifact) -> str:
            return f"doc:{artifact.id}"

    class GitTrackingAdapter:
        kind = "git_repository"

        def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
            calls.append(artifact.id)
            return artifact

        def project_artifact(self, artifact: StateArtifact) -> str:
            return f"git:{artifact.id}"

    state = State(
        artifacts=(
            StateArtifact(id="n-doc", kind="document"),
            StateArtifact(id="n-git", kind="git_repository"),
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

        def project_artifact(self, artifact: StateArtifact) -> str:
            return f"doc:{artifact.id}"

    class GitTrackingAdapter:
        kind = "git_repository"

        def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
            calls.append(artifact.id)
            return artifact

        def project_artifact(self, artifact: StateArtifact) -> str:
            return f"git:{artifact.id}"

    state = State(
        artifacts=(
            StateArtifact(id="s-doc", kind="document"),
            StateArtifact(id="s-git", kind="git_repository"),
        ),
    )
    registry = StateArtifactRegistry()
    registry.register(DocumentTrackingAdapter())
    registry.register(GitTrackingAdapter())

    _ = validate_state_artifacts(state, registry)
    assert calls == ["s-doc", "s-git"]


def test_validate_state_artifacts_preserves_ordering() -> None:
    state = State(
        artifacts=(
            StateArtifact(id="s1", kind="document"),
            StateArtifact(id="s2", kind="git_repository"),
        ),
    )
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())
    registry.register(GitRepositoryArtifactAdapter())

    validated = validate_state_artifacts(state, registry)
    assert [artifact.id for artifact in validated.artifacts] == ["s1", "s2"]


def test_validate_state_artifacts_raises_for_unknown_artifact_kind() -> None:
    state = State(
        artifacts=(StateArtifact(id="s1", kind="unknown"),),
    )
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())

    with pytest.raises(ValueError, match="unknown artifact kind"):
        validate_state_artifacts(state, registry)


def test_validate_state_artifacts_raises_for_unknown_ordinary_artifact_kind() -> None:
    state = State(
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

        def project_artifact(self, artifact: StateArtifact) -> str:
            return f"doc:{artifact.id}"

    state = State(
        artifacts=(StateArtifact(id="n1", kind="document"),),
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

        def project_artifact(self, artifact: StateArtifact) -> str:
            return f"doc:{artifact.id}"

    state = State(
        artifacts=(StateArtifact(id="n1", kind="document"),),
    )
    registry = StateArtifactRegistry()
    registry.register(ChangingKindAdapter())

    with pytest.raises(ValueError, match="must not change artifact kind"):
        validate_state_artifacts(state, registry)


def test_validate_state_artifacts_does_not_mutate_input_state() -> None:
    state = State(
        artifacts=(StateArtifact(id="s1", kind="git_repository"),),
    )
    before = state.model_dump(mode="json")
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())
    registry.register(GitRepositoryArtifactAdapter())

    _ = validate_state_artifacts(state, registry)

    after = state.model_dump(mode="json")
    assert after == before


def test_state_projection_defaults_to_empty_tuples() -> None:
    projection = StateProjection()
    assert projection.artifacts == ()


def test_project_state_projects_artifacts_through_adapters() -> None:
    state = State(
        artifacts=(
            StateArtifact(id="n1", kind="document"),
            StateArtifact(id="n2", kind="git_repository"),
        ),
    )
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())
    registry.register(GitRepositoryArtifactAdapter())

    projection = project_state(state, registry)
    assert projection.artifacts == (
        "document artifact: n1",
        "git repository artifact: n2",
    )


def test_project_state_projects_ordinary_artifacts_through_adapters() -> None:
    state = State(
        artifacts=(
            StateArtifact(id="s1", kind="document"),
            StateArtifact(id="s2", kind="git_repository"),
        ),
    )
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())
    registry.register(GitRepositoryArtifactAdapter())

    projection = project_state(state, registry)
    assert projection.artifacts == (
        "document artifact: s1",
        "git repository artifact: s2",
    )


def test_project_state_preserves_ordering() -> None:
    state = State(
        artifacts=(
            StateArtifact(id="s1", kind="git_repository"),
            StateArtifact(id="s2", kind="document"),
        ),
    )
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())
    registry.register(GitRepositoryArtifactAdapter())

    projection = project_state(state, registry)
    assert projection.artifacts == (
        "git repository artifact: s1",
        "document artifact: s2",
    )


def test_project_state_raises_for_unknown_artifact_kind() -> None:
    state = State(
        artifacts=(StateArtifact(id="s1", kind="unknown"),),
    )
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())

    with pytest.raises(ValueError, match="unknown artifact kind"):
        project_state(state, registry)


def test_project_state_raises_if_adapter_projection_is_empty_or_whitespace() -> None:
    class EmptyProjectionAdapter:
        kind = "document"

        def validate_artifact(self, artifact: StateArtifact) -> StateArtifact:
            return artifact

        def project_artifact(self, artifact: StateArtifact) -> str:
            return "   "

    state = State(
        artifacts=(StateArtifact(id="n1", kind="document"),),
    )
    registry = StateArtifactRegistry()
    registry.register(EmptyProjectionAdapter())

    with pytest.raises(ValueError, match="projection must be a non-empty string"):
        project_state(state, registry)


def test_project_state_does_not_mutate_input_state() -> None:
    state = State(
        artifacts=(StateArtifact(id="s1", kind="git_repository"),),
    )
    before = state.model_dump(mode="json")
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())
    registry.register(GitRepositoryArtifactAdapter())

    _ = project_state(state, registry)

    after = state.model_dump(mode="json")
    assert after == before
