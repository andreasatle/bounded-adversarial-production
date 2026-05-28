import json
from urllib import error

import pytest

from baps.models import AnthropicClient, FakeModelClient, FallbackClient, ModelClient, OllamaClient, OpenAIClient, Role, ToolCall, ToolDefinition


def test_fake_model_client_returns_responses_in_order() -> None:
    client = FakeModelClient(responses=["first", "second"])

    assert client.generate("prompt 1") == "first"
    assert client.generate("prompt 2") == "second"


def test_fake_model_client_records_prompts() -> None:
    client = FakeModelClient(responses=["ok", "ok2"])

    client.generate("alpha")
    client.generate("beta")

    assert client.prompts == ["alpha", "beta"]


def test_fake_model_client_rejects_empty_prompt() -> None:
    client = FakeModelClient(responses=["ok"])

    with pytest.raises(ValueError):
        client.generate("   ")


def test_fake_model_client_raises_when_responses_exhausted() -> None:
    client = FakeModelClient(responses=["only"])
    client.generate("prompt 1")

    with pytest.raises(RuntimeError):
        client.generate("prompt 2")


def test_model_client_generate_raises_not_implemented() -> None:
    client = ModelClient()

    with pytest.raises(NotImplementedError):
        client.generate("prompt")


def test_ollama_client_rejects_empty_model() -> None:
    with pytest.raises(ValueError):
        OllamaClient(model="   ")


def test_ollama_client_rejects_empty_base_url() -> None:
    with pytest.raises(ValueError):
        OllamaClient(model="llama3", base_url="   ")


def test_ollama_client_generate_rejects_empty_prompt() -> None:
    client = OllamaClient(model="llama3")
    with pytest.raises(ValueError):
        client.generate("   ")


def test_ollama_client_generate_sends_expected_request_body(monkeypatch) -> None:
    client = OllamaClient(model="llama3", base_url="http://localhost:11434")
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"response":"ok"}'

    def fake_urlopen(req):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["body"] = req.data
        return FakeResponse()

    monkeypatch.setattr("baps.models.request.urlopen", fake_urlopen)

    result = client.generate("hello")

    assert result == "ok"
    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["method"] == "POST"
    assert json.loads(captured["body"].decode("utf-8")) == {
        "model": "llama3",
        "prompt": "hello",
        "stream": False,
    }


def test_ollama_client_generate_returns_response_field(monkeypatch) -> None:
    client = OllamaClient(model="llama3")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"response":"generated text"}'

    monkeypatch.setattr("baps.models.request.urlopen", lambda req: FakeResponse())
    assert client.generate("prompt") == "generated text"


def test_ollama_client_generate_raises_when_response_missing(monkeypatch) -> None:
    client = OllamaClient(model="llama3")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"done": true}'

    monkeypatch.setattr("baps.models.request.urlopen", lambda req: FakeResponse())
    with pytest.raises(RuntimeError):
        client.generate("prompt")


