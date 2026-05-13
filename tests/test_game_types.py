from baps.game_types import make_documentation_refinement_game_type


def test_documentation_refinement_game_type_contains_expected_sections() -> None:
    sections = make_documentation_refinement_game_type()
    assert len(sections.blue_sections) >= 1
    assert len(sections.red_sections) >= 1
    assert len(sections.referee_sections) >= 1
    assert "documentation refinement" in sections.blue_sections[0].content
    assert "Red critiques only the current Blue-produced delta" in sections.red_sections[0].content
    assert "Accept when no material discrepancy remains" in sections.referee_sections[0].content


def test_game_type_section_defaults_are_isolated() -> None:
    a = make_documentation_refinement_game_type()
    b = make_documentation_refinement_game_type()
    a.blue_sections.append(a.blue_sections[0])
    assert len(a.blue_sections) == len(b.blue_sections) + 1
