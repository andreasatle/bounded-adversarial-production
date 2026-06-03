"""Renders NorthStarProjectionInput into fingerprinted StateView projections for model consumption."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _require_non_empty(value: str) -> str:
    """Raise ValueError if value is blank; used as a Pydantic field validator."""
    if not value.strip():
        raise ValueError("must be a non-empty string")
    return value


class ProjectionPolicy(StrEnum):
    """Governs how a NorthStarProjectionItem's content is rendered into the StateView."""

    VERBATIM = "verbatim"
    SUMMARIZED = "summarized"
    FILTERED = "filtered"
    DIRECT = "direct"


class NorthStarProjectionItem(BaseModel):
    """A single projection item with provenance metadata and a rendering policy."""

    id: str
    content: str
    source: str
    authority: str
    status: str
    projection_policy: ProjectionPolicy = ProjectionPolicy.VERBATIM

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_content = field_validator("content")(_require_non_empty)
    _validate_source = field_validator("source")(_require_non_empty)
    _validate_authority = field_validator("authority")(_require_non_empty)
    _validate_status = field_validator("status")(_require_non_empty)


class NorthStarProjectionInput(BaseModel):
    """Structured input for the NorthStar projection renderer, grouping items by section."""

    framework_policy: tuple[NorthStarProjectionItem, ...] = ()
    project_state: tuple[NorthStarProjectionItem, ...] = ()
    blackboard_history: tuple[NorthStarProjectionItem, ...] = ()
    runtime_context: tuple[NorthStarProjectionItem, ...] = ()


STATE_VIEW_START = "=== StateView Start ==="
STATE_VIEW_END = "=== StateView End ==="


class ProjectionType(StrEnum):
    """Identifies the lifecycle stage for which a StateView was constructed."""

    NORTH_STAR = "north_star"
    CREATE_GAME = "create_game"
    PLAY_GAME = "play_game"


class StateView(BaseModel):
    """Immutable model-facing projection of state: framed content, fingerprint, and metadata."""

    model_config = ConfigDict(frozen=True)

    id: str
    projection_type: ProjectionType
    content: str
    input_fingerprint: str
    metadata: dict = Field(default_factory=dict)

    _validate_id = field_validator("id")(_require_non_empty)
    _validate_projection_type = field_validator("projection_type")(_require_non_empty)
    _validate_content = field_validator("content")(_require_non_empty)
    _validate_input_fingerprint = field_validator("input_fingerprint")(
        _require_non_empty
    )


def require_state_view_metadata(state_view: StateView, key: str) -> str:
    """Return the non-empty string value at key from state_view.metadata, raising ValueError if absent."""
    if key not in state_view.metadata:
        raise ValueError(f"state_view.metadata missing required key: {key}")
    value = state_view.metadata[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"state_view.metadata[{key!r}] must be a non-empty string")
    return value


def assemble_state_view(
    *,
    stage: str,
    artifact_id: str,
    projection_type: ProjectionType,
    inner_lines: list[str],
    metadata: dict,
) -> StateView:
    """Build a StateView from section content lines, adding STATE_VIEW framing and fingerprint.

    Adapters provide inner_lines (everything between the delimiters); framing,
    fingerprinting, and ID construction happen here.
    """
    content = "\n".join([STATE_VIEW_START, "", *inner_lines, STATE_VIEW_END]).rstrip()
    input_fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return StateView(
        id=f"state-view:{stage}:{artifact_id}:{input_fingerprint[:12]}",
        projection_type=projection_type,
        content=content,
        input_fingerprint=input_fingerprint,
        metadata=metadata,
    )


class ProjectionRenderer(Protocol):
    """Protocol for components that convert NorthStarProjectionInput into a StateView."""

    def render(self, input_data: NorthStarProjectionInput) -> StateView:
        """Render the projection input and return a StateView."""
        ...


def _render_section(title: str, items: tuple[NorthStarProjectionItem, ...]) -> str:
    """Render a single named section of the NorthStar projection with its items and provenance."""
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
        lines.append(f"   - id: {item.id}")
        lines.append(f"   - source: {item.source}")
        lines.append(f"   - authority: {item.authority}")
        lines.append(f"   - status: {item.status}")
    return "\n".join(lines)


def render_northstar_projection(input_data: NorthStarProjectionInput) -> str:
    """Render all four projection sections into a single multi-section markdown string."""
    sections = (
        _render_section("Framework Policy", input_data.framework_policy),
        _render_section("Project State", input_data.project_state),
        _render_section("Blackboard History", input_data.blackboard_history),
        _render_section("Runtime Context", input_data.runtime_context),
    )
    return "\n\n".join(sections)


def fingerprint_northstar_projection_input(input_data: NorthStarProjectionInput) -> str:
    """Return a deterministic SHA-256 hex fingerprint of the canonically serialized projection input."""
    canonical = json.dumps(
        input_data.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class NorthStarProjectionRenderer:
    """Renders NorthStarProjectionInput into a NorthStarView StateView with fingerprinting."""

    def render(self, input_data: NorthStarProjectionInput) -> "NorthStarView":
        """Render the input into a NorthStarView StateView."""
        content = render_northstar_projection(input_data)
        input_fingerprint = fingerprint_northstar_projection_input(input_data)
        return NorthStarView(
            id=f"projection:northstar:{input_fingerprint}",
            projection_type=ProjectionType.NORTH_STAR,
            content=content,
            input_fingerprint=input_fingerprint,
        )


NorthStarView = StateView


def render_northstar_view(
    input_data: NorthStarProjectionInput,
) -> NorthStarView:
    """Convenience function that renders a NorthStarProjectionInput to a NorthStarView."""
    return NorthStarProjectionRenderer().render(input_data)
