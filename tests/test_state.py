import pytest
from pydantic import ValidationError

from baps.state import (
    apply_state_update,
    apply_referee_decision_to_runtime,
    AppendSectionDelta,
    build_default_state_artifact_registry,
    CodeFile,
    CodingArtifact,
    DeltaCodingBatchState,
    DeltaDeleteCodingState,
    DeltaDeleteDocumentState,
    DeltaModifyDocumentState,
    DeltaState,
    DeltaDocumentState,
    DeleteFileDelta,
    DeleteSectionDelta,
    DocumentArtifact,
    DocumentArtifactAdapter,
    find_state_artifact,
    fingerprint_state,
    GameSpec,
    ModifySectionDelta,
    PlayGameRuntime,
    RedFinding,
    RefereeDecision,
    GitRepositoryArtifactAdapter,
    NorthStar,
    Section,
    State,
    StateArtifact,
    StateArtifactRegistry,
    StateProjection,
    StateUpdateProposal,
    StateUpdateTarget,
    WriteFilesDelta,
    project_state,
    validate_update_base_state,
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


def test_document_artifact_accepts_main_document_with_empty_sections() -> None:
    artifact = DocumentArtifact(id="main-document", sections=())
    assert artifact.id == "main-document"
    assert artifact.kind == "document"
    assert artifact.sections == ()


def test_document_artifact_sections_accepts_section_instances() -> None:
    artifact = DocumentArtifact(
        id="main-document",
        sections=(Section(title="Intro", body="Hello"),),
    )
    assert artifact.sections[0].title == "Intro"
    assert artifact.sections[0].body == "Hello"


def test_code_file_accepts_empty_content() -> None:
    f = CodeFile(path="src/__init__.py", content="")
    assert f.path == "src/__init__.py"
    assert f.content == ""


@pytest.mark.parametrize("bad_path", ["", "   ", "\t"])
def test_code_file_rejects_empty_or_whitespace_path(bad_path: str) -> None:
    with pytest.raises(ValidationError):
        CodeFile(path=bad_path, content="")


def test_delta_document_state_append_section_constructs_valid_model() -> None:
    delta = DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=AppendSectionDelta(section=Section(title="Intro", body="Body text")),
    )
    assert delta.artifact_id == "main-document"
    assert delta.operation == "append_section"
    assert delta.payload.section.title == "Intro"


@pytest.mark.parametrize("bad_artifact_id", ["", "   ", "\n\t"])
def test_delta_document_state_rejects_empty_artifact_id(bad_artifact_id: str) -> None:
    with pytest.raises(ValidationError):
        DeltaDocumentState(
            artifact_id=bad_artifact_id,
            operation="append_section",
            payload=AppendSectionDelta(section=Section(title="Intro", body="Body text")),
        )


@pytest.mark.parametrize("bad_title", ["", "   ", "\n\t"])
def test_delta_document_state_rejects_empty_section_title(bad_title: str) -> None:
    with pytest.raises(ValidationError):
        DeltaDocumentState(
            artifact_id="main-document",
            operation="append_section",
            payload=AppendSectionDelta(section=Section(title=bad_title, body="Body text")),
        )


@pytest.mark.parametrize("bad_body", ["", "   ", "\n\t"])
def test_delta_document_state_rejects_empty_section_body(bad_body: str) -> None:
    with pytest.raises(ValidationError):
        DeltaDocumentState(
            artifact_id="main-document",
            operation="append_section",
            payload=AppendSectionDelta(section=Section(title="Intro", body=bad_body)),
        )


def test_delta_document_state_serialization_is_deterministic() -> None:
    delta = DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=AppendSectionDelta(section=Section(title="Intro", body="Body text")),
    )
    first = delta.model_dump(mode="json")
    second = delta.model_dump(mode="json")
    assert first == second


def test_delta_document_state_does_not_mutate_state() -> None:
    state = State(
        northstar=NorthStar(artifacts=()),
        artifacts=(DocumentArtifact(id="main-document", sections=()),),
    )
    before = state.model_dump(mode="json")
    _ = DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=AppendSectionDelta(section=Section(title="Intro", body="Body text")),
    )
    after = state.model_dump(mode="json")
    assert after == before


