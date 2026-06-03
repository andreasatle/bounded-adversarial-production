"""Schema validation tests for state models."""

import pytest
from pydantic import ValidationError

from baps.state.state import (
    apply_referee_decision_to_runtime,
    AppendSectionDelta,
    CodeFile,
    DeltaDocumentState,
    DeltaState,
    DocumentArtifact,
    GameSpec,
    NorthStar,
    PlayGameRuntime,
    RedFinding,
    RefereeDecision,
    Section,
    State,
    StateArtifact,
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
            payload=AppendSectionDelta(
                section=Section(title="Intro", body="Body text")
            ),
        )


@pytest.mark.parametrize("bad_title", ["", "   ", "\n\t"])
def test_delta_document_state_rejects_empty_section_title(bad_title: str) -> None:
    with pytest.raises(ValidationError):
        DeltaDocumentState(
            artifact_id="main-document",
            operation="append_section",
            payload=AppendSectionDelta(
                section=Section(title=bad_title, body="Body text")
            ),
        )


@pytest.mark.parametrize("bad_body", ["", "   ", "\n\t"])
def test_delta_document_state_rejects_empty_section_body(bad_body: str) -> None:
    with pytest.raises(ValidationError):
        DeltaDocumentState(
            artifact_id="main-document",
            operation="append_section",
            payload=AppendSectionDelta(section=Section(title="Intro", body=bad_body)),
        )


def test_section_rejects_unicode_whitespace_only_body() -> None:
    with pytest.raises(ValidationError):
        Section(title="Intro", body=" ")  # EM SPACE passes ASCII strip but not NFKC


def test_section_rejects_unicode_whitespace_only_title() -> None:
    with pytest.raises(ValidationError):
        Section(title=" ", body="Body text")


def test_section_rejects_non_string_body() -> None:
    with pytest.raises(ValidationError):
        Section.model_validate({"title": "Intro", "body": 42})


def test_section_rejects_non_string_title() -> None:
    with pytest.raises(ValidationError):
        Section.model_validate({"title": 42, "body": "Body text"})


def test_section_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Section.model_validate({"title": "Intro", "body": "Body", "injected": "x"})


def test_section_rejects_oversized_body() -> None:
    from baps.state.state import _MAX_SECTION_BODY_BYTES

    with pytest.raises(ValidationError):
        Section(title="Intro", body="x" * (_MAX_SECTION_BODY_BYTES + 1))


def test_code_file_rejects_non_string_path() -> None:
    with pytest.raises(ValidationError):
        CodeFile.model_validate({"path": 123, "content": ""})


def test_code_file_rejects_non_string_content() -> None:
    with pytest.raises(ValidationError):
        CodeFile.model_validate({"path": "src/main.py", "content": ["lines"]})


def test_code_file_rejects_oversized_path() -> None:
    from baps.state.state import _MAX_CODEFILE_PATH_BYTES

    with pytest.raises(ValidationError):
        CodeFile(path="a" * (_MAX_CODEFILE_PATH_BYTES + 1), content="")


def test_code_file_rejects_oversized_content() -> None:
    from baps.state.state import _MAX_CODEFILE_CONTENT_BYTES

    with pytest.raises(ValidationError):
        CodeFile(path="src/main.py", content="x" * (_MAX_CODEFILE_CONTENT_BYTES + 1))


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
    assert runtime.integration_eligible_delta is None


def test_play_game_runtime_preserves_earlier_accepted_delta_when_later_candidate_rejected() -> (
    None
):
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
        payload=AppendSectionDelta(
            section=Section(title="Conclusion", body="Body text")
        ),
    )
    runtime_after_reject = apply_referee_decision_to_runtime(
        runtime=runtime,
        candidate_delta=later_candidate,
        decision=RefereeDecision(
            disposition="reject", rationale="Reject later candidate"
        ),
    )

    assert runtime_after_reject.current_best_delta is not None
    assert runtime_after_reject.current_best_delta.model_dump(
        mode="json"
    ) == accepted_delta.model_dump(mode="json")
    assert runtime_after_reject.integration_eligible_delta is not None
    assert runtime_after_reject.integration_eligible_delta.model_dump(
        mode="json"
    ) == accepted_delta.model_dump(mode="json")


