from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib import error, request

logger = logging.getLogger(__name__)


class Backend(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OLLAMA = "ollama"

_RETRY_DELAYS = (5.0, 15.0, 30.0)  # seconds to wait on 429, per attempt


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict


@dataclass(frozen=True)
class ToolCallRecord:
    """Immutable record of one tool call made during an agentic role turn."""
    role: str
    tool_name: str
    arguments: dict
    result: str
    created_at: str


class ModelClient:
    def generate(self, prompt: str, format: str | dict | None = None) -> str:
        raise NotImplementedError

    def generate_with_tools(self, prompt: str, tools: list[ToolDefinition]) -> ToolCall:
        raise NotImplementedError

    def generate_agentic(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        executor: Any,
        role_name: str = "",
        max_tool_calls: int = 10,
    ) -> tuple[str, list[ToolCallRecord]]:
        raise NotImplementedError


class FakeModelClient(ModelClient):
    def __init__(
        self,
        responses: list[str] | None = None,
        tool_responses: list[ToolCall | None] | None = None,
        agentic_sequences: list[list[ToolCall | str]] | None = None,
    ):
        self.responses = list(responses) if responses is not None else []
        self.tool_responses = list(tool_responses) if tool_responses is not None else []
        self.prompts: list[str] = []
        self.tool_prompts: list[str] = []
        self.agentic_prompts: list[str] = []
        self._response_index = 0
        self._tool_response_index = 0
        self._agentic_sequences: list[list[ToolCall | str]] = (
            [list(seq) for seq in agentic_sequences] if agentic_sequences is not None else []
        )

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

    def generate_agentic(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        executor: Any,
        role_name: str = "",
        max_tool_calls: int = 10,
    ) -> tuple[str, list[ToolCallRecord]]:
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        self.agentic_prompts.append(prompt)
        if not self._agentic_sequences:
            return ("", [])
        sequence = self._agentic_sequences.pop(0)
        records: list[ToolCallRecord] = []
        for item in sequence:
            if isinstance(item, ToolCall):
                result = executor.execute(item.name, item.arguments)
                records.append(ToolCallRecord(
                    role=role_name,
                    tool_name=item.name,
                    arguments=item.arguments,
                    result=result,
                    created_at="2024-01-01T00:00:00+00:00",
                ))
            else:
                return (str(item), records)
        return ("", records)


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
        for attempt, delay in enumerate((*_RETRY_DELAYS, None)):
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
                if exc.code == 429 and delay is not None:
                    logger.warning("[anthropic] rate limited, retrying in %ss (attempt %d)", delay, attempt + 1)
                    time.sleep(delay)
                    continue
                body_text = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"anthropic request failed [{exc.code}]: {body_text}") from exc
            except error.URLError as exc:
                raise RuntimeError(f"anthropic request failed: {exc}") from exc
        raise RuntimeError("anthropic request failed: rate limit retries exhausted")

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
        text = content[0].get("text")
        if text is None:
            raise RuntimeError("anthropic response content block missing 'text' field")
        return text

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

    def generate_agentic(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        executor: Any,
        role_name: str = "",
        max_tool_calls: int = 10,
    ) -> tuple[str, list[ToolCallRecord]]:
        import datetime
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        tool_schemas = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in tools
        ]
        messages: list[dict] = [{"role": "user", "content": prompt}]
        records: list[ToolCallRecord] = []
        for _ in range(max_tool_calls + 1):
            data = self._post({
                "model": self.model,
                "max_tokens": _ANTHROPIC_MAX_TOKENS,
                "tools": tool_schemas,
                "messages": messages,
            })
            content = data.get("content", [])
            stop_reason = data.get("stop_reason", "")
            tool_blocks = [b for b in content if b.get("type") == "tool_use"]
            text_blocks = [b for b in content if b.get("type") == "text"]
            if not tool_blocks or stop_reason == "end_turn":
                if text_blocks:
                    text = text_blocks[0].get("text")
                    if text is None:
                        raise RuntimeError("anthropic agentic response text block missing 'text' field")
                else:
                    text = ""
                return (text, records)
            tool_results = []
            for block in tool_blocks:
                tool_id = block.get("id", "")
                name = block.get("name", "")
                arguments = block.get("input", {})
                result = executor.execute(name, arguments)
                records.append(ToolCallRecord(
                    role=role_name,
                    tool_name=name,
                    arguments=arguments,
                    result=result,
                    created_at=datetime.datetime.now(datetime.UTC).isoformat(),
                ))
                tool_results.append({"type": "tool_result", "tool_use_id": tool_id, "content": result})
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": tool_results})
        return ("", records)


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
        for attempt, delay in enumerate((*_RETRY_DELAYS, None)):
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
                if exc.code == 429 and delay is not None:
                    logger.warning("[openai] rate limited, retrying in %ss (attempt %d)", delay, attempt + 1)
                    time.sleep(delay)
                    continue
                body_text = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"openai request failed [{exc.code}]: {body_text}") from exc
            except error.URLError as exc:
                raise RuntimeError(f"openai request failed: {exc}") from exc
        raise RuntimeError("openai request failed: rate limit retries exhausted")

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

    def generate_agentic(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        executor: Any,
        role_name: str = "",
        max_tool_calls: int = 10,
    ) -> tuple[str, list[ToolCallRecord]]:
        import datetime
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        tool_schemas = [
            {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in tools
        ]
        messages: list[dict] = [{"role": "user", "content": prompt}]
        records: list[ToolCallRecord] = []
        for _ in range(max_tool_calls + 1):
            payload: dict = {"model": self.model, "messages": messages, "tools": tool_schemas}
            data = self._post(payload)
            choices = data.get("choices", [])
            if not choices:
                return ("", records)
            msg = choices[0].get("message", {})
            finish_reason = choices[0].get("finish_reason", "")
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls or finish_reason == "stop":
                return (msg.get("content", "") or "", records)
            messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls})
            for tc in tool_calls:
                call_id = tc.get("id", "")
                fn = tc.get("function", {})
                name = fn.get("name", "")
                raw_args = fn.get("arguments", {})
                arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                result = executor.execute(name, arguments)
                records.append(ToolCallRecord(
                    role=role_name, tool_name=name, arguments=arguments, result=result,
                    created_at=datetime.datetime.now(datetime.UTC).isoformat(),
                ))
                messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
        return ("", records)


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

    def generate_agentic(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        executor: Any,
        role_name: str = "",
        max_tool_calls: int = 10,
    ) -> tuple[str, list[ToolCallRecord]]:
        import datetime
        if not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        tool_schemas = [
            {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in tools
        ]
        messages: list[dict] = [{"role": "user", "content": prompt}]
        records: list[ToolCallRecord] = []
        for _ in range(max_tool_calls + 1):
            payload = {"model": self.model, "messages": messages, "tools": tool_schemas, "stream": False}
            body = json.dumps(payload).encode("utf-8")
            req = request.Request(
                url=f"{self.base_url}/api/chat", data=body,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            try:
                with request.urlopen(req) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except (error.HTTPError, error.URLError) as exc:
                raise RuntimeError(f"ollama request failed: {exc}") from exc
            msg = data.get("message", {})
            done = data.get("done", False)
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls or done:
                return (msg.get("content", "") or "", records)
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                arguments = fn.get("arguments", {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}
                result = executor.execute(name, arguments)
                records.append(ToolCallRecord(
                    role=role_name, tool_name=name, arguments=arguments, result=result,
                    created_at=datetime.datetime.now(datetime.UTC).isoformat(),
                ))
            messages.append({"role": "assistant", "content": "", "tool_calls": tool_calls})
            messages.append({"role": "tool", "content": "\n".join(r.result for r in records[-len(tool_calls):])})
        return ("", records)


class FallbackClient(ModelClient):
    """Tries each client in order, falling back on RuntimeError (transport/billing failures).

    ValueError (e.g. model did not invoke a tool) is not a transport failure and propagates
    immediately without trying the next client.
    """

    def __init__(self, clients: list[ModelClient]) -> None:
        if not clients:
            raise ValueError("clients must be non-empty")
        self._clients = list(clients)

    def generate(self, prompt: str, format: str | dict | None = None) -> str:
        last_exc: Exception | None = None
        for i, client in enumerate(self._clients):
            try:
                return client.generate(prompt, format=format)
            except RuntimeError as exc:
                logger.warning("[fallback] client %d (%s) failed: %s; trying next", i, type(client).__name__, exc)
                last_exc = exc
        raise RuntimeError(
            f"all {len(self._clients)} fallback clients failed; last: {last_exc}"
        ) from last_exc

    def generate_with_tools(self, prompt: str, tools: list[ToolDefinition]) -> ToolCall:
        last_exc: Exception | None = None
        for i, client in enumerate(self._clients):
            try:
                return client.generate_with_tools(prompt, tools)
            except RuntimeError as exc:
                logger.warning("[fallback] client %d (%s) failed: %s; trying next", i, type(client).__name__, exc)
                last_exc = exc
        raise RuntimeError(
            f"all {len(self._clients)} fallback clients failed; last: {last_exc}"
        ) from last_exc

    def generate_agentic(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        executor: Any,
        role_name: str = "",
        max_tool_calls: int = 10,
    ) -> tuple[str, list[ToolCallRecord]]:
        last_exc: Exception | None = None
        for i, client in enumerate(self._clients):
            try:
                return client.generate_agentic(prompt, tools, executor, role_name=role_name, max_tool_calls=max_tool_calls)
            except RuntimeError as exc:
                logger.warning("[fallback] client %d (%s) failed: %s; trying next", i, type(client).__name__, exc)
                last_exc = exc
        raise RuntimeError(
            f"all {len(self._clients)} fallback clients failed; last: {last_exc}"
        ) from last_exc


@dataclass(frozen=True)
class Role:
    name: str
    client: ModelClient
    schema: str | dict | None = None
    constrained: bool = False

    def generate(self, prompt: str) -> str:
        from baps.models.model_output import wrap_json_prompt
        return self.client.generate(wrap_json_prompt(prompt), format=self.schema if self.constrained else None)

    def generate_with_tools(self, prompt: str, tools: list[ToolDefinition]) -> ToolCall:
        return self.client.generate_with_tools(prompt, tools)

    def generate_agentic(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        executor: Any,
        max_tool_calls: int = 10,
    ) -> tuple[str, list[ToolCallRecord]]:
        return self.client.generate_agentic(
            prompt, tools, executor, role_name=self.name, max_tool_calls=max_tool_calls
        )
