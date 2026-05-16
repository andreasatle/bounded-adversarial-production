from __future__ import annotations

from pydantic import BaseModel, field_validator


def _require_non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("must be a non-empty string")
    return value


class NorthStarProjectionItem(BaseModel):
    content: str
    source: str
    authority: str
    status: str

    _validate_content = field_validator("content")(_require_non_empty)
    _validate_source = field_validator("source")(_require_non_empty)
    _validate_authority = field_validator("authority")(_require_non_empty)
    _validate_status = field_validator("status")(_require_non_empty)


class NorthStarProjectionInput(BaseModel):
    framework_policy: tuple[NorthStarProjectionItem, ...] = ()
    project_state: tuple[NorthStarProjectionItem, ...] = ()
    blackboard_history: tuple[NorthStarProjectionItem, ...] = ()
    runtime_context: tuple[NorthStarProjectionItem, ...] = ()


def _render_section(title: str, items: tuple[NorthStarProjectionItem, ...]) -> str:
    lines = [f"## {title}"]
    if not items:
        lines.append("_No items._")
        return "\n".join(lines)

    for index, item in enumerate(items, start=1):
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
