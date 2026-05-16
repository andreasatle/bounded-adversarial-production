import pytest
from pydantic import ValidationError

from baps.project_intake import ProjectIntake, intake_to_northstar_view


@pytest.mark.parametrize("bad_id", ["", "   ", "\n\t"])
def test_project_intake_rejects_empty_id(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        ProjectIntake(id=bad_id, northstar="Valid northstar")


@pytest.mark.parametrize("bad_northstar", ["", "   ", "\n\t"])
def test_project_intake_rejects_empty_northstar(bad_northstar: str) -> None:
    with pytest.raises(ValidationError):
        ProjectIntake(id="intake-1", northstar=bad_northstar)


def test_project_intake_optional_fields_are_optional() -> None:
    intake = ProjectIntake(id="intake-1", northstar="Valid northstar")
    assert intake.project_context is None
    assert intake.user_note is None


def test_intake_to_northstar_view_preserves_northstar_text_verbatim() -> None:
    northstar_text = "Line 1\nLine 2 with  spacing"
    intake = ProjectIntake(id="intake-1", northstar=northstar_text)

    view = intake_to_northstar_view(intake)

    assert f"1. {northstar_text}" in view.content


def test_generated_northstar_view_is_deterministic_for_identical_intake() -> None:
    intake = ProjectIntake(
        id="intake-1",
        northstar="Stable northstar text",
        project_context="Context",
        user_note="Note",
    )

    first = intake_to_northstar_view(intake)
    second = intake_to_northstar_view(intake)

    assert first.model_dump_json() == second.model_dump_json()


def test_user_facing_intake_does_not_require_internal_structures() -> None:
    intake = ProjectIntake(
        id="intake-1",
        northstar="Northstar only",
    )

    view = intake_to_northstar_view(intake)

    assert view is not None
    assert "project_intake.northstar" in view.content