def test_delta_document_state_is_subclass_and_instance_of_delta_state() -> None:
    delta = DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=AppendSectionDelta(section=Section(title="Intro", body="Body text")),
    )
    assert isinstance(delta, DeltaState)
    assert issubclass(DeltaDocumentState, DeltaState)


def test_game_spec_accepts_valid_values() -> None:
    spec = GameSpec(
        objective="Advance report quality",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return valid DeltaDocumentState",
    )
    assert spec.target_artifact_id == "main-document"


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("objective", ""),
        ("objective", "   "),
        ("target_artifact_id", ""),
        ("target_artifact_id", "   "),
        ("allowed_delta_type", ""),
        ("allowed_delta_type", "   "),
        ("success_condition", ""),
        ("success_condition", "   "),
    ],
)
def test_game_spec_rejects_empty_required_fields(field_name: str, value: str) -> None:
    payload = {
        "objective": "Advance report quality",
        "target_artifact_id": "main-document",
        "allowed_delta_type": "DeltaDocumentState",
        "success_condition": "PlayGame must return valid DeltaDocumentState",
    }
    payload[field_name] = value
    with pytest.raises(ValidationError):
        GameSpec.model_validate(payload)


@pytest.mark.parametrize("disposition", ["accept", "revise", "reject"])
def test_red_finding_accepts_valid_dispositions(disposition: str) -> None:
    finding = RedFinding(disposition=disposition, rationale="Reason")
    assert finding.disposition == disposition


@pytest.mark.parametrize("disposition", ["accept", "revise", "reject"])
def test_referee_decision_accepts_valid_dispositions(disposition: str) -> None:
    decision = RefereeDecision(disposition=disposition, rationale="Reason")
    assert decision.disposition == disposition


@pytest.mark.parametrize("bad_rationale", ["", "   ", "\n\t"])
def test_red_finding_rejects_empty_rationale(bad_rationale: str) -> None:
    with pytest.raises(ValidationError):
        RedFinding(disposition="accept", rationale=bad_rationale)


@pytest.mark.parametrize("bad_rationale", ["", "   ", "\n\t"])
def test_referee_decision_rejects_empty_rationale(bad_rationale: str) -> None:
    with pytest.raises(ValidationError):
        RefereeDecision(disposition="accept", rationale=bad_rationale)


def test_play_game_runtime_defaults_current_best_delta_to_none() -> None:
    runtime = PlayGameRuntime()
    assert runtime.current_best_delta is None


def test_play_game_runtime_preserves_earlier_accepted_delta_when_later_candidate_rejected() -> None:
    accepted_delta = DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=AppendSectionDelta(section=Section(title="Intro", body="Body text")),
    )
    runtime = PlayGameRuntime()
    runtime = apply_referee_decision_to_runtime(
        runtime=runtime,
        candidate_delta=accepted_delta,
        decision=RefereeDecision(disposition="accept", rationale="Good candidate"),
    )

    later_candidate = DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=AppendSectionDelta(section=Section(title="Conclusion", body="Body text")),
    )
    runtime_after_reject = apply_referee_decision_to_runtime(
        runtime=runtime,
        candidate_delta=later_candidate,
        decision=RefereeDecision(disposition="reject", rationale="Reject later candidate"),
    )

    assert runtime_after_reject.current_best_delta is not None
    assert runtime_after_reject.current_best_delta.model_dump(mode="json") == accepted_delta.model_dump(
        mode="json"
    )


def test_apply_referee_decision_revise_promotes_candidate_as_best_delta() -> None:
    candidate = DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=AppendSectionDelta(section=Section(title="Draft", body="Draft body.")),
    )
    runtime = apply_referee_decision_to_runtime(
        runtime=PlayGameRuntime(),
        candidate_delta=candidate,
        decision=RefereeDecision(disposition="revise", rationale="Promising but needs work."),
    )

    assert runtime.current_best_delta is not None
    assert runtime.current_best_delta.model_dump(mode="json") == candidate.model_dump(mode="json")


