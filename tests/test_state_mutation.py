"""Tests for state mutation, registry, fingerprint, validation, and projection."""
import pytest
from pydantic import ValidationError

from baps.state.state import (
    apply_state_update,
    build_default_state_artifact_registry,
    CodeFile,
    CodingArtifact,
    DocumentArtifact,
    DocumentArtifactAdapter,
    find_state_artifact,
    fingerprint_state,
    GitRepositoryArtifactAdapter,
    NorthStar,
    Section,
    State,
    StateArtifact,
    StateArtifactRegistry,
    StateProjection,
    StateUpdateProposal,
    StateUpdateTarget,
    ReplaceArtifactPayload,
    project_state,
    validate_update_base_state,
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


def test_validate_update_base_state_without_fingerprint_returns_true() -> None:
    state = State(
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="ns-1"),
        summary="Summary",
        payload=ReplaceArtifactPayload(artifact={"id": "ns-1", "kind": "document"}),
    )

    assert validate_update_base_state(state, proposal) is True


def test_validate_update_base_state_with_matching_fingerprint_returns_true() -> None:
    state = State(
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="ns-1"),
        summary="Summary",
        payload=ReplaceArtifactPayload(artifact={"id": "ns-1", "kind": "document"}),
        base_state_fingerprint=fingerprint_state(state),
    )

    assert validate_update_base_state(state, proposal) is True


def test_validate_update_base_state_with_non_matching_fingerprint_returns_false() -> None:
    state = State(
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="ns-1"),
        summary="Summary",
        payload=ReplaceArtifactPayload(artifact={"id": "ns-1", "kind": "document"}),
        base_state_fingerprint="not-a-matching-fingerprint",
    )

    assert validate_update_base_state(state, proposal) is False


def test_validate_update_base_state_does_not_mutate_inputs() -> None:
    state = State(
        artifacts=(StateArtifact(id="artifact-1", kind="git_repository"),),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="artifact-1"),
        summary="Summary",
        base_state_fingerprint=fingerprint_state(state),
        payload=ReplaceArtifactPayload(artifact={"id": "artifact-1", "kind": "git_repository"}),
    )
    state_before = state.model_dump(mode="json")
    proposal_before = proposal.model_dump(mode="json")

    _ = validate_update_base_state(state, proposal)

    assert state.model_dump(mode="json") == state_before
    assert proposal.model_dump(mode="json") == proposal_before


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


def test_apply_state_update_raises_value_error_for_missing_target_artifact() -> None:
    state = State(
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="missing"),
        summary="Attempt update on unknown artifact.",
        payload=ReplaceArtifactPayload(artifact={"id": "missing", "kind": "document"}),
    )
    with pytest.raises(ValueError, match="artifact id not found in state"):
        apply_state_update(state, proposal)


def test_apply_state_update_replace_artifact_updates_target_artifact() -> None:
    state = State(
        artifacts=(
            StateArtifact(id="artifact-1", kind="document"),
            StateArtifact(id="artifact-2", kind="git_repository"),
        ),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="artifact-1"),
        summary="Replace known artifact.",
        payload={
            "operation": "replace_artifact",
            "artifact": {"id": "artifact-1", "kind": "document"},
        },
    )
    updated = apply_state_update(state, proposal)
    assert [artifact.id for artifact in updated.artifacts] == [
        "artifact-1",
        "artifact-2",
    ]


def test_apply_state_update_replace_artifact_updates_ordinary_artifact() -> None:
    state = State(
        artifacts=(
            StateArtifact(id="state-1", kind="git_repository"),
            StateArtifact(id="state-2", kind="document"),
        ),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="state-1"),
        summary="Replace known ordinary state artifact.",
        payload={
            "operation": "replace_artifact",
            "artifact": {"id": "state-1", "kind": "git_repository"},
        },
    )
    updated = apply_state_update(state, proposal)
    assert [artifact.id for artifact in updated.artifacts] == ["state-1", "state-2"]


def test_apply_state_update_add_artifact_appends_one_ordinary_artifact() -> None:
    state = State(
        artifacts=(StateArtifact(id="state-1", kind="document"),),
    )
    proposal = StateUpdateProposal(
        id="proposal-add-1",
        target=StateUpdateTarget(artifact_id="state-1"),
        summary="Add one ordinary artifact",
        payload={
            "operation": "add_artifact",
            "artifact": {"id": "state-2", "kind": "git_repository"},
        },
    )

    updated = apply_state_update(state, proposal)

    assert [artifact.id for artifact in updated.artifacts] == ["state-1", "state-2"]


def test_apply_state_update_add_artifact_rejects_duplicate_ordinary_artifact_id() -> None:
    state = State(
        artifacts=(StateArtifact(id="state-1", kind="document"),),
    )
    proposal = StateUpdateProposal(
        id="proposal-add-dup",
        target=StateUpdateTarget(artifact_id="state-1"),
        summary="Attempt duplicate ordinary id",
        payload={
            "operation": "add_artifact",
            "artifact": {"id": "state-1", "kind": "git_repository"},
        },
    )

    with pytest.raises(ValidationError, match="state artifact ids must be unique"):
        apply_state_update(state, proposal)


