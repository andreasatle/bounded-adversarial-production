import json
from pathlib import Path

import pytest

from baps.game_types import (
    GameRequest,
    GameDefinition,
    build_game_definition,
    get_builtin_game_definition,
    load_game_definition,
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


def test_get_builtin_game_definition_returns_documentation_refinement() -> None:
    definition = get_builtin_game_definition("documentation-refinement")
    assert definition.id == "documentation-refinement"


def test_get_builtin_game_definition_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="unknown game type: unknown-type"):
        get_builtin_game_definition("unknown-type")


def test_load_game_definition_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "game-definition.json"
    path.write_text(
        json.dumps(
            {
                "id": "custom-doc-refine",
                "name": "Custom Doc Refine",
                "description": "Custom definition",
                "prompt_sections": {
                    "blue_sections": [{"name": "Blue", "content": "blue guidance"}],
                    "red_sections": [{"name": "Red", "content": "red guidance"}],
                    "referee_sections": [{"name": "Ref", "content": "ref guidance"}],
                },
            }
        ),
        encoding="utf-8",
    )

    definition = load_game_definition(path)
    assert definition.id == "custom-doc-refine"
    assert definition.name == "Custom Doc Refine"


def test_load_game_definition_missing_file_fails(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError):
        load_game_definition(path)


def test_load_game_definition_invalid_json_fails(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_game_definition(path)


def test_load_game_definition_invalid_schema_fails(tmp_path: Path) -> None:
    path = tmp_path / "invalid-schema.json"
    path.write_text(json.dumps({"id": "x"}), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid GameDefinition schema"):
        load_game_definition(path)


def test_load_checked_in_example_game_definition() -> None:
    path = Path("examples/game_definitions/documentation_refinement.json")
    definition = load_game_definition(path)
    assert definition.id.strip()
    assert definition.name.strip()
    assert definition.description.strip()
    assert len(definition.prompt_sections.blue_sections) >= 1
    assert len(definition.prompt_sections.red_sections) >= 1
    assert len(definition.prompt_sections.referee_sections) >= 1


def test_game_request_validation_and_empty_target_ref_allowed() -> None:
    request = GameRequest(
        game_type="documentation-refinement",
        subject="README",
        goal="Improve quickstart clarity",
        target_kind="documentation",
        target_ref="",
    )
    assert request.target_ref == ""

    with pytest.raises(ValueError):
        GameRequest(
            game_type=" ",
            subject="README",
            goal="Improve quickstart clarity",
            target_kind="documentation",
            target_ref="README.md",
        )
    with pytest.raises(ValueError):
        GameRequest(
            game_type="documentation-refinement",
            subject=" ",
            goal="Improve quickstart clarity",
            target_kind="documentation",
            target_ref="README.md",
        )
    with pytest.raises(ValueError):
        GameRequest(
            game_type="documentation-refinement",
            subject="README",
            goal=" ",
            target_kind="documentation",
            target_ref="README.md",
        )
    with pytest.raises(ValueError):
        GameRequest(
            game_type="documentation-refinement",
            subject="README",
            goal="Improve quickstart clarity",
            target_kind=" ",
            target_ref="README.md",
        )


def test_build_game_definition_success_path() -> None:
    request = GameRequest(
        game_type="documentation-refinement",
        subject="README",
        goal="Improve quickstart clarity",
        target_kind="documentation",
        target_ref="README.md",
    )
    definition = build_game_definition(request)
    assert definition.id == "documentation-refinement"
    assert definition.name == "Documentation Refinement"
    assert definition.description.strip()
    assert len(definition.prompt_sections.blue_sections) >= 1
    assert len(definition.prompt_sections.red_sections) >= 1
    assert len(definition.prompt_sections.referee_sections) >= 1


def test_build_game_definition_unsupported_game_type_fails() -> None:
    request = GameRequest(
        game_type="unsupported-type",
        subject="README",
        goal="Improve quickstart clarity",
        target_kind="documentation",
        target_ref="README.md",
    )
    with pytest.raises(ValueError, match="unsupported game type in request: unsupported-type"):
        build_game_definition(request)