def test_apply_referee_decision_reject_discards_candidate_and_keeps_none() -> None:
    candidate = DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=AppendSectionDelta(section=Section(title="Bad", body="Wrong direction.")),
    )
    runtime = apply_referee_decision_to_runtime(
        runtime=PlayGameRuntime(),
        candidate_delta=candidate,
        decision=RefereeDecision(disposition="reject", rationale="Wrong direction."),
    )

    assert runtime.current_best_delta is None


def test_apply_referee_decision_revise_then_reject_keeps_revised_candidate() -> None:
    first_candidate = DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=AppendSectionDelta(section=Section(title="First", body="First body.")),
    )
    runtime = apply_referee_decision_to_runtime(
        runtime=PlayGameRuntime(),
        candidate_delta=first_candidate,
        decision=RefereeDecision(disposition="revise", rationale="Good start."),
    )
    second_candidate = DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=AppendSectionDelta(section=Section(title="Second", body="Worse body.")),
    )
    runtime = apply_referee_decision_to_runtime(
        runtime=runtime,
        candidate_delta=second_candidate,
        decision=RefereeDecision(disposition="reject", rationale="Regression."),
    )

    assert runtime.current_best_delta is not None
    assert runtime.current_best_delta.model_dump(mode="json") == first_candidate.model_dump(mode="json")


def test_document_artifact_is_subclass_and_instance_of_state_artifact() -> None:
    artifact = DocumentArtifact(id="main-document", sections=())
    assert isinstance(artifact, StateArtifact)
    assert issubclass(DocumentArtifact, StateArtifact)


def test_state_accepts_document_artifact_in_artifacts() -> None:
    state = State(
        northstar=NorthStar(artifacts=()),
        artifacts=(DocumentArtifact(id="main-document", sections=()),),
    )
    assert len(state.artifacts) == 1
    assert state.artifacts[0].id == "main-document"


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


def test_state_rejects_duplicate_ids_with_document_artifact() -> None:
    with pytest.raises(ValidationError, match="state artifact ids must be unique"):
        State(
            northstar=NorthStar(artifacts=()),
            artifacts=(
                DocumentArtifact(id="main-document", sections=()),
                StateArtifact(id="main-document", kind="document"),
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


def test_state_update_proposal_accepts_omitted_base_state_fingerprint() -> None:
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="artifact-1"),
        summary="Summary",
    )
    assert proposal.base_state_fingerprint is None


def test_state_update_proposal_accepts_non_empty_base_state_fingerprint() -> None:
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="artifact-1"),
        summary="Summary",
        base_state_fingerprint="state-fingerprint-123",
    )
    assert proposal.base_state_fingerprint == "state-fingerprint-123"


@pytest.mark.parametrize("bad_fingerprint", ["", "   ", "\n\t"])
def test_state_update_proposal_rejects_empty_base_state_fingerprint(
    bad_fingerprint: str,
) -> None:
    with pytest.raises(ValidationError):
        StateUpdateProposal(
            id="proposal-1",
            target=StateUpdateTarget(artifact_id="artifact-1"),
            summary="Summary",
            base_state_fingerprint=bad_fingerprint,
        )


def test_fingerprint_state_is_deterministic_for_repeated_calls() -> None:
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

    first = fingerprint_state(state)
    second = fingerprint_state(state)

    assert first == second


def test_fingerprint_state_changes_when_artifact_order_changes() -> None:
    first_state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="northstar-1", kind="document"),)),
        artifacts=(
            StateArtifact(id="state-1", kind="document"),
            StateArtifact(id="state-2", kind="git_repository"),
        ),
    )
    second_state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="northstar-1", kind="document"),)),
        artifacts=(
            StateArtifact(id="state-2", kind="git_repository"),
            StateArtifact(id="state-1", kind="document"),
        ),
    )

    assert fingerprint_state(first_state) != fingerprint_state(second_state)


