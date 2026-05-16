from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _require_non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("must be a non-empty string")
    return value


class ProjectionPolicy(str, Enum):
    VERBATIM = "verbatim"
    SUMMARIZED = "summarized"
    FILTERED = "filtered"
    DIRECT = "direct"


class NorthStarProjectionItem(BaseModel):
    content: str
    source: str
    authority: str
    status: str
    projection_policy: ProjectionPolicy = ProjectionPolicy.VERBATIM

    _validate_content = field_validator("content")(_require_non_empty)
    _validate_source = field_validator("source")(_require_non_empty)
    _validate_authority = field_validator("authority")(_require_non_empty)
    _validate_status = field_validator("status")(_require_non_empty)


class NorthStarProjectionInput(BaseModel):
    framework_policy: tuple[NorthStarProjectionItem, ...] = ()
    project_state: tuple[NorthStarProjectionItem, ...] = ()
    blackboard_history: tuple[NorthStarProjectionItem, ...] = ()
    runtime_context: tuple[NorthStarProjectionItem, ...] = ()


class ProjectionType(str, Enum):
    NORTH_STAR = "north_star"


class ProjectionArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    projection_type: ProjectionType
    content: str
    input_fingerprint: str
    metadata: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_projection_type = field_validator("projection_type")(_require_non_empty)
    _validate_content = field_validator("content")(_require_non_empty)
    _validate_input_fingerprint = field_validator("input_fingerprint")(_require_non_empty)


class ProjectionRenderer(Protocol):
    def render(self, input_data: NorthStarProjectionInput) -> ProjectionArtifact:
        ...


def _render_section(title: str, items: tuple[NorthStarProjectionItem, ...]) -> str:
    lines = [f"## {title}"]
    if not items:
        lines.append("_No items._")
        return "\n".join(lines)

    for index, item in enumerate(items, start=1):
        if item.projection_policy is not ProjectionPolicy.VERBATIM:
            raise ValueError(
                "unsupported projection policy for renderer: "
                f"{item.projection_policy.value}; only 'verbatim' is supported"
            )
        lines.append(f"{index}. {item.content}")
        lines.append(f"   - source: {item.source}")
        lines.append(f"   - authority: {item.authority}")
        lines.append(f"   - status: {item.status}")
    return "\n".join(lines)


def render_northstar_projection(input_data: NorthStarProjectionInput) -> str:
    sections = (
        _render_section("Framework Policy", input_data.framework_policy),
        _render_section("Project State", input_data.project_state),
        _render_section("Blackboard History", input_data.blackboard_history),
        _render_section("Runtime Context", input_data.runtime_context),
    )
    return "\n\n".join(sections)


def fingerprint_northstar_projection_input(input_data: NorthStarProjectionInput) -> str:
    canonical = json.dumps(
        input_data.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class NorthStarProjectionRenderer:
    def render(self, input_data: NorthStarProjectionInput) -> ProjectionArtifact:
        content = render_northstar_projection(input_data)
        input_fingerprint = fingerprint_northstar_projection_input(input_data)
        return ProjectionArtifact(
            id=f"projection:northstar:{input_fingerprint}",
            projection_type=ProjectionType.NORTH_STAR,
            content=content,
            input_fingerprint=input_fingerprint,
        )


def render_northstar_projection_artifact(
    input_data: NorthStarProjectionInput,
) -> ProjectionArtifact:
    return NorthStarProjectionRenderer().render(input_data)
