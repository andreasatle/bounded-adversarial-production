import pytest
from pydantic import ValidationError

from baps.prompt_assembly import PromptSection, PromptSpec, assemble_prompt


def test_prompt_section_requires_non_empty_name_and_content() -> None:
    with pytest.raises(ValidationError):
        PromptSection(name="", content="x")
    with pytest.raises(ValidationError):
        PromptSection(name="   ", content="x")
    with pytest.raises(ValidationError):
        PromptSection(name="role", content="")
    with pytest.raises(ValidationError):
        PromptSection(name="role", content="   ")


def test_prompt_spec_requires_non_empty_sections() -> None:
    with pytest.raises(ValidationError):
        PromptSpec(sections=[])


def test_prompt_spec_rejects_duplicate_section_names() -> None:
    with pytest.raises(ValidationError):
        PromptSpec(
            sections=[
                PromptSection(name="Role", content="first"),
                PromptSection(name="Role", content="second"),
            ]
        )


def test_assemble_prompt_preserves_section_order() -> None:
    spec = PromptSpec(
        sections=[
            PromptSection(name="One", content="first"),
            PromptSection(name="Two", content="second"),
        ]
    )
    rendered = assemble_prompt(spec)
    assert rendered.index("## One") < rendered.index("## Two")
    assert "first" in rendered
    assert "second" in rendered


def test_assemble_prompt_rejects_whitespace_only_output() -> None:
    spec = PromptSpec(sections=[PromptSection(name="One", content="x")])
    assert assemble_prompt(spec).strip() != ""