def test_fingerprint_state_changes_when_artifact_id_changes() -> None:
    first_state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="northstar-1", kind="document"),)),
        artifacts=(StateArtifact(id="state-1", kind="document"),),
    )
    second_state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="northstar-1", kind="document"),)),
        artifacts=(StateArtifact(id="state-2", kind="document"),),
    )

    assert fingerprint_state(first_state) != fingerprint_state(second_state)


def test_fingerprint_state_changes_when_artifact_kind_changes() -> None:
    first_state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="northstar-1", kind="document"),)),
        artifacts=(StateArtifact(id="state-1", kind="document"),),
    )
    second_state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="northstar-1", kind="document"),)),
        artifacts=(StateArtifact(id="state-1", kind="git_repository"),),
    )

    assert fingerprint_state(first_state) != fingerprint_state(second_state)


def test_fingerprint_state_changes_when_northstar_artifacts_change() -> None:
    first_state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="northstar-1", kind="document"),)),
        artifacts=(StateArtifact(id="state-1", kind="document"),),
    )
    second_state = State(
        northstar=NorthStar(
            artifacts=(
                StateArtifact(id="northstar-1", kind="document"),
                StateArtifact(id="northstar-2", kind="git_repository"),
            )
        ),
        artifacts=(StateArtifact(id="state-1", kind="document"),),
    )

    assert fingerprint_state(first_state) != fingerprint_state(second_state)


def test_validate_update_base_state_without_fingerprint_returns_true() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="ns-1", kind="document"),)),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="ns-1"),
        summary="Summary",
    )

    assert validate_update_base_state(state, proposal) is True


def test_validate_update_base_state_with_matching_fingerprint_returns_true() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="ns-1", kind="document"),)),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="ns-1"),
        summary="Summary",
        base_state_fingerprint=fingerprint_state(state),
    )

    assert validate_update_base_state(state, proposal) is True


def test_validate_update_base_state_with_non_matching_fingerprint_returns_false() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="ns-1", kind="document"),)),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="ns-1"),
        summary="Summary",
        base_state_fingerprint="not-a-matching-fingerprint",
    )

    assert validate_update_base_state(state, proposal) is False


def test_validate_update_base_state_does_not_mutate_inputs() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="ns-1", kind="document"),)),
        artifacts=(StateArtifact(id="artifact-1", kind="git_repository"),),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="ns-1"),
        summary="Summary",
        base_state_fingerprint=fingerprint_state(state),
        payload={"operation": "replace_artifact"},
    )
    state_before = state.model_dump(mode="json")
    proposal_before = proposal.model_dump(mode="json")

    _ = validate_update_base_state(state, proposal)

    assert state.model_dump(mode="json") == state_before
    assert proposal.model_dump(mode="json") == proposal_before


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


def test_apply_state_update_replace_artifact_updates_northstar_artifact() -> None:
    state = State(
        northstar=NorthStar(
            artifacts=(
                StateArtifact(id="northstar-1", kind="document"),
                StateArtifact(id="northstar-2", kind="git_repository"),
            )
        ),
        artifacts=(StateArtifact(id="state-1", kind="document"),),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="northstar-1"),
        summary="Replace known northstar artifact.",
        payload={
            "operation": "replace_artifact",
            "artifact": {"id": "northstar-1", "kind": "document"},
        },
    )
    updated = apply_state_update(state, proposal)
    assert [artifact.id for artifact in updated.northstar.artifacts] == [
        "northstar-1",
        "northstar-2",
    ]
    assert [artifact.id for artifact in updated.artifacts] == ["state-1"]


def test_apply_state_update_replace_artifact_updates_ordinary_artifact() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="northstar-1", kind="document"),)),
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
    assert [artifact.id for artifact in updated.northstar.artifacts] == ["northstar-1"]
    assert [artifact.id for artifact in updated.artifacts] == ["state-1", "state-2"]


