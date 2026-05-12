import pytest

from baps.prompts import PromptRenderer, render_prompt


def test_prompt_renderer_renders_template_with_context() -> None:
    renderer = PromptRenderer("Hello {name}, goal: {goal}")
    rendered = renderer.render({"name": "Blue", "goal": "ship safely"})
    assert rendered == "Hello Blue, goal: ship safely"


def test_prompt_renderer_missing_variable_raises_key_error() -> None:
    renderer = PromptRenderer("Hello {name}")
    with pytest.raises(KeyError):
        renderer.render({})


def test_prompt_renderer_empty_template_raises_value_error() -> None:
    with pytest.raises(ValueError):
        PromptRenderer("   ")


def test_prompt_renderer_whitespace_only_output_raises_value_error() -> None:
    renderer = PromptRenderer("{blank}")
    with pytest.raises(ValueError):
        renderer.render({"blank": "   "})


def test_render_prompt_helper_works() -> None:
    rendered = render_prompt("Role: {role}", {"role": "referee"})
    assert rendered == "Role: referee"
