from __future__ import annotations


class PromptRenderer:
    def __init__(self, template: str):
        if not template.strip():
            raise ValueError("template must be a non-empty string")
        self.template = template

    def render(self, context: dict) -> str:
        rendered = self.template.format(**context)
        if not rendered.strip():
            raise ValueError("rendered prompt must be non-empty")
        return rendered


def render_prompt(template: str, context: dict) -> str:
    return PromptRenderer(template).render(context)