def test_apply_state_update_add_artifact_appends_one_ordinary_artifact() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="northstar-1", kind="document"),)),
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

    assert [artifact.id for artifact in updated.northstar.artifacts] == ["northstar-1"]
    assert [artifact.id for artifact in updated.artifacts] == ["state-1", "state-2"]


def test_apply_state_update_add_artifact_rejects_duplicate_ordinary_artifact_id() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="northstar-1", kind="document"),)),
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


def test_apply_state_update_add_artifact_rejects_northstar_overlap_id() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="northstar-1", kind="document"),)),
        artifacts=(StateArtifact(id="state-1", kind="document"),),
    )
    proposal = StateUpdateProposal(
        id="proposal-add-overlap",
        target=StateUpdateTarget(artifact_id="state-1"),
        summary="Attempt northstar overlap id",
        payload={
            "operation": "add_artifact",
            "artifact": {"id": "northstar-1", "kind": "git_repository"},
        },
    )

    with pytest.raises(
        ValidationError,
        match="northstar and state artifacts must not share ids",
    ):
        apply_state_update(state, proposal)


def test_apply_state_update_replace_artifact_remains_pure_replace() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="northstar-1", kind="document"),)),
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
        northstar=NorthStar(
            artifacts=(
                StateArtifact(id="n1", kind="document"),
                StateArtifact(id="n2", kind="git_repository"),
            )
        ),
        artifacts=(
            StateArtifact(id="s1", kind="document"),
            StateArtifact(id="s2", kind="git_repository"),
            StateArtifact(id="s3", kind="document"),
        ),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="s2"),
        summary="Replace middle ordinary artifact.",
        payload={
            "operation": "replace_artifact",
            "artifact": {"id": "s2", "kind": "git_repository"},
        },
    )
    updated = apply_state_update(state, proposal)
    assert [artifact.id for artifact in updated.northstar.artifacts] == ["n1", "n2"]
    assert [artifact.id for artifact in updated.artifacts] == ["s1", "s2", "s3"]


def test_apply_state_update_replacement_preserves_northstar_ordinary_separation() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
        artifacts=(StateArtifact(id="s1", kind="git_repository"),),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="n1"),
        summary="Replace northstar artifact only.",
        payload={
            "operation": "replace_artifact",
            "artifact": {"id": "n1", "kind": "document"},
        },
    )
    updated = apply_state_update(state, proposal)
    assert [artifact.id for artifact in updated.northstar.artifacts] == ["n1"]
    assert [artifact.id for artifact in updated.artifacts] == ["s1"]


def test_apply_state_update_replacement_rejects_different_id() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
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
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
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
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
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
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
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


def test_apply_state_update_unsupported_operation_raises_not_implemented() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="n1"),
        summary="Unsupported operation.",
        payload={"operation": "unsupported_operation"},
    )
    with pytest.raises(NotImplementedError, match="unsupported state update operation"):
        apply_state_update(state, proposal)


def test_apply_state_update_missing_operation_raises_clear_error() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="n1"),
        summary="Missing operation.",
        payload={},
    )
    with pytest.raises(NotImplementedError, match="unsupported state update operation"):
        apply_state_update(state, proposal)


def test_apply_state_update_missing_artifact_raises_value_error() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
    )
    proposal = StateUpdateProposal(
        id="proposal-1",
        target=StateUpdateTarget(artifact_id="n1"),
        summary="Missing artifact payload field.",
        payload={"operation": "replace_artifact"},
    )
    with pytest.raises(ValueError, match="requires payload\\['artifact'\\]"):
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


def test_validate_state_artifacts_validates_all_northstar_artifacts() -> None:
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

        def project_artifact(self, artifact: StateArtifact) -> str:
            return f"doc:{artifact.id}"

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

        def project_artifact(self, artifact: StateArtifact) -> str:
            return f"doc:{artifact.id}"

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


def test_state_projection_defaults_to_empty_tuples() -> None:
    projection = StateProjection()
    assert projection.northstar == ()
    assert projection.artifacts == ()