def test_apply_state_update_replace_artifact_remains_pure_replace() -> None:
    state = State(
        artifacts=(
            StateArtifact(id="state-1", kind="document"),
            StateArtifact(id="state-2", kind="git_repository"),
        ),
    )
    proposal = StateUpdateProposal(
        id="proposal-replace-pure",
        target=StateUpdateTarget(artifact_id="state-1"),
        summary="Replace only target artifact",
        payload={
            "operation": "replace_artifact",
            "artifact": {"id": "state-1", "kind": "document"},
        },
    )

    updated = apply_state_update(state, proposal)

    assert len(updated.artifacts) == 2
    assert [artifact.id for artifact in updated.artifacts] == ["state-1", "state-2"]


def test_apply_state_update_replacement_preserves_ordering() -> None:
    state = State(
        artifacts=(
            StateArtifact(id="s1", kind="document"),
            StateArtifact(id="s2", kind="git_repository"),
            StateArtifact(id="s3", kind="document"),
        ),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="s2"),
        summary="Replace middle artifact.",
        payload={
            "operation": "replace_artifact",
            "artifact": {"id": "s2", "kind": "git_repository"},
        },
    )
    updated = apply_state_update(state, proposal)
    assert [artifact.id for artifact in updated.artifacts] == ["s1", "s2", "s3"]


def test_apply_state_update_replacement_rejects_different_id() -> None:
    state = State(
        artifacts=(StateArtifact(id="n1", kind="document"),),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="n1"),
        summary="Bad replacement id.",
        payload={
            "operation": "replace_artifact",
            "artifact": {"id": "different", "kind": "document"},
        },
    )
    with pytest.raises(ValueError, match="id must match proposal.target.artifact_id"):
        apply_state_update(state, proposal)


def test_apply_state_update_replacement_rejects_different_kind() -> None:
    state = State(
        artifacts=(StateArtifact(id="n1", kind="document"),),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="n1"),
        summary="Bad replacement kind.",
        payload={
            "operation": "replace_artifact",
            "artifact": {"id": "n1", "kind": "git_repository"},
        },
    )
    with pytest.raises(ValueError, match="kind must match existing artifact kind"):
        apply_state_update(state, proposal)


def test_apply_state_update_replace_artifact_preserves_document_artifact_type() -> None:
    state = State(
        artifacts=(
            DocumentArtifact(
                id="doc-1",
                sections=(Section(title="Intro", body="Body text."),),
            ),
        ),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="doc-1"),
        summary="Replace document artifact with updated sections.",
        payload={
            "operation": "replace_artifact",
            "artifact": {
                "id": "doc-1",
                "kind": "document",
                "sections": [{"title": "Revised", "body": "New body."}],
            },
        },
    )

    updated = apply_state_update(state, proposal)

    replaced = updated.artifacts[0]
    assert isinstance(replaced, DocumentArtifact)
    assert len(replaced.sections) == 1
    assert replaced.sections[0].title == "Revised"
    assert replaced.sections[0].body == "New body."


def test_apply_state_update_replace_artifact_preserves_coding_artifact_type() -> None:
    state = State(
        artifacts=(
            CodingArtifact(
                id="code-1",
                files=(CodeFile(path="src/main.py", content="print('hello')"),),
            ),
        ),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="code-1"),
        summary="Replace coding artifact with updated files.",
        payload={
            "operation": "replace_artifact",
            "artifact": {
                "id": "code-1",
                "kind": "coding",
                "files": [{"path": "src/main.py", "content": "print('world')"}],
            },
        },
    )

    updated = apply_state_update(state, proposal)

    replaced = updated.artifacts[0]
    assert isinstance(replaced, CodingArtifact)
    assert len(replaced.files) == 1
    assert replaced.files[0].path == "src/main.py"
    assert replaced.files[0].content == "print('world')"


def test_state_update_proposal_rejects_unknown_operation_at_construction() -> None:
    with pytest.raises(ValidationError):
        StateUpdateProposal(
            id="proposal-1",
            target=StateUpdateTarget(artifact_id="n1"),
            summary="Unsupported operation.",
            payload={"operation": "unsupported_operation"},
        )


def test_state_update_proposal_rejects_missing_operation_at_construction() -> None:
    with pytest.raises(ValidationError):
        StateUpdateProposal(
            id="proposal-1",
            target=StateUpdateTarget(artifact_id="n1"),
            summary="Missing operation.",
            payload={},
        )


def test_state_update_proposal_rejects_replace_artifact_without_artifact_at_construction() -> None:
    with pytest.raises(ValidationError):
        StateUpdateProposal(
            id="proposal-1",
            target=StateUpdateTarget(artifact_id="n1"),
            summary="Missing artifact payload field.",
            payload={"operation": "replace_artifact"},
        )


def test_apply_state_update_does_not_mutate_input_state() -> None:
    state = State(
        artifacts=(StateArtifact(id="state-1", kind="git_repository"),),
    )
    before = state.model_dump(mode="json")
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="state-1"),
        summary="Replace with same-shape artifact.",
        payload={
            "operation": "replace_artifact",
            "artifact": {"id": "state-1", "kind": "git_repository"},
        },
    )
    _ = apply_state_update(state, proposal)

    after = state.model_dump(mode="json")
    assert after == before


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
