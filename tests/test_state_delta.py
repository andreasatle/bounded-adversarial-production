"""Tests for delta operations, mutation path equivalence, and typed payload construction.

Integration path note
---------------------
Runtime path:     DeltaState → StateService.apply_delta  (used by orchestration._solve_gap)
Non-runtime path: DeltaState → StateUpdateProposal → StateService.apply_update
                  (used by tooling such as baps-apply-northstar and test fixtures)

apply_state_update tests and mutation path equivalence tests below exercise the
NON-RUNTIME path. The equivalence tests additionally verify that both paths produce
identical State — they do not imply both paths are valid for runtime use.
"""
import pytest
from pydantic import ValidationError

from baps.state.state import (
    apply_state_delta,
    apply_state_update,
    AppendSectionDelta,
    AppendSectionPayload,
    CodeFile,
    CodingArtifact,
    DeleteFilePayload,
    DeleteSectionPayload,
    DeltaCodingBatchState,
    DeltaCodingState,
    DeltaDeleteCodingState,
    DeltaDeleteDocumentState,
    DeltaDocumentState,
    DeltaModifyDocumentState,
    DeleteFileDelta,
    DeleteSectionDelta,
    DocumentArtifact,
    ModifySectionDelta,
    ModifySectionPayload,
    NoFindingPayload,
    Section,
    State,
    StateUpdateProposal,
    StateUpdateTarget,
    WriteFileDelta,
    WriteFilePayload,
    WriteFilesDelta,
    WriteFilesPayload,
)


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
        artifacts=(DocumentArtifact(id="doc", sections=()),),
    )
    proposal = StateUpdateProposal(
        id="u1",
        target=StateUpdateTarget(artifact_id="doc"),
        summary="bad",
        payload={"operation": "write_files", "files": [{"path": "a.py", "content": "x"}]},
    )
    with pytest.raises(ValueError, match="does not support delta type"):
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
    with pytest.raises(ValueError, match="does not support delta type"):
        apply_state_update(state, proposal)


# --- delete_section ---

def test_apply_state_update_delete_section_removes_matching_section() -> None:
    state = State(
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
        artifacts=(CodingArtifact(id="code", files=()),),
    )
    proposal = StateUpdateProposal(
        id="u1",
        target=StateUpdateTarget(artifact_id="code"),
        summary="bad",
        payload={"operation": "delete_section", "section_title": "Intro"},
    )
    with pytest.raises(ValueError, match="does not support delta type"):
        apply_state_update(state, proposal)


# --- delete_file ---

def test_apply_state_update_delete_file_removes_matching_file() -> None:
    state = State(
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
        artifacts=(DocumentArtifact(id="doc", sections=()),),
    )
    proposal = StateUpdateProposal(
        id="u1",
        target=StateUpdateTarget(artifact_id="doc"),
        summary="bad",
        payload={"operation": "delete_file", "path": "a.py"},
    )
    with pytest.raises(ValueError, match="does not support delta type"):
        apply_state_update(state, proposal)


# ---------------------------------------------------------------------------
# Equivalence: apply_state_update and apply_state_delta produce identical State
#
# NON-RUNTIME PATH. These tests confirm that the proposal path (apply_state_update)
# and the runtime path (apply_state_delta) produce the same State for the
# operations they share. Only apply_state_delta is called in production;
# apply_state_update is reserved for tooling and tests.
# ---------------------------------------------------------------------------

def test_mutation_path_equivalence_append_section() -> None:
    state = State(artifacts=(DocumentArtifact(id="doc", sections=(Section(title="A", body="a"),)),))
    new_section = Section(title="B", body="b")
    via_update = apply_state_update(state, StateUpdateProposal(
        id="u1", target=StateUpdateTarget(artifact_id="doc"), summary="s",
        payload={"operation": "append_section", "section": {"title": "B", "body": "b"}},
    ))
    via_delta = apply_state_delta(state, DeltaDocumentState(
        artifact_id="doc", operation="append_section",
        payload=AppendSectionDelta(section=new_section),
    ))
    assert via_update == via_delta


def test_mutation_path_equivalence_modify_section() -> None:
    state = State(artifacts=(DocumentArtifact(id="doc", sections=(
        Section(title="Intro", body="old"), Section(title="End", body="end"),
    )),))
    via_update = apply_state_update(state, StateUpdateProposal(
        id="u1", target=StateUpdateTarget(artifact_id="doc"), summary="s",
        payload={"operation": "modify_section", "section_title": "Intro", "new_body": "new"},
    ))
    via_delta = apply_state_delta(state, DeltaModifyDocumentState(
        artifact_id="doc", operation="modify_section",
        payload=ModifySectionDelta(section_title="Intro", new_body="new"),
    ))
    assert via_update == via_delta