def test_project_state_projects_northstar_artifacts_through_adapters() -> None:
    state = State(
        northstar=NorthStar(
            artifacts=(
                StateArtifact(id="n1", kind="document"),
                StateArtifact(id="n2", kind="git_repository"),
            )
        ),
    )
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())
    registry.register(GitRepositoryArtifactAdapter())

    projection = project_state(state, registry)
    assert projection.northstar == (
        "document artifact: n1",
        "git repository artifact: n2",
    )


def test_project_state_projects_ordinary_artifacts_through_adapters() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
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
        northstar=NorthStar(
            artifacts=(
                StateArtifact(id="n1", kind="document"),
                StateArtifact(id="n2", kind="git_repository"),
            )
        ),
        artifacts=(
            StateArtifact(id="s1", kind="git_repository"),
            StateArtifact(id="s2", kind="document"),
        ),
    )
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())
    registry.register(GitRepositoryArtifactAdapter())

    projection = project_state(state, registry)
    assert projection.northstar == (
        "document artifact: n1",
        "git repository artifact: n2",
    )
    assert projection.artifacts == (
        "git repository artifact: s1",
        "document artifact: s2",
    )


def test_project_state_preserves_northstar_ordinary_separation() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
        artifacts=(StateArtifact(id="s1", kind="git_repository"),),
    )
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())
    registry.register(GitRepositoryArtifactAdapter())

    projection = project_state(state, registry)
    assert projection.northstar == ("document artifact: n1",)
    assert projection.artifacts == ("git repository artifact: s1",)


def test_project_state_raises_for_unknown_northstar_artifact_kind() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="unknown"),)),
    )
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())

    with pytest.raises(ValueError, match="unknown artifact kind"):
        project_state(state, registry)


def test_project_state_raises_for_unknown_ordinary_artifact_kind() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
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
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
    )
    registry = StateArtifactRegistry()
    registry.register(EmptyProjectionAdapter())

    with pytest.raises(ValueError, match="projection must be a non-empty string"):
        project_state(state, registry)


def test_project_state_does_not_mutate_input_state() -> None:
    state = State(
        northstar=NorthStar(artifacts=(StateArtifact(id="n1", kind="document"),)),
        artifacts=(StateArtifact(id="s1", kind="git_repository"),),
    )
    before = state.model_dump(mode="json")
    registry = StateArtifactRegistry()
    registry.register(DocumentArtifactAdapter())
    registry.register(GitRepositoryArtifactAdapter())

    _ = project_state(state, registry)

    after = state.model_dump(mode="json")
    assert after == before


# --- write_files delta schema ---

def test_write_files_delta_requires_non_empty_files() -> None:
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        WriteFilesDelta(files=())


def test_write_files_delta_accepts_multiple_files() -> None:
    delta = WriteFilesDelta(files=(
        CodeFile(path="a.py", content="x"),
        CodeFile(path="b.py", content="y"),
    ))
    assert len(delta.files) == 2


def test_delta_coding_batch_state_validates() -> None:
    delta = DeltaCodingBatchState.model_validate({
        "artifact_id": "art",
        "operation": "write_files",
        "payload": {"files": [{"path": "a.py", "content": "x"}]},
    })
    assert delta.operation == "write_files"
    assert delta.payload.files[0].path == "a.py"


# --- apply_state_update write_files ---

def test_apply_state_update_write_files_adds_new_files() -> None:
    state = State(
        northstar=NorthStar(artifacts=()),
        artifacts=(CodingArtifact(id="code", files=(CodeFile(path="existing.py", content="old"),)),),
    )
    proposal = StateUpdateProposal(
        id="u1",
        target=StateUpdateTarget(artifact_id="code"),
        summary="write two files",
        payload={
            "operation": "write_files",
            "files": [
                {"path": "new1.py", "content": "a"},
                {"path": "new2.py", "content": "b"},
            ],
        },
    )
    updated = apply_state_update(state, proposal)
    artifact = next(a for a in updated.artifacts if a.id == "code")
    assert isinstance(artifact, CodingArtifact)
    paths = {f.path for f in artifact.files}
    assert paths == {"existing.py", "new1.py", "new2.py"}


