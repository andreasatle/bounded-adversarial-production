from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib import error, request


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict


class ModelClient:
    def generate(self, prompt: str, format: str | dict | None = None) -> str:
        raise NotImplementedError

    def generate_with_tools(self, prompt: str, tools: list[ToolDefinition]) -> ToolCall:
        raise NotImplementedError


class FakeModelClient(ModelClient):
    def __init__(
        self,
        responses: list[str] | None = None,
        tool_responses: list[ToolCall | None] | None = None,
    ):
        self.responses = list(responses) if responses is not None else []
        self.tool_responses = list(tool_responses) if tool_responses is not None else []
        self.prompts: list[str] = []
        self.tool_prompts: list[str] = []
        self._response_index = 0
        self._tool_response_index = 0

    def generate(self, prompt: str, format: str | dict | None = None) -> str:
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")

        self.prompts.append(prompt)
        if self._response_index >= len(self.responses):
            raise RuntimeError("no fake responses remaining")

        response = self.responses[self._response_index]
        self._response_index += 1
        return response

    def generate_with_tools(self, prompt: str, tools: list[ToolDefinition]) -> ToolCall:
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")

        self.tool_prompts.append(prompt)
        if self._tool_response_index >= len(self.tool_responses):
            raise RuntimeError("no fake tool responses remaining")

        response = self.tool_responses[self._tool_response_index]
        self._tool_response_index += 1
        if response is None:
            raise ValueError("model did not invoke any tool")
        return response


class OllamaClient(ModelClient):
    def __init__(self, model: str, base_url: str = "http://localhost:11434"):
        if not model.strip():
            raise ValueError("model must be a non-empty string")
        if not base_url.strip():
            raise ValueError("base_url must be a non-empty string")
        self.model = model
        self.base_url = base_url.rstrip("/")

    def generate(self, prompt: str, format: str | dict | None = None) -> str:
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")

        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        if format is not None:
            payload["format"] = format
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

    def generate_with_tools(self, prompt: str, tools: list[ToolDefinition]) -> ToolCall:
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")

        tool_schemas = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "tools": tool_schemas,
            "stream": False,
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=f"{self.base_url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (error.HTTPError, error.URLError) as exc:
            raise RuntimeError(f"ollama request failed: {exc}") from exc

        tool_calls = data.get("message", {}).get("tool_calls", [])
        if not tool_calls:
            raise ValueError("model did not invoke any tool")

        fn = tool_calls[0].get("function", {})
        name = fn.get("name", "")
        arguments = fn.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise ValueError(f"tool call arguments not valid JSON: {exc}") from exc
        return ToolCall(name=name, arguments=arguments)