def test_ollama_client_generate_raises_runtime_error_on_http_error(monkeypatch) -> None:
    client = OllamaClient(model="llama3")

    def fake_urlopen(req):
        raise error.HTTPError(
            url=req.full_url,
            code=500,
            msg="server error",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("baps.models.request.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError):
        client.generate("prompt")


def test_ollama_client_generate_raises_runtime_error_on_url_error(monkeypatch) -> None:
    client = OllamaClient(model="llama3")

    def fake_urlopen(req):
        raise error.URLError("connection refused")

    monkeypatch.setattr("baps.models.request.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError):
        client.generate("prompt")


def test_role_generate_without_constrained_passes_no_format() -> None:
    from baps.model_output import _JSON_ONLY_INSTRUCTION
    client = FakeModelClient(responses=["result"])
    role = Role("blue", client, schema={"type": "object"}, constrained=False)

    result = role.generate("my prompt")

    assert result == "result"
    assert len(client.prompts) == 1
    sent = client.prompts[0]
    assert sent.startswith(_JSON_ONLY_INSTRUCTION)
    assert sent.endswith(_JSON_ONLY_INSTRUCTION)
    assert "my prompt" in sent


def test_role_generate_wraps_prompt_for_every_call() -> None:
    from baps.model_output import _JSON_ONLY_INSTRUCTION
    client = FakeModelClient(responses=["r1", "r2"])
    role = Role("create_game", client)

    role.generate("first")
    role.generate("second")

    assert _JSON_ONLY_INSTRUCTION in client.prompts[0]
    assert _JSON_ONLY_INSTRUCTION in client.prompts[1]
    assert "first" in client.prompts[0]
    assert "second" in client.prompts[1]


def test_role_generate_with_tools_does_not_wrap() -> None:
    client = FakeModelClient(tool_responses=[ToolCall(name="write_file", arguments={"path": "x.py", "content": ""})])
    role = Role("blue", client)

    role.generate_with_tools("use a tool", [ToolDefinition(name="write_file", description="write")])

    # generate_with_tools records to tool_prompts, not prompts
    assert client.tool_prompts == ["use a tool"]


def test_role_generate_with_constrained_passes_schema_as_format(monkeypatch) -> None:
    schema = {"type": "object", "properties": {"disposition": {"type": "string", "enum": ["accept"]}}}
    captured: dict = {}

    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return b'{"response":"{\\"disposition\\":\\"accept\\"}"}'

    def fake_urlopen(req):
        captured["body"] = json.loads(req.data.decode())
        return FakeResponse()

    monkeypatch.setattr("baps.models.request.urlopen", fake_urlopen)
    client = OllamaClient(model="llama3")
    role = Role("red", client, schema=schema, constrained=True)

    role.generate("evaluate this")

    assert captured["body"]["format"] == schema


def test_role_generate_with_constrained_false_omits_format(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return b'{"response":"ok"}'

    def fake_urlopen(req):
        captured["body"] = json.loads(req.data.decode())
        return FakeResponse()

    monkeypatch.setattr("baps.models.request.urlopen", fake_urlopen)
    client = OllamaClient(model="llama3")
    role = Role("create_game", client, schema={"type": "object"}, constrained=False)

    role.generate("plan something")

    assert "format" not in captured["body"]


def test_role_generate_with_no_schema_omits_format(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return b'{"response":"ok"}'

    def fake_urlopen(req):
        captured["body"] = json.loads(req.data.decode())
        return FakeResponse()

    monkeypatch.setattr("baps.models.request.urlopen", fake_urlopen)
    client = OllamaClient(model="llama3")
    role = Role("blue", client, schema=None, constrained=True)

    role.generate("write something")

    assert "format" not in captured["body"]


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_fake_urlopen(response_body: bytes):
    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return response_body
    return lambda req: _Resp()


def _make_capturing_urlopen(response_body: bytes, captured: dict):
    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return response_body
    def _urlopen(req):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["headers"] = dict(req.headers)
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _Resp()
    return _urlopen


# ---------------------------------------------------------------------------
# AnthropicClient
# ---------------------------------------------------------------------------

def test_anthropic_client_rejects_empty_model() -> None:
    with pytest.raises(ValueError):
        AnthropicClient(model="   ", api_key="key")


def test_anthropic_client_rejects_empty_api_key() -> None:
    with pytest.raises(ValueError):
        AnthropicClient(model="claude-sonnet-4-6", api_key="   ")


def test_anthropic_client_generate_plain_text(monkeypatch) -> None:
    body = json.dumps({"content": [{"type": "text", "text": "hello world"}]}).encode()
    monkeypatch.setattr("baps.models.request.urlopen", _make_fake_urlopen(body))
    client = AnthropicClient(model="claude-sonnet-4-6", api_key="test-key")
    result = client.generate("say hello")
    assert result == "hello world"


def test_anthropic_client_generate_sends_correct_headers(monkeypatch) -> None:
    body = json.dumps({"content": [{"type": "text", "text": "ok"}]}).encode()
    captured: dict = {}
    monkeypatch.setattr("baps.models.request.urlopen", _make_capturing_urlopen(body, captured))
    client = AnthropicClient(model="claude-sonnet-4-6", api_key="sk-ant-123", base_url="https://api.anthropic.com")
    client.generate("prompt")
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"].get("X-api-key") == "sk-ant-123"
    assert "Anthropic-version" in captured["headers"]


def test_anthropic_client_generate_with_schema_uses_tool_use(monkeypatch) -> None:
    output_data = {"disposition": "accept", "rationale": "good"}
    body = json.dumps({
        "content": [{"type": "tool_use", "name": "output", "input": output_data}],
        "stop_reason": "tool_use",
    }).encode()
    captured: dict = {}
    monkeypatch.setattr("baps.models.request.urlopen", _make_capturing_urlopen(body, captured))
    client = AnthropicClient(model="claude-sonnet-4-6", api_key="key")
    schema = {"type": "object", "properties": {"disposition": {"type": "string"}}}
    result = client.generate("evaluate", format=schema)
    assert json.loads(result) == output_data
    assert captured["body"]["tool_choice"] == {"type": "tool", "name": "output"}
    assert captured["body"]["tools"][0]["name"] == "output"
    assert captured["body"]["tools"][0]["input_schema"] == schema


def test_anthropic_client_generate_raises_on_http_error(monkeypatch) -> None:
    def fake_urlopen(req):
        fp = __import__("io").BytesIO(b'{"error": "unauthorized"}')
        raise error.HTTPError(req.full_url, 401, "Unauthorized", {}, fp)
    monkeypatch.setattr("baps.models.request.urlopen", fake_urlopen)
    client = AnthropicClient(model="claude-sonnet-4-6", api_key="bad-key")
    with pytest.raises(RuntimeError, match="401"):
        client.generate("prompt")


def test_anthropic_client_generate_with_tools(monkeypatch) -> None:
    from baps.models import ToolDefinition
    body = json.dumps({
        "content": [{"type": "tool_use", "name": "write_file", "input": {"path": "src/x.py", "content": "pass"}}],
    }).encode()
    captured: dict = {}
    monkeypatch.setattr("baps.models.request.urlopen", _make_capturing_urlopen(body, captured))
    client = AnthropicClient(model="claude-sonnet-4-6", api_key="key")
    tools = [ToolDefinition(name="write_file", description="Write a file", parameters={"type": "object"})]
    result = client.generate_with_tools("write something", tools)
    assert result.name == "write_file"
    assert result.arguments == {"path": "src/x.py", "content": "pass"}
    assert captured["body"]["tool_choice"] == {"type": "any"}
    assert captured["body"]["tools"][0]["input_schema"] == {"type": "object"}


def test_anthropic_client_generate_with_tools_raises_when_no_tool_called(monkeypatch) -> None:
    from baps.models import ToolDefinition
    body = json.dumps({"content": [{"type": "text", "text": "I cannot help."}]}).encode()
    monkeypatch.setattr("baps.models.request.urlopen", _make_fake_urlopen(body))
    client = AnthropicClient(model="claude-sonnet-4-6", api_key="key")
    tools = [ToolDefinition(name="write_file", description="Write", parameters={})]
    with pytest.raises(ValueError, match="tool"):
        client.generate_with_tools("do something", tools)


# ---------------------------------------------------------------------------
# OpenAIClient
# ---------------------------------------------------------------------------

def test_openai_client_rejects_empty_model() -> None:
    with pytest.raises(ValueError):
        OpenAIClient(model="   ", api_key="key")


def test_openai_client_rejects_empty_api_key() -> None:
    with pytest.raises(ValueError):
        OpenAIClient(model="gpt-4o", api_key="   ")


def test_openai_client_generate_plain_text(monkeypatch) -> None:
    body = json.dumps({"choices": [{"message": {"content": "hello world"}}]}).encode()
    monkeypatch.setattr("baps.models.request.urlopen", _make_fake_urlopen(body))
    client = OpenAIClient(model="gpt-4o", api_key="key")
    result = client.generate("say hello")
    assert result == "hello world"


def test_openai_client_generate_sends_correct_headers(monkeypatch) -> None:
    body = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
    captured: dict = {}
    monkeypatch.setattr("baps.models.request.urlopen", _make_capturing_urlopen(body, captured))
    client = OpenAIClient(model="gpt-4o", api_key="sk-openai-123", base_url="https://api.openai.com/v1")
    client.generate("prompt")
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["headers"].get("Authorization") == "Bearer sk-openai-123"


def test_openai_client_generate_with_schema_sends_json_schema_format(monkeypatch) -> None:
    output = '{"disposition": "accept", "rationale": "good"}'
    body = json.dumps({"choices": [{"message": {"content": output}}]}).encode()
    captured: dict = {}
    monkeypatch.setattr("baps.models.request.urlopen", _make_capturing_urlopen(body, captured))
    client = OpenAIClient(model="gpt-4o", api_key="key")
    schema = {"type": "object", "properties": {"disposition": {"type": "string"}}}
    result = client.generate("evaluate", format=schema)
    assert result == output
    rf = captured["body"]["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["schema"] == schema


def test_openai_client_generate_raises_on_http_error(monkeypatch) -> None:
    def fake_urlopen(req):
        fp = __import__("io").BytesIO(b'{"error": {"message": "invalid key"}}')
        raise error.HTTPError(req.full_url, 401, "Unauthorized", {}, fp)
    monkeypatch.setattr("baps.models.request.urlopen", fake_urlopen)
    client = OpenAIClient(model="gpt-4o", api_key="bad-key")
    with pytest.raises(RuntimeError, match="401"):
        client.generate("prompt")


def test_openai_client_generate_with_tools(monkeypatch) -> None:
    from baps.models import ToolDefinition
    args_json = json.dumps({"path": "src/x.py", "content": "pass"})
    body = json.dumps({
        "choices": [{"message": {"tool_calls": [{"function": {"name": "write_file", "arguments": args_json}}]}}]
    }).encode()
    captured: dict = {}
    monkeypatch.setattr("baps.models.request.urlopen", _make_capturing_urlopen(body, captured))
    client = OpenAIClient(model="gpt-4o", api_key="key")
    tools = [ToolDefinition(name="write_file", description="Write a file", parameters={"type": "object"})]
    result = client.generate_with_tools("write something", tools)
    assert result.name == "write_file"
    assert result.arguments == {"path": "src/x.py", "content": "pass"}
    assert captured["body"]["tool_choice"] == "required"


# ---------------------------------------------------------------------------
# FallbackClient
# ---------------------------------------------------------------------------

def test_fallback_client_rejects_empty_client_list() -> None:
    with pytest.raises(ValueError):
        FallbackClient([])


def test_fallback_client_returns_first_client_result_when_successful() -> None:
    primary = FakeModelClient(responses=["primary result"])
    secondary = FakeModelClient(responses=["secondary result"])
    client = FallbackClient([primary, secondary])
    assert client.generate("prompt") == "primary result"
    assert secondary.prompts == []


def test_fallback_client_falls_back_on_runtime_error() -> None:
    class FailingClient(ModelClient):
        def generate(self, prompt: str, format=None) -> str:
            raise RuntimeError("billing failure")

    secondary = FakeModelClient(responses=["fallback result"])
    client = FallbackClient([FailingClient(), secondary])
    assert client.generate("prompt") == "fallback result"


def test_fallback_client_raises_when_all_clients_fail() -> None:
    class FailingClient(ModelClient):
        def generate(self, prompt: str, format=None) -> str:
            raise RuntimeError("failure")

    client = FallbackClient([FailingClient(), FailingClient()])
    with pytest.raises(RuntimeError, match="all 2 fallback clients failed"):
        client.generate("prompt")


def test_fallback_client_does_not_fallback_on_value_error() -> None:
    class BadLogicClient(ModelClient):
        def generate(self, prompt: str, format=None) -> str:
            raise ValueError("model did not invoke any tool")

    secondary = FakeModelClient(responses=["should not reach"])
    client = FallbackClient([BadLogicClient(), secondary])
    with pytest.raises(ValueError, match="model did not invoke any tool"):
        client.generate("prompt")
    assert secondary.prompts == []


def test_fallback_client_generate_with_tools_falls_back_on_runtime_error() -> None:
    class FailingClient(ModelClient):
        def generate_with_tools(self, prompt: str, tools) -> ToolCall:
            raise RuntimeError("transport error")

    class SucceedingClient(ModelClient):
        def generate_with_tools(self, prompt: str, tools) -> ToolCall:
            return ToolCall(name="write_file", arguments={"path": "x.py"})

    client = FallbackClient([FailingClient(), SucceedingClient()])
    result = client.generate_with_tools("prompt", [])
    assert result.name == "write_file"


def test_fallback_client_generate_with_tools_does_not_fallback_on_value_error() -> None:
    class BadLogicClient(ModelClient):
        def generate_with_tools(self, prompt: str, tools) -> ToolCall:
            raise ValueError("model did not invoke any tool")

    class SucceedingClient(ModelClient):
        called = False
        def generate_with_tools(self, prompt: str, tools) -> ToolCall:
            SucceedingClient.called = True
            return ToolCall(name="write_file", arguments={})

    client = FallbackClient([BadLogicClient(), SucceedingClient()])
    with pytest.raises(ValueError):
        client.generate_with_tools("prompt", [])
    assert not SucceedingClient.called


def test_openai_client_generate_with_tools_raises_when_no_tool_called(monkeypatch) -> None:
    from baps.models import ToolDefinition
    body = json.dumps({"choices": [{"message": {"content": "I cannot help.", "tool_calls": []}}]}).encode()
    monkeypatch.setattr("baps.models.request.urlopen", _make_fake_urlopen(body))
    client = OpenAIClient(model="gpt-4o", api_key="key")
    tools = [ToolDefinition(name="write_file", description="Write", parameters={})]
    with pytest.raises(ValueError, match="tool"):
        client.generate_with_tools("do something", tools)


# ---------------------------------------------------------------------------
# generate_agentic — FakeModelClient
# ---------------------------------------------------------------------------

class _FakeExecutor:
    def __init__(self, results: dict[str, str] | None = None) -> None:
        self._results = results or {}
        self.calls: list[tuple[str, dict]] = []

    def execute(self, tool_name: str, arguments: dict) -> str:
        self.calls.append((tool_name, arguments))
        return self._results.get(tool_name, f"result_of_{tool_name}")


def test_fake_client_generate_agentic_no_sequences_returns_empty() -> None:
    client = FakeModelClient()
    executor = _FakeExecutor()
    text, records = client.generate_agentic("prompt", [], executor)
    assert text == ""
    assert records == []


def test_fake_client_generate_agentic_text_only_sequence() -> None:
    client = FakeModelClient(agentic_sequences=[["research complete"]])
    executor = _FakeExecutor()
    text, records = client.generate_agentic("prompt", [], executor)
    assert text == "research complete"
    assert records == []


def test_fake_client_generate_agentic_tool_then_text() -> None:
    tc = ToolCall(name="web_search", arguments={"query": "CVE-2024-1234"})
    client = FakeModelClient(agentic_sequences=[[tc, "found vulnerability info"]])
    executor = _FakeExecutor({"web_search": "CVE details here"})
    text, records = client.generate_agentic("prompt", [], executor, role_name="red")
    assert text == "found vulnerability info"
    assert len(records) == 1
    assert records[0].tool_name == "web_search"
    assert records[0].result == "CVE details here"
    assert records[0].role == "red"


def test_fake_client_generate_agentic_multiple_tool_calls() -> None:
    tc1 = ToolCall(name="web_search", arguments={"query": "q1"})
    tc2 = ToolCall(name="fetch_url", arguments={"url": "https://example.com"})
    client = FakeModelClient(agentic_sequences=[[tc1, tc2, "done"]])
    executor = _FakeExecutor({"web_search": "r1", "fetch_url": "r2"})
    text, records = client.generate_agentic("prompt", [], executor)
    assert text == "done"
    assert len(records) == 2
    assert records[0].tool_name == "web_search"
    assert records[1].tool_name == "fetch_url"


def test_fake_client_generate_agentic_executor_called_with_correct_args() -> None:
    tc = ToolCall(name="fetch_url", arguments={"url": "https://example.com/page"})
    client = FakeModelClient(agentic_sequences=[[tc, "done"]])
    executor = _FakeExecutor()
    client.generate_agentic("prompt", [], executor, role_name="blue")
    assert executor.calls == [("fetch_url", {"url": "https://example.com/page"})]


def test_fake_client_generate_agentic_sequence_ends_without_text_returns_empty_string() -> None:
    tc = ToolCall(name="web_search", arguments={"query": "q"})
    client = FakeModelClient(agentic_sequences=[[tc]])
    executor = _FakeExecutor()
    text, records = client.generate_agentic("prompt", [], executor)
    assert text == ""
    assert len(records) == 1


def test_fake_client_generate_agentic_multiple_sequences_consumed_in_order() -> None:
    client = FakeModelClient(agentic_sequences=[["first"], ["second"]])
    executor = _FakeExecutor()
    t1, _ = client.generate_agentic("p", [], executor)
    t2, _ = client.generate_agentic("p", [], executor)
    assert t1 == "first"
    assert t2 == "second"


def test_fake_client_generate_agentic_records_prompt() -> None:
    client = FakeModelClient(agentic_sequences=[["done"]])
    executor = _FakeExecutor()
    client.generate_agentic("my research prompt", [], executor)
    assert "my research prompt" in client.agentic_prompts


def test_fake_client_generate_agentic_rejects_empty_prompt() -> None:
    client = FakeModelClient(agentic_sequences=[["done"]])
    executor = _FakeExecutor()
    with pytest.raises(ValueError, match="non-empty"):
        client.generate_agentic("   ", [], executor)


# ---------------------------------------------------------------------------
# Role.generate_agentic
# ---------------------------------------------------------------------------

def test_role_generate_agentic_delegates_to_client() -> None:
    client = FakeModelClient(agentic_sequences=[["role result"]])
    executor = _FakeExecutor()
    role = Role(name="blue", client=client, schema=None, constrained=False)
    text, records = role.generate_agentic("prompt", [], executor)
    assert text == "role result"
    assert records == []


def test_role_generate_agentic_passes_role_name_to_records() -> None:
    tc = ToolCall(name="web_search", arguments={"query": "q"})
    client = FakeModelClient(agentic_sequences=[[tc, "done"]])
    executor = _FakeExecutor()
    role = Role(name="referee", client=client, schema=None, constrained=False)
    _, records = role.generate_agentic("prompt", [], executor)
    assert records[0].role == "referee"