def test_apply_state_update_write_files_overwrites_existing_file() -> None:
    state = State(
        northstar=NorthStar(artifacts=()),
        artifacts=(CodingArtifact(id="code", files=(CodeFile(path="a.py", content="old"),)),),
    )
    proposal = StateUpdateProposal(
        id="u1",
        target=StateUpdateTarget(artifact_id="code"),
        summary="overwrite",
        payload={
            "operation": "write_files",
            "files": [{"path": "a.py", "content": "new"}],
        },
    )
    updated = apply_state_update(state, proposal)
    artifact = next(a for a in updated.artifacts if a.id == "code")
    assert isinstance(artifact, CodingArtifact)
    assert artifact.files[0].content == "new"
    assert len(artifact.files) == 1


def test_apply_state_update_write_files_requires_coding_artifact() -> None:
    state = State(
        northstar=NorthStar(artifacts=()),
        artifacts=(DocumentArtifact(id="doc", sections=()),),
    )
    proposal = StateUpdateProposal(
        id="u1",
        target=StateUpdateTarget(artifact_id="doc"),
        summary="bad",
        payload={"operation": "write_files", "files": [{"path": "a.py", "content": "x"}]},
    )
    with pytest.raises(ValueError, match="CodingArtifact"):
        apply_state_update(state, proposal)


# --- modify_section delta schema ---

def test_modify_section_delta_requires_non_empty_fields() -> None:
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ModifySectionDelta(section_title="", new_body="body")
    with pytest.raises(ValidationError):
        ModifySectionDelta(section_title="Title", new_body="")


def test_delta_modify_document_state_validates() -> None:
    delta = DeltaModifyDocumentState.model_validate({
        "artifact_id": "doc",
        "operation": "modify_section",
        "payload": {"section_title": "Intro", "new_body": "new content"},
    })
    assert delta.operation == "modify_section"
    assert delta.payload.section_title == "Intro"
    assert delta.payload.new_body == "new content"


# --- apply_state_update modify_section ---

def test_apply_state_update_modify_section_replaces_body() -> None:
    state = State(
        northstar=NorthStar(artifacts=()),
        artifacts=(DocumentArtifact(
            id="doc",
            sections=(
                Section(title="Intro", body="old intro"),
                Section(title="Details", body="details text"),
            ),
        ),),
    )
    proposal = StateUpdateProposal(
        id="u1",
        target=StateUpdateTarget(artifact_id="doc"),
        summary="modify intro",
        payload={
            "operation": "modify_section",
            "section_title": "Intro",
            "new_body": "new intro",
        },
    )
    updated = apply_state_update(state, proposal)
    artifact = next(a for a in updated.artifacts if a.id == "doc")
    assert isinstance(artifact, DocumentArtifact)
    assert artifact.sections[0].body == "new intro"
    assert artifact.sections[1].body == "details text"


def test_apply_state_update_modify_section_raises_if_title_not_found() -> None:
    state = State(
        northstar=NorthStar(artifacts=()),
        artifacts=(DocumentArtifact(
            id="doc",
            sections=(Section(title="Intro", body="body"),),
        ),),
    )
    proposal = StateUpdateProposal(
        id="u1",
        target=StateUpdateTarget(artifact_id="doc"),
        summary="modify missing",
        payload={
            "operation": "modify_section",
            "section_title": "Nonexistent",
            "new_body": "x",
        },
    )
    with pytest.raises(ValueError, match="Nonexistent"):
        apply_state_update(state, proposal)


def test_apply_state_update_modify_section_requires_document_artifact() -> None:
    state = State(
        northstar=NorthStar(artifacts=()),
        artifacts=(CodingArtifact(id="code", files=()),),
    )
    proposal = StateUpdateProposal(
        id="u1",
        target=StateUpdateTarget(artifact_id="code"),
        summary="bad",
        payload={
            "operation": "modify_section",
            "section_title": "Intro",
            "new_body": "x",
        },
    )
    with pytest.raises(ValueError, match="DocumentArtifact"):
        apply_state_update(state, proposal)


