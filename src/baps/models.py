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


_ANTHROPIC_API_VERSION = "2023-06-01"
_ANTHROPIC_MAX_TOKENS = 4096


class AnthropicClient(ModelClient):
    def __init__(self, model: str, api_key: str, base_url: str = "https://api.anthropic.com"):
        if not model.strip():
            raise ValueError("model must be a non-empty string")
        if not api_key.strip():
            raise ValueError("api_key must be a non-empty string")
        if not base_url.strip():
            raise ValueError("base_url must be a non-empty string")
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _post(self, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=f"{self.base_url}/v1/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": _ANTHROPIC_API_VERSION,
            },
            method="POST",
        )
        try:
            with request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"anthropic request failed [{exc.code}]: {body_text}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"anthropic request failed: {exc}") from exc

    def generate(self, prompt: str, format: str | dict | None = None) -> str:
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")

        if isinstance(format, dict):
            data = self._post({
                "model": self.model,
                "max_tokens": _ANTHROPIC_MAX_TOKENS,
                "tools": [{"name": "output", "description": "Return the structured output.", "input_schema": format}],
                "tool_choice": {"type": "tool", "name": "output"},
                "messages": [{"role": "user", "content": prompt}],
            })
            for block in data.get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "output":
                    return json.dumps(block["input"])
            raise RuntimeError("anthropic structured response missing tool_use content block")

        data = self._post({
            "model": self.model,
            "max_tokens": _ANTHROPIC_MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        })
        content = data.get("content", [])
        if not content:
            raise RuntimeError("anthropic response missing content")
        return content[0].get("text", "")

    def generate_with_tools(self, prompt: str, tools: list[ToolDefinition]) -> ToolCall:
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")

        tool_schemas = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in tools
        ]
        data = self._post({
            "model": self.model,
            "max_tokens": _ANTHROPIC_MAX_TOKENS,
            "tools": tool_schemas,
            "tool_choice": {"type": "any"},
            "messages": [{"role": "user", "content": prompt}],
        })
        for block in data.get("content", []):
            if block.get("type") == "tool_use":
                return ToolCall(name=block["name"], arguments=block.get("input", {}))
        raise ValueError("model did not invoke any tool")


class OpenAIClient(ModelClient):
    def __init__(self, model: str, api_key: str, base_url: str = "https://api.openai.com/v1"):
        if not model.strip():
            raise ValueError("model must be a non-empty string")
        if not api_key.strip():
            raise ValueError("api_key must be a non-empty string")
        if not base_url.strip():
            raise ValueError("base_url must be a non-empty string")
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _post(self, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"openai request failed [{exc.code}]: {body_text}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"openai request failed: {exc}") from exc

    def generate(self, prompt: str, format: str | dict | None = None) -> str:
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")

        payload: dict = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if isinstance(format, dict):
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": format, "strict": False},
            }
        data = self._post(payload)
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("openai response missing choices")
        return choices[0].get("message", {}).get("content", "")

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
        data = self._post({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "tools": tool_schemas,
            "tool_choice": "required",
        })
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("openai response missing choices")
        tool_calls = choices[0].get("message", {}).get("tool_calls", [])
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


@dataclass(frozen=True)
class Role:
    name: str
    client: ModelClient
    schema: str | dict | None = None
    constrained: bool = False

    def generate(self, prompt: str) -> str:
        return self.client.generate(prompt, format=self.schema if self.constrained else None)

    def generate_with_tools(self, prompt: str, tools: list[ToolDefinition]) -> ToolCall:
        return self.client.generate_with_tools(prompt, tools)
