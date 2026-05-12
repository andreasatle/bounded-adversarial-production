from __future__ import annotations

import json
from urllib import error, request


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


class OllamaClient(ModelClient):
    def __init__(self, model: str, base_url: str = "http://localhost:11434"):
        if not model.strip():
            raise ValueError("model must be a non-empty string")
        if not base_url.strip():
            raise ValueError("base_url must be a non-empty string")
        self.model = model
        self.base_url = base_url.rstrip("/")

    def generate(self, prompt: str) -> str:
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=f"{self.base_url}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (error.HTTPError, error.URLError) as exc:
            raise RuntimeError(f"ollama request failed: {exc}") from exc

        if "response" not in data:
            raise RuntimeError("ollama response missing 'response' field")
        return data["response"]
