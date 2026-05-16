from __future__ import annotations

from pydantic import BaseModel, field_validator

from baps.northstar_projection import (
    NorthStarProjectionInput,
    NorthStarProjectionItem,
    NorthStarView,
    ProjectionPolicy,
    render_northstar_view,
)


def _require_non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("must be a non-empty string")
    return value


class ProjectIntake(BaseModel):
    id: str
    northstar: str
    project_context: str | None = None
    user_note: str | None = None

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_northstar = field_validator("northstar")(_require_non_empty)


def intake_to_northstar_view(intake: ProjectIntake) -> NorthStarView:
    projection_input = NorthStarProjectionInput(
        project_state=(
            NorthStarProjectionItem(
                id=f"intake:{intake.id}:northstar",
                content=intake.northstar,
                source="project_intake.northstar",
                authority="project",
                status="provided",
                projection_policy=ProjectionPolicy.VERBATIM,
            ),
        ),
    )
    return render_northstar_view(projection_input)
