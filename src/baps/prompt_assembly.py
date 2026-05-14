from __future__ import annotations

from pydantic import BaseModel, field_validator


def _require_non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("must be a non-empty string")
    return value


class PromptSection(BaseModel):
    name: str
    content: str

    _validate_name = field_validator("name")(_require_non_empty)
    _validate_content = field_validator("content")(_require_non_empty)


class PromptSpec(BaseModel):
    sections: list[PromptSection]

    @field_validator("sections")
    @classmethod
    def validate_sections(cls, value: list[PromptSection]) -> list[PromptSection]:
        if not value:
            raise ValueError("sections must be non-empty")
        names = [section.name for section in value]
        if len(names) != len(set(names)):
            raise ValueError("section names must be unique")
        return value


def assemble_prompt(spec: PromptSpec) -> str:
    parts: list[str] = []
    for section in spec.sections:
        parts.append(f"## {section.name}\n{section.content}")
    assembled = "\n\n".join(parts)
    if not assembled.strip():
        raise ValueError("assembled prompt must be non-empty")
    return assembled
