"""Tests for delta model schemas."""

import pytest
from pydantic import ValidationError

from baps.state.state import (
    CodeFile,
    DeltaCodingBatchState,
    DeltaModifyDocumentState,
    ModifySectionDelta,
    WriteFilesDelta,
)


def test_write_files_delta_requires_non_empty_files() -> None:
    with pytest.raises(ValidationError):
        WriteFilesDelta(files=())


def test_write_files_delta_accepts_multiple_files() -> None:
    delta = WriteFilesDelta(
        files=(
            CodeFile(path="a.py", content="x"),
            CodeFile(path="b.py", content="y"),
        )
    )
    assert len(delta.files) == 2


def test_delta_coding_batch_state_validates() -> None:
    delta = DeltaCodingBatchState.model_validate(
        {
            "artifact_id": "art",
            "operation": "write_files",
            "payload": {"files": [{"path": "a.py", "content": "x"}]},
        }
    )
    assert delta.operation == "write_files"
    assert delta.payload.files[0].path == "a.py"


def test_modify_section_delta_requires_non_empty_fields() -> None:
    with pytest.raises(ValidationError):
        ModifySectionDelta(section_title="", new_body="body")
    with pytest.raises(ValidationError):
        ModifySectionDelta(section_title="Title", new_body="")


def test_delta_modify_document_state_validates() -> None:
    delta = DeltaModifyDocumentState.model_validate(
        {
            "artifact_id": "doc",
            "operation": "modify_section",
            "payload": {"section_title": "Intro", "new_body": "new content"},
        }
    )
    assert delta.operation == "modify_section"
    assert delta.payload.section_title == "Intro"
    assert delta.payload.new_body == "new content"
