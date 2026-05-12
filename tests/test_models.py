import pytest

from baps.models import FakeModelClient, ModelClient


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