# --- delete_section ---

def test_apply_state_update_delete_section_removes_matching_section() -> None:
    state = State(
        northstar=NorthStar(artifacts=()),
        artifacts=(DocumentArtifact(
            id="doc",
            sections=(
                Section(title="Intro", body="intro"),
                Section(title="Details", body="details"),
                Section(title="Conclusion", body="conclusion"),
            ),
        ),),
    )
    proposal = StateUpdateProposal(
        id="u1",
        target=StateUpdateTarget(artifact_id="doc"),
        summary="delete intro",
        payload={"operation": "delete_section", "section_title": "Details"},
    )
    updated = apply_state_update(state, proposal)
    artifact = next(a for a in updated.artifacts if a.id == "doc")
    assert isinstance(artifact, DocumentArtifact)
    titles = [s.title for s in artifact.sections]
    assert titles == ["Intro", "Conclusion"]


def test_apply_state_update_delete_section_raises_if_title_not_found() -> None:
    state = State(
        northstar=NorthStar(artifacts=()),
        artifacts=(DocumentArtifact(
            id="doc",
            sections=(Section(title="Intro", body="body"),),
        ),),
    )
    proposal = StateUpdateProposal(
        id="u1",
        target=StateUpdateTarget(artifact_id="doc"),
        summary="delete missing",
        payload={"operation": "delete_section", "section_title": "Ghost"},
    )
    with pytest.raises(ValueError, match="Ghost"):
        apply_state_update(state, proposal)


def test_apply_state_update_delete_section_requires_document_artifact() -> None:
    state = State(
        northstar=NorthStar(artifacts=()),
        artifacts=(CodingArtifact(id="code", files=()),),
    )
    proposal = StateUpdateProposal(
        id="u1",
        target=StateUpdateTarget(artifact_id="code"),
        summary="bad",
        payload={"operation": "delete_section", "section_title": "Intro"},
    )
    with pytest.raises(ValueError, match="DocumentArtifact"):
        apply_state_update(state, proposal)


# --- delete_file ---

def test_apply_state_update_delete_file_removes_matching_file() -> None:
    state = State(
        northstar=NorthStar(artifacts=()),
        artifacts=(CodingArtifact(
            id="code",
            files=(
                CodeFile(path="a.py", content="a"),
                CodeFile(path="b.py", content="b"),
                CodeFile(path="c.py", content="c"),
            ),
        ),),
    )
    proposal = StateUpdateProposal(
        id="u1",
        target=StateUpdateTarget(artifact_id="code"),
        summary="delete b",
        payload={"operation": "delete_file", "path": "b.py"},
    )
    updated = apply_state_update(state, proposal)
    artifact = next(a for a in updated.artifacts if a.id == "code")
    assert isinstance(artifact, CodingArtifact)
    paths = [f.path for f in artifact.files]
    assert paths == ["a.py", "c.py"]


def test_apply_state_update_delete_file_raises_if_path_not_found() -> None:
    state = State(
        northstar=NorthStar(artifacts=()),
        artifacts=(CodingArtifact(
            id="code",
            files=(CodeFile(path="a.py", content="a"),),
        ),),
    )
    proposal = StateUpdateProposal(
        id="u1",
        target=StateUpdateTarget(artifact_id="code"),
        summary="delete missing",
        payload={"operation": "delete_file", "path": "ghost.py"},
    )
    with pytest.raises(ValueError, match="ghost.py"):
        apply_state_update(state, proposal)


def test_apply_state_update_delete_file_requires_coding_artifact() -> None:
    state = State(
        northstar=NorthStar(artifacts=()),
        artifacts=(DocumentArtifact(id="doc", sections=()),),
    )
    proposal = StateUpdateProposal(
        id="u1",
        target=StateUpdateTarget(artifact_id="doc"),
        summary="bad",
        payload={"operation": "delete_file", "path": "a.py"},
    )
    with pytest.raises(ValueError, match="CodingArtifact"):
        apply_state_update(state, proposal)