def test_apply_referee_decision_revise_does_not_set_current_best_delta() -> None:
    candidate = DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=AppendSectionDelta(section=Section(title="Draft", body="Draft body.")),
    )
    runtime = apply_referee_decision_to_runtime(
        runtime=PlayGameRuntime(),
        candidate_delta=candidate,
        decision=RefereeDecision(
            disposition="revise", rationale="Promising but needs work."
        ),
    )

    assert runtime.current_best_delta is None
    assert runtime.integration_eligible_delta is None


def test_apply_referee_decision_reject_discards_candidate_and_keeps_none() -> None:
    candidate = DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=AppendSectionDelta(
            section=Section(title="Bad", body="Wrong direction.")
        ),
    )
    runtime = apply_referee_decision_to_runtime(
        runtime=PlayGameRuntime(),
        candidate_delta=candidate,
        decision=RefereeDecision(disposition="reject", rationale="Wrong direction."),
    )

    assert runtime.current_best_delta is None
    assert runtime.integration_eligible_delta is None


def test_apply_referee_decision_revise_then_reject_produces_no_accepted_candidate() -> (
    None
):
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

    assert runtime.current_best_delta is None
    assert runtime.integration_eligible_delta is None


def test_apply_referee_decision_accept_then_revise_keeps_accepted_candidate_unchanged() -> (
    None
):
    accepted_candidate = DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=AppendSectionDelta(
            section=Section(title="Accepted", body="Accepted body.")
        ),
    )
    runtime = apply_referee_decision_to_runtime(
        runtime=PlayGameRuntime(),
        candidate_delta=accepted_candidate,
        decision=RefereeDecision(disposition="accept", rationale="Approved."),
    )
    revised_candidate = DeltaDocumentState(
        artifact_id="main-document",
        operation="append_section",
        payload=AppendSectionDelta(
            section=Section(title="Revised", body="Needs work.")
        ),
    )
    runtime = apply_referee_decision_to_runtime(
        runtime=runtime,
        candidate_delta=revised_candidate,
        decision=RefereeDecision(
            disposition="revise", rationale="Promising but not ready."
        ),
    )
    assert runtime.current_best_delta is not None
    assert runtime.current_best_delta.model_dump(
        mode="json"
    ) == accepted_candidate.model_dump(mode="json")
    assert runtime.integration_eligible_delta is not None
    assert runtime.integration_eligible_delta.model_dump(
        mode="json"
    ) == accepted_candidate.model_dump(mode="json")


def test_document_artifact_is_subclass_and_instance_of_state_artifact() -> None:
    artifact = DocumentArtifact(id="main-document", sections=())
    assert isinstance(artifact, StateArtifact)
    assert issubclass(DocumentArtifact, StateArtifact)


def test_state_accepts_document_artifact_in_artifacts() -> None:
    state = State(
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


def test_state_artifacts_defaults_to_empty_tuple() -> None:
    state = State()
    assert state.artifacts == ()


def test_state_artifacts_accepts_state_artifact_instances() -> None:
    state = State(
        artifacts=(
            StateArtifact(id="a1", kind="document"),
            StateArtifact(id="a2", kind="git_repository"),
        ),
    )
    assert len(state.artifacts) == 2
    assert all(isinstance(artifact, StateArtifact) for artifact in state.artifacts)


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
            artifacts=(
                StateArtifact(id="dup", kind="document"),
                StateArtifact(id="dup", kind="git_repository"),
            ),
        )


def test_state_rejects_duplicate_ids_with_document_artifact() -> None:
    with pytest.raises(ValidationError, match="state artifact ids must be unique"):
        State(
            artifacts=(
                DocumentArtifact(id="main-document", sections=()),
                StateArtifact(id="main-document", kind="document"),
            ),
        )


def test_state_accepts_multiple_artifacts_with_distinct_ids() -> None:
    state = State(
        artifacts=(
            StateArtifact(id="state-1", kind="document"),
            StateArtifact(id="state-2", kind="git_repository"),
        ),
    )
    assert [artifact.id for artifact in state.artifacts] == ["state-1", "state-2"]