def test_mutation_path_equivalence_delete_section() -> None:
    state = State(artifacts=(DocumentArtifact(id="doc", sections=(
        Section(title="A", body="a"), Section(title="B", body="b"),
    )),))
    via_update = apply_state_update(state, StateUpdateProposal(
        id="u1", target=StateUpdateTarget(artifact_id="doc"), summary="s",
        payload={"operation": "delete_section", "section_title": "A"},
    ))
    via_delta = apply_state_delta(state, DeltaDeleteDocumentState(
        artifact_id="doc", operation="delete_section",
        payload=DeleteSectionDelta(section_title="A"),
    ))
    assert via_update == via_delta


def test_mutation_path_equivalence_write_file() -> None:
    state = State(artifacts=(CodingArtifact(id="code", files=(
        CodeFile(path="a.py", content="a"), CodeFile(path="b.py", content="b"),
    )),))
    via_update = apply_state_update(state, StateUpdateProposal(
        id="u1", target=StateUpdateTarget(artifact_id="code"), summary="s",
        payload={"operation": "write_file", "file": {"path": "b.py", "content": "new-b"}},
    ))
    via_delta = apply_state_delta(state, DeltaCodingState(
        artifact_id="code", operation="write_file",
        payload=WriteFileDelta(file=CodeFile(path="b.py", content="new-b")),
    ))
    assert via_update == via_delta


def test_mutation_path_equivalence_write_files() -> None:
    state = State(artifacts=(CodingArtifact(id="code", files=(
        CodeFile(path="a.py", content="a"),
    )),))
    via_update = apply_state_update(state, StateUpdateProposal(
        id="u1", target=StateUpdateTarget(artifact_id="code"), summary="s",
        payload={"operation": "write_files", "files": [
            {"path": "a.py", "content": "new-a"},
            {"path": "b.py", "content": "b"},
        ]},
    ))
    via_delta = apply_state_delta(state, DeltaCodingBatchState(
        artifact_id="code", operation="write_files",
        payload=WriteFilesDelta(files=(
            CodeFile(path="a.py", content="new-a"),
            CodeFile(path="b.py", content="b"),
        )),
    ))
    assert via_update == via_delta


def test_mutation_path_equivalence_delete_file() -> None:
    state = State(artifacts=(CodingArtifact(id="code", files=(
        CodeFile(path="a.py", content="a"), CodeFile(path="b.py", content="b"),
    )),))
    via_update = apply_state_update(state, StateUpdateProposal(
        id="u1", target=StateUpdateTarget(artifact_id="code"), summary="s",
        payload={"operation": "delete_file", "path": "a.py"},
    ))
    via_delta = apply_state_delta(state, DeltaDeleteCodingState(
        artifact_id="code", operation="delete_file",
        payload=DeleteFileDelta(path="a.py"),
    ))
    assert via_update == via_delta


# ---------------------------------------------------------------------------
# Typed payload construction and invalid-payload rejection
# ---------------------------------------------------------------------------

def test_state_update_proposal_accepts_write_file_payload() -> None:
    p = StateUpdateProposal(
        id="u1", target=StateUpdateTarget(artifact_id="code"), summary="s",
        payload=WriteFilePayload(file=CodeFile(path="a.py", content="x")),
    )
    assert isinstance(p.payload, WriteFilePayload)
    assert p.payload.operation == "write_file"
    assert p.payload.file.path == "a.py"


def test_state_update_proposal_accepts_write_files_payload() -> None:
    p = StateUpdateProposal(
        id="u1", target=StateUpdateTarget(artifact_id="code"), summary="s",
        payload=WriteFilesPayload(files=(CodeFile(path="a.py", content="x"),)),
    )
    assert isinstance(p.payload, WriteFilesPayload)
    assert p.payload.operation == "write_files"


def test_state_update_proposal_accepts_append_section_payload() -> None:
    p = StateUpdateProposal(
        id="u1", target=StateUpdateTarget(artifact_id="doc"), summary="s",
        payload=AppendSectionPayload(section=Section(title="T", body="B")),
    )
    assert isinstance(p.payload, AppendSectionPayload)
    assert p.payload.operation == "append_section"


def test_state_update_proposal_accepts_modify_section_payload() -> None:
    p = StateUpdateProposal(
        id="u1", target=StateUpdateTarget(artifact_id="doc"), summary="s",
        payload=ModifySectionPayload(section_title="T", new_body="B"),
    )
    assert isinstance(p.payload, ModifySectionPayload)
    assert p.payload.operation == "modify_section"


