from __future__ import annotations


class ModelClient:
    def generate(self, prompt: str) -> str:
        raise NotImplementedError


class FakeModelClient(ModelClient):
    def __init__(self, responses: list[str] | None = None):
        self.responses = list(responses) if responses is not None else []
        self.prompts: list[str] = []
        self._response_index = 0

    def generate(self, prompt: str) -> str:
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")

        self.prompts.append(prompt)
        if self._response_index >= len(self.responses):
            raise RuntimeError("no fake responses remaining")

        response = self.responses[self._response_index]
        self._response_index += 1
        return response
