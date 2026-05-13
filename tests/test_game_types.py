import pytest

from baps.game_types import (
    GameDefinition,
    make_documentation_refinement_game_definition,
    make_documentation_refinement_game_type,
)
from baps.prompt_assembly import PromptSection


def test_documentation_refinement_game_type_contains_expected_sections() -> None:
    sections = make_documentation_refinement_game_type()
    assert len(sections.blue_sections) >= 1
    assert len(sections.red_sections) >= 1
    assert len(sections.referee_sections) >= 1
    assert "documentation refinement" in sections.blue_sections[0].content
    assert "Red critiques only the current Blue-produced delta" in sections.red_sections[0].content
    referee_content = sections.referee_sections[0].content
    assert "Accept when Red reports no material issue." in referee_content
    assert (
        "Accept when Red provides praise, confirmation, minor wording preference, or optional polish."
        in referee_content
    )
    assert (
        "Revise only when Red identifies a material discrepancy that another round is expected to reduce."
        in referee_content
    )
    assert "Do not recommend another revision merely because the candidate could be marginally polished." in referee_content
    assert "The rationale must support the already-fixed structured decision." in referee_content


def test_documentation_refinement_game_definition_contains_metadata_and_sections() -> None:
    definition = make_documentation_refinement_game_definition()
    assert definition.id == "documentation-refinement"
    assert definition.name == "Documentation Refinement"
    assert "bounded adversarial critique" in definition.description
    assert len(definition.prompt_sections.blue_sections) >= 1
    assert len(definition.prompt_sections.red_sections) >= 1
    assert len(definition.prompt_sections.referee_sections) >= 1


def test_game_definition_rejects_empty_required_strings() -> None:
    with pytest.raises(ValueError):
        GameDefinition(
            id=" ",
            name="Name",
            description="Description",
            prompt_sections=make_documentation_refinement_game_type(),
        )
    with pytest.raises(ValueError):
        GameDefinition(
            id="doc-refine",
            name=" ",
            description="Description",
            prompt_sections=make_documentation_refinement_game_type(),
        )
    with pytest.raises(ValueError):
        GameDefinition(
            id="doc-refine",
            name="Name",
            description=" ",
            prompt_sections=make_documentation_refinement_game_type(),
        )


def test_game_type_helper_is_compatibility_wrapper() -> None:
    sections = make_documentation_refinement_game_type()
    definition_sections = make_documentation_refinement_game_definition().prompt_sections
    assert sections.model_dump(mode="json") == definition_sections.model_dump(mode="json")


def test_game_type_section_defaults_are_isolated() -> None:
    a = make_documentation_refinement_game_type()
    b = make_documentation_refinement_game_type()
    a.blue_sections.append(a.blue_sections[0])
    assert len(a.blue_sections) == len(b.blue_sections) + 1


def test_game_definition_prompt_sections_are_isolated() -> None:
    a = make_documentation_refinement_game_definition()
    b = make_documentation_refinement_game_definition()
    a.prompt_sections.red_sections.append(PromptSection(name="Extra", content="extra"))
    assert len(a.prompt_sections.red_sections) == len(b.prompt_sections.red_sections) + 1
