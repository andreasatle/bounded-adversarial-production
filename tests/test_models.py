import json
from urllib import error

import pytest

from baps.models import FakeModelClient, ModelClient, OllamaClient


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