def test_state_update_proposal_accepts_delete_section_payload() -> None:
    p = StateUpdateProposal(
        id="u1", target=StateUpdateTarget(artifact_id="doc"), summary="s",
        payload=DeleteSectionPayload(section_title="T"),
    )
    assert isinstance(p.payload, DeleteSectionPayload)
    assert p.payload.operation == "delete_section"


def test_state_update_proposal_accepts_delete_file_payload() -> None:
    p = StateUpdateProposal(
        id="u1", target=StateUpdateTarget(artifact_id="code"), summary="s",
        payload=DeleteFilePayload(path="a.py"),
    )
    assert isinstance(p.payload, DeleteFilePayload)
    assert p.payload.operation == "delete_file"


def test_state_update_proposal_accepts_no_finding_payload() -> None:
    p = StateUpdateProposal(
        id="u1", target=StateUpdateTarget(artifact_id="doc"), summary="s",
        payload=NoFindingPayload(file="src/foo.py", rationale="No issues found."),
    )
    assert isinstance(p.payload, NoFindingPayload)
    assert p.payload.operation == "no_finding"


def test_state_update_proposal_rejects_write_file_without_file() -> None:
    with pytest.raises(ValidationError):
        StateUpdateProposal(
            id="u1", target=StateUpdateTarget(artifact_id="code"), summary="s",
            payload={"operation": "write_file"},
        )


def test_state_update_proposal_rejects_write_files_with_empty_files() -> None:
    with pytest.raises(ValidationError):
        StateUpdateProposal(
            id="u1", target=StateUpdateTarget(artifact_id="code"), summary="s",
            payload={"operation": "write_files", "files": []},
        )


def test_state_update_proposal_rejects_append_section_without_section() -> None:
    with pytest.raises(ValidationError):
        StateUpdateProposal(
            id="u1", target=StateUpdateTarget(artifact_id="doc"), summary="s",
            payload={"operation": "append_section"},
        )


def test_state_update_proposal_rejects_modify_section_without_required_fields() -> None:
    with pytest.raises(ValidationError):
        StateUpdateProposal(
            id="u1", target=StateUpdateTarget(artifact_id="doc"), summary="s",
            payload={"operation": "modify_section"},
        )


def test_state_update_proposal_rejects_delete_section_without_section_title() -> None:
    with pytest.raises(ValidationError):
        StateUpdateProposal(
            id="u1", target=StateUpdateTarget(artifact_id="doc"), summary="s",
            payload={"operation": "delete_section"},
        )


def test_state_update_proposal_rejects_delete_file_without_path() -> None:
    with pytest.raises(ValidationError):
        StateUpdateProposal(
            id="u1", target=StateUpdateTarget(artifact_id="code"), summary="s",
            payload={"operation": "delete_file"},
        )


def test_state_update_proposal_rejects_no_finding_without_required_fields() -> None:
    with pytest.raises(ValidationError):
        StateUpdateProposal(
            id="u1", target=StateUpdateTarget(artifact_id="doc"), summary="s",
            payload={"operation": "no_finding"},
        )


def test_state_update_proposal_rejects_extra_fields_in_payload() -> None:
    with pytest.raises(ValidationError):
        StateUpdateProposal(
            id="u1", target=StateUpdateTarget(artifact_id="code"), summary="s",
            payload={
                "operation": "write_file",
                "file": {"path": "a.py", "content": "x"},
                "extra": "forbidden",
            },
        )


def test_apply_state_update_no_finding_appends_section() -> None:
    state = State(artifacts=(DocumentArtifact(id="doc", sections=()),))
    proposal = StateUpdateProposal(
        id="u1", target=StateUpdateTarget(artifact_id="doc"), summary="s",
        payload=NoFindingPayload(file="src/foo.py", rationale="Checked carefully, no issues."),
    )
    updated = apply_state_update(state, proposal)
    artifact = next(a for a in updated.artifacts if a.id == "doc")
    assert isinstance(artifact, DocumentArtifact)
    assert len(artifact.sections) == 1
    assert artifact.sections[0].title == "Audited: src/foo.py"
    assert artifact.sections[0].body == "Checked carefully, no issues."


def test_payload_coerced_from_dict_via_discriminator() -> None:
    p = StateUpdateProposal(
        id="u1", target=StateUpdateTarget(artifact_id="code"), summary="s",
        payload={"operation": "write_file", "file": {"path": "a.py", "content": "x"}},
    )
    assert isinstance(p.payload, WriteFilePayload)
