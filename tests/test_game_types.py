from baps.game_types import make_documentation_refinement_game_type


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


def test_game_type_section_defaults_are_isolated() -> None:
    a = make_documentation_refinement_game_type()
    b = make_documentation_refinement_game_type()
    a.blue_sections.append(a.blue_sections[0])
    assert len(a.blue_sections) == len(b.blue_sections) + 1
