"""Tests for client building, fallback chains, and backend resolution (baps.clients)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
import yaml

import baps.core.clients as _clients_module
from baps.core.run import create_state as _create_state
from baps.core.run_config import RunConfig
from baps.game.engine import create_game, play_game
from baps.models.models import (
    AnthropicClient,
    Backend,
    FakeModelClient,
    OllamaClient,
    OpenAIClient,
    ToolCall,
)
from baps.state.state import GameSpec

# Captured before autouse fixtures patch them — used by backend dispatch tests.
_real_build_model_client = _clients_module._build_model_client
_real_build_planner_model_client = _clients_module._build_planner_model_client
_realbuild_role_client = _clients_module.build_role_client
_realbuild_fallback_chain_for_role = _clients_module.build_fallback_chain_for_role
_real_build_fallback_client_for_role = _clients_module._build_fallback_client_for_role


def _make_run_config(**overrides) -> RunConfig:
    base = dict(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
        spec_path=None,
        spec_backend=None,
        spec_model=None,
        spec_roles={},
    )
    base.update(overrides)
    return RunConfig.model_validate(base)


def create_state(config: RunConfig | dict):
    return _create_state(config if isinstance(config, RunConfig) else RunConfig(**config))

    # ---------------------------------------------------------------------------
    # Backend dispatch tests
    # ---------------------------------------------------------------------------


def test_build_model_client_returns_ollama_by_default(monkeypatch) -> None:
    monkeypatch.delenv("BAPS_BACKEND", raising=False)
    monkeypatch.setenv("BAPS_OLLAMA_MODEL", "llama3.2")
    client = _real_build_model_client()
    assert isinstance(client, OllamaClient)
    assert client.model == "llama3.2"


def test_build_model_client_returns_anthropic_when_backend_set(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("BAPS_ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    client = _real_build_model_client()
    assert isinstance(client, AnthropicClient)
    assert client.model == "claude-haiku-4-5-20251001"
    assert client.api_key == "sk-ant-test"


def test_build_model_client_returns_openai_when_backend_set(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_BACKEND", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    monkeypatch.setenv("BAPS_OPENAI_MODEL", "gpt-4o-mini")
    client = _real_build_model_client()
    assert isinstance(client, OpenAIClient)
    assert client.model == "gpt-4o-mini"
    assert client.api_key == "sk-openai-test"


def test_build_client_anthropic_raises_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        _clients_module._build_client("anthropic", "claude-sonnet-4-6")


def test_build_client_openai_raises_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        _clients_module._build_client("openai", "gpt-4o")


def test_build_create_game_client_uses_cloud_client_without_planner_split(
    monkeypatch,
) -> None:
    monkeypatch.setenv("BAPS_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("BAPS_OLLAMA_PLANNER_MODEL", raising=False)
    client = _real_build_planner_model_client()
    assert isinstance(client, AnthropicClient)


def test_build_create_game_client_uses_ollama_planner_model_when_set(
    monkeypatch,
) -> None:
    monkeypatch.delenv("BAPS_BACKEND", raising=False)
    monkeypatch.setenv("BAPS_OLLAMA_PLANNER_MODEL", "mistral")
    monkeypatch.setenv("BAPS_OLLAMA_MODEL", "llama3.2")
    client = _real_build_planner_model_client()
    assert isinstance(client, OllamaClient)
    assert client.model == "mistral"


def test_build_create_game_client_falls_back_to_ollama_model_when_no_planner(
    monkeypatch,
) -> None:
    monkeypatch.delenv("BAPS_BACKEND", raising=False)
    monkeypatch.delenv("BAPS_OLLAMA_PLANNER_MODEL", raising=False)
    monkeypatch.setenv("BAPS_OLLAMA_MODEL", "llama3.2")
    client = _real_build_planner_model_client()
    assert isinstance(client, OllamaClient)
    assert client.model == "llama3.2"

    # --- build_role_client tests ---


def testbuild_role_client_falls_back_to_global_when_no_role_vars(monkeypatch) -> None:
    monkeypatch.delenv("BAPS_RED_BACKEND", raising=False)
    monkeypatch.delenv("BAPS_RED_MODEL", raising=False)
    monkeypatch.delenv("BAPS_BACKEND", raising=False)
    monkeypatch.setenv("BAPS_OLLAMA_MODEL", "llama3.2")
    # Restore the real _build_model_client so the fallback path exercises it,
    # not the FakeModelClient injected by the autouse fixture.
    monkeypatch.setattr("baps.core.clients._build_model_client", _real_build_model_client)
    client = _realbuild_role_client("red")
    assert isinstance(client, OllamaClient)
    assert client.model == "llama3.2"


def testbuild_role_client_uses_role_model_on_anthropic_backend(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_RED_BACKEND", "anthropic")
    monkeypatch.setenv("BAPS_RED_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client = _realbuild_role_client("red")
    assert isinstance(client, AnthropicClient)
    assert client.model == "claude-haiku-4-5-20251001"


def testbuild_role_client_uses_role_model_on_openai_backend(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_REFEREE_BACKEND", "openai")
    monkeypatch.setenv("BAPS_REFEREE_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    client = _realbuild_role_client("referee")
    assert isinstance(client, OpenAIClient)
    assert client.model == "gpt-4o-mini"


def testbuild_role_client_uses_role_model_on_ollama_backend(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_BLUE_BACKEND", "ollama")
    monkeypatch.setenv("BAPS_BLUE_MODEL", "gemma3:latest")
    client = _realbuild_role_client("blue")
    assert isinstance(client, OllamaClient)
    assert client.model == "gemma3:latest"


def testbuild_role_client_infers_backend_from_global_when_only_model_set(
    monkeypatch,
) -> None:
    monkeypatch.delenv("BAPS_RED_BACKEND", raising=False)
    monkeypatch.setenv("BAPS_RED_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.setenv("BAPS_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client = _realbuild_role_client("red")
    assert isinstance(client, AnthropicClient)
    assert client.model == "claude-haiku-4-5-20251001"


def testbuild_role_client_raises_on_anthropic_without_api_key(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_RED_BACKEND", "anthropic")
    monkeypatch.setenv("BAPS_RED_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        _realbuild_role_client("red")


def testbuild_role_client_raises_on_openai_without_api_key(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_REFEREE_BACKEND", "openai")
    monkeypatch.setenv("BAPS_REFEREE_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        _realbuild_role_client("referee")


def testbuild_role_client_uses_global_anthropic_model_when_only_backend_set(
    monkeypatch,
) -> None:
    monkeypatch.setenv("BAPS_BLUE_BACKEND", "anthropic")
    monkeypatch.delenv("BAPS_BLUE_MODEL", raising=False)
    monkeypatch.setenv("BAPS_ANTHROPIC_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client = _realbuild_role_client("blue")
    assert isinstance(client, AnthropicClient)
    assert client.model == "claude-sonnet-4-6"

    # --- resolve_backend_model / build_client_for_role tests ---


def testresolve_backend_model_spec_global_overrides_env(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_BACKEND", "ollama")
    monkeypatch.setenv("BAPS_OLLAMA_MODEL", "env-model")
    config = _make_run_config(spec_backend="ollama", spec_model="spec-model", spec_roles={})
    backend, model = _clients_module.resolve_backend_model("blue", config)
    assert backend == "ollama"
    assert model == "spec-model"


def testresolve_backend_model_role_spec_overrides_global_spec(monkeypatch) -> None:
    monkeypatch.delenv("BAPS_BACKEND", raising=False)
    config = _make_run_config(
        spec_backend="ollama",
        spec_model="global-model",
        spec_roles={"blue": {"backend": "ollama", "model": "role-model"}},
    )
    backend, model = _clients_module.resolve_backend_model("blue", config)
    assert model == "role-model"


def testresolve_backend_model_env_fallback_when_no_spec(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_BACKEND", "ollama")
    monkeypatch.setenv("BAPS_OLLAMA_MODEL", "env-model")
    config = _make_run_config(spec_backend=None, spec_model=None, spec_roles={})
    backend, model = _clients_module.resolve_backend_model("blue", config)
    assert backend == "ollama"
    assert model == "env-model"


def testresolve_backend_model_role_env_overrides_global_env(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_BACKEND", "ollama")
    monkeypatch.setenv("BAPS_OLLAMA_MODEL", "global-env")
    monkeypatch.setenv("BAPS_BLUE_BACKEND", "ollama")
    monkeypatch.setenv("BAPS_BLUE_MODEL", "role-env")
    config = _make_run_config(spec_backend=None, spec_model=None, spec_roles={})
    backend, model = _clients_module.resolve_backend_model("blue", config)
    assert model == "role-env"


def testresolve_backend_model_raises_when_nothing_configured(monkeypatch) -> None:
    for var in (
        "BAPS_BACKEND",
        "BAPS_OLLAMA_MODEL",
        "BAPS_ANTHROPIC_MODEL",
        "BAPS_OPENAI_MODEL",
        "BAPS_BLUE_BACKEND",
        "BAPS_BLUE_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    config = _make_run_config(spec_backend=None, spec_model=None, spec_roles={})
    with pytest.raises(ValueError, match="No model configured"):
        _clients_module.resolve_backend_model("blue", config)


def testresolve_backend_model_raises_on_unknown_backend(monkeypatch) -> None:
    del monkeypatch
    with pytest.raises(ValueError, match="Input should be 'anthropic', 'openai' or 'ollama'"):
        _make_run_config(spec_backend="bogus", spec_model="some-model", spec_roles={})


def testresolve_backend_model_role_spec_backend_only_falls_back_to_spec_model(
    monkeypatch,
) -> None:
    monkeypatch.delenv("BAPS_RED_MODEL", raising=False)
    config = _make_run_config(
        spec_backend="ollama",
        spec_model="global-model",
        spec_roles={"red": {"backend": "ollama"}},
    )
    backend, model = _clients_module.resolve_backend_model("red", config)
    assert backend == "ollama"
    assert model == "global-model"


def testbuild_client_for_role_constructs_ollama_client(monkeypatch) -> None:
    config = _make_run_config(
        spec_backend="ollama",
        spec_model="gemma4:e4b",
        spec_roles={},
    )
    client = _clients_module._build_client(  # bypass env
        *_clients_module.resolve_backend_model("blue", config)
    )
    assert isinstance(client, OllamaClient)
    assert client.model == "gemma4:e4b"


def test_build_client_constructs_anthropic_client(monkeypatch) -> None:
    # Test _build_client directly (not patched by autouse fixture).
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client = _clients_module._build_client("anthropic", "claude-haiku-4-5-20251001")
    assert isinstance(client, AnthropicClient)
    assert client.model == "claude-haiku-4-5-20251001"


def test_build_client_anthropic_raises_without_api_key_via_run(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        _clients_module._build_client("anthropic", "claude-sonnet-4-6")


def test_spec_backend_and_model_parsed_into_config(tmp_path: Path) -> None:
    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_markdown": "# Goal",
        "goal": "write",
        "output": "output/doc.md",
        "backend": "ollama",
        "model": "gemma4:e4b",
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path),
        workspace=None,
        artifact_id=None,
        goal=None,
        output=None,
        max_iterations=None,
        project_type=None,
        sandbox=None,
        command="start",
        language=None,
    )
    import baps.core.run as run_module

    config = run_module.resolve_run_config(args)
    assert config["spec_backend"] == Backend.OLLAMA
    assert config["spec_model"] == "gemma4:e4b"
    assert config["spec_roles"] == {}


def test_spec_roles_parsed_into_config(tmp_path: Path) -> None:
    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_markdown": "# Goal",
        "goal": "write",
        "output": "output/doc.md",
        "backend": "ollama",
        "model": "gemma4:e4b",
        "roles": {
            "blue": {"backend": "anthropic", "model": "claude-sonnet-4-6"},
            "decompose": {"backend": "ollama", "model": "gemma4:e4b"},
        },
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path),
        workspace=None,
        artifact_id=None,
        goal=None,
        output=None,
        max_iterations=None,
        project_type=None,
        sandbox=None,
        command="start",
        language=None,
    )
    import baps.core.run as run_module

    config = run_module.resolve_run_config(args)
    assert config.spec_roles["blue"]["backend"] == "anthropic"
    assert config.spec_roles["blue"]["model"] == "claude-sonnet-4-6"
    assert config.spec_roles["decompose"]["model"] == "gemma4:e4b"


def test_spec_backend_invalid_raises(tmp_path: Path) -> None:
    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_markdown": "# Goal",
        "goal": "write",
        "output": "output/doc.md",
        "backend": "bogus",
        "model": "whatever",
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path),
        workspace=None,
        artifact_id=None,
        goal=None,
        output=None,
        max_iterations=None,
        project_type=None,
        sandbox=None,
        command="start",
        language=None,
    )
    import baps.core.run as run_module

    with pytest.raises(ValueError, match="spec 'backend' must be one of"):
        run_module.resolve_run_config(args)


def test_spec_role_override_is_used_in_resolve(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_BACKEND", "ollama")
    monkeypatch.setenv("BAPS_OLLAMA_MODEL", "global-env")
    config = _make_run_config(
        spec_backend="ollama",
        spec_model="global-spec",
        spec_roles={"referee": {"backend": "ollama", "model": "referee-override"}},
    )
    backend, model = _clients_module.resolve_backend_model("referee", config)
    assert model == "referee-override"


def test_role_spec_backend_only_uses_spec_model_for_model(monkeypatch) -> None:
    config = _make_run_config(
        spec_backend="ollama",
        spec_model="fallback-model",
        spec_roles={"red": {"backend": "ollama"}},
    )
    _, model = _clients_module.resolve_backend_model("red", config)
    assert model == "fallback-model"

    # --- Model fallback/escalation tests ---


def test_spec_roles_parsed_with_fallback_config(tmp_path: Path) -> None:
    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_markdown": "# Goal",
        "goal": "write",
        "output": "output/doc.md",
        "backend": "ollama",
        "model": "gemma4:e4b",
        "roles": {
            "create_game": {
                "backend": "ollama",
                "model": "gemma4:e4b",
                "fallback": {"backend": "ollama", "model": "gemma4:26b"},
            },
        },
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path),
        workspace=None,
        artifact_id=None,
        goal=None,
        output=None,
        max_iterations=None,
        project_type=None,
        sandbox=None,
        command="start",
        language=None,
    )
    import baps.core.run as run_module

    config = run_module.resolve_run_config(args)
    role_cfg = config.spec_roles["create_game"]
    assert role_cfg["backend"] == "ollama"
    assert role_cfg["model"] == "gemma4:e4b"
    assert role_cfg.fallback is not None
    assert role_cfg.fallback["backend"] == "ollama"
    assert role_cfg.fallback["model"] == "gemma4:26b"


def test_spec_role_fallback_invalid_backend_raises(tmp_path: Path) -> None:
    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_markdown": "# Goal",
        "goal": "write",
        "output": "output/doc.md",
        "backend": "ollama",
        "model": "gemma4:e4b",
        "roles": {
            "create_game": {
                "backend": "ollama",
                "model": "gemma4:e4b",
                "fallback": {"backend": "bogus", "model": "some-model"},
            },
        },
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path),
        workspace=None,
        artifact_id=None,
        goal=None,
        output=None,
        max_iterations=None,
        project_type=None,
        sandbox=None,
        command="start",
        language=None,
    )
    import baps.core.run as run_module

    with pytest.raises(ValueError, match="roles.create_game.fallback.backend"):
        run_module.resolve_run_config(args)


def test_spec_role_fallback_non_mapping_raises(tmp_path: Path) -> None:
    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_markdown": "# Goal",
        "goal": "write",
        "output": "output/doc.md",
        "backend": "ollama",
        "model": "gemma4:e4b",
        "roles": {
            "create_game": {
                "backend": "ollama",
                "model": "gemma4:e4b",
                "fallback": "ollama",
            },
        },
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path),
        workspace=None,
        artifact_id=None,
        goal=None,
        output=None,
        max_iterations=None,
        project_type=None,
        sandbox=None,
        command="start",
        language=None,
    )
    import baps.core.run as run_module

    with pytest.raises(ValueError, match="roles.create_game.fallback.*must be a mapping"):
        run_module.resolve_run_config(args)


def test_build_fallback_client_for_role_returns_none_when_no_fallback() -> None:
    config = _make_run_config(spec_roles={"create_game": {"backend": "ollama", "model": "gemma4:e4b"}})
    result = _real_build_fallback_client_for_role("create_game", config)
    assert result is None


def test_build_fallback_client_for_role_returns_none_for_unconfigured_role() -> None:
    config = _make_run_config(spec_roles={})
    result = _real_build_fallback_client_for_role("create_game", config)
    assert result is None


def test_create_game_fallback_called_when_primary_exhausts_retries(monkeypatch) -> None:
    valid_response = (
        '{"kind":"game_spec","objective":"Advance goal","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"section exists"}'
    )
    fallback_client = FakeModelClient(responses=[valid_response])

    def _chain(role, cfg):
        del cfg
        return [("gemma4:26b", fallback_client)] if role == "create_game" else []

    monkeypatch.setattr("baps.game.engine.build_fallback_chain_for_role", _chain)
    monkeypatch.setattr("baps.game.engine.build_fallback_chain_for_role", _chain)

    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
        spec_roles={},
    )
    state = create_state(config)

    # Primary exhausts initial call + two retries before escalating to fallback.
    primary_client = FakeModelClient(responses=["not-json"] * 3)
    game_spec = create_game(config, state, model_client=primary_client)
    assert isinstance(game_spec, GameSpec)

    assert game_spec.target_artifact_id == "main-document"
    assert len(fallback_client.prompts) == 1


def test_create_game_fallback_not_called_when_primary_succeeds(monkeypatch) -> None:
    valid_response = (
        '{"kind":"game_spec","objective":"Advance goal","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"section exists"}'
    )
    fallback_client = FakeModelClient(responses=[valid_response])

    def _chain(role, cfg):
        del cfg
        return [("gemma4:26b", fallback_client)] if role == "create_game" else []

    monkeypatch.setattr("baps.game.engine.build_fallback_chain_for_role", _chain)
    monkeypatch.setattr("baps.game.engine.build_fallback_chain_for_role", _chain)

    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
        spec_roles={},
    )
    state = create_state(config)

    primary_client = FakeModelClient(responses=[valid_response])
    game_spec = create_game(config, state, model_client=primary_client)
    assert isinstance(game_spec, GameSpec)

    assert game_spec.target_artifact_id == "main-document"
    assert len(fallback_client.prompts) == 0


def test_play_game_red_fallback_called_when_primary_exhausts_retries(
    monkeypatch,
) -> None:

    valid_accept = '{"disposition":"accept","rationale":"looks good"}'
    fallback_red_client = FakeModelClient(responses=[valid_accept])

    def _chain(role, cfg):
        del cfg
        return [("gemma4:26b", fallback_red_client)] if role == "red" else []

    monkeypatch.setattr("baps.game.engine.build_fallback_chain_for_role", _chain)
    monkeypatch.setattr("baps.game.engine.build_fallback_chain_for_role", _chain)

    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
    )
    state = create_state(_make_run_config())

    blue_client = FakeModelClient(
        tool_responses=[
            ToolCall(
                name="append_section",
                arguments={
                    "artifact_id": "main-document",
                    "title": "Introduction",
                    "body": "Any objective",
                },
            )
        ]
    )
    referee_client = FakeModelClient(responses=[valid_accept])
    # Primary red exhausts initial call + two retries before escalating to fallback.
    primary_red_client = FakeModelClient(responses=["not-json"] * 3)

    result = play_game(
        state,
        spec,
        model_client=blue_client,
        red_model_client=primary_red_client,
        referee_model_client=referee_client,
        config=_make_run_config(spec_roles={}),
    )

    assert result is not None
    assert len(fallback_red_client.prompts) == 1


def test_play_game_referee_fallback_called_when_primary_exhausts_retries(
    monkeypatch,
) -> None:

    valid_accept = '{"disposition":"accept","rationale":"looks good"}'
    fallback_referee_client = FakeModelClient(responses=[valid_accept])

    def _chain(role, cfg):
        del cfg
        return [("gemma4:26b", fallback_referee_client)] if role == "referee" else []

    monkeypatch.setattr("baps.game.engine.build_fallback_chain_for_role", _chain)
    monkeypatch.setattr("baps.game.engine.build_fallback_chain_for_role", _chain)

    spec = GameSpec(
        objective="Any objective",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="PlayGame must return a valid DeltaDocumentState targeting main-document.",
    )
    state = create_state(_make_run_config())

    blue_client = FakeModelClient(
        tool_responses=[
            ToolCall(
                name="append_section",
                arguments={
                    "artifact_id": "main-document",
                    "title": "Introduction",
                    "body": "Any objective",
                },
            )
        ]
    )
    red_client = FakeModelClient(responses=[valid_accept])
    # Primary referee exhausts initial call + two retries before escalating to fallback.
    primary_referee_client = FakeModelClient(responses=["not-json"] * 3)

    result = play_game(
        state,
        spec,
        model_client=blue_client,
        red_model_client=red_client,
        referee_model_client=primary_referee_client,
        config=_make_run_config(spec_roles={}),
    )

    assert result is not None
    assert len(fallback_referee_client.prompts) == 1


def test_spec_roles_parsed_with_deep_fallback_chain(tmp_path: Path) -> None:
    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_markdown": "# Goal",
        "goal": "write",
        "output": "output/doc.md",
        "backend": "ollama",
        "model": "gemma4:e4b",
        "roles": {
            "create_game": {
                "backend": "ollama",
                "model": "gemma4:e4b",
                "fallback": {
                    "backend": "ollama",
                    "model": "gemma4:26b",
                    "fallback": {
                        "backend": "ollama",
                        "model": "gemma4:72b",
                    },
                },
            },
        },
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path),
        workspace=None,
        artifact_id=None,
        goal=None,
        output=None,
        max_iterations=None,
        project_type=None,
        sandbox=None,
        command="start",
        language=None,
    )
    import baps.core.run as run_module

    config = run_module.resolve_run_config(args)
    role_cfg = config.spec_roles["create_game"]
    assert role_cfg["model"] == "gemma4:e4b"
    assert role_cfg.fallback is not None
    assert role_cfg.fallback["model"] == "gemma4:26b"
    assert role_cfg.fallback.fallback is not None
    assert role_cfg.fallback.fallback["model"] == "gemma4:72b"


def test_spec_role_deep_fallback_invalid_backend_raises(tmp_path: Path) -> None:
    spec = {
        "project_type": "document",
        "artifact_id": "doc",
        "northstar_markdown": "# Goal",
        "goal": "write",
        "output": "output/doc.md",
        "backend": "ollama",
        "model": "gemma4:e4b",
        "roles": {
            "create_game": {
                "backend": "ollama",
                "model": "gemma4:e4b",
                "fallback": {
                    "backend": "ollama",
                    "model": "gemma4:26b",
                    "fallback": {
                        "backend": "bogus",
                        "model": "gemma4:72b",
                    },
                },
            },
        },
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.dump(spec))
    args = argparse.Namespace(
        spec=str(spec_path),
        workspace=None,
        artifact_id=None,
        goal=None,
        output=None,
        max_iterations=None,
        project_type=None,
        sandbox=None,
        command="start",
        language=None,
    )
    import baps.core.run as run_module

    with pytest.raises(ValueError, match="roles.create_game.fallback.fallback.backend"):
        run_module.resolve_run_config(args)


def testbuild_fallback_chain_for_role_returns_empty_when_no_fallback() -> None:
    config = _make_run_config(spec_roles={"create_game": {"backend": "ollama", "model": "gemma4:e4b"}})
    chain = _realbuild_fallback_chain_for_role("create_game", config)
    assert chain == []


def testbuild_fallback_chain_for_role_returns_empty_for_unconfigured_role() -> None:
    config = _make_run_config(spec_roles={})
    chain = _realbuild_fallback_chain_for_role("create_game", config)
    assert chain == []


def testbuild_fallback_chain_for_role_returns_single_entry_chain() -> None:
    config = _make_run_config(
        spec_roles={
            "create_game": {
                "backend": "ollama",
                "model": "gemma4:e4b",
                "fallback": {"backend": "ollama", "model": "gemma4:26b"},
            }
        }
    )
    chain = _realbuild_fallback_chain_for_role("create_game", config)
    assert len(chain) == 1
    assert chain[0][0] == "gemma4:26b"
    assert isinstance(chain[0][1], OllamaClient)


def testbuild_fallback_chain_for_role_returns_two_entry_chain() -> None:
    config = _make_run_config(
        spec_roles={
            "create_game": {
                "backend": "ollama",
                "model": "gemma4:e4b",
                "fallback": {
                    "backend": "ollama",
                    "model": "gemma4:26b",
                    "fallback": {"backend": "ollama", "model": "gemma4:72b"},
                },
            }
        }
    )
    chain = _realbuild_fallback_chain_for_role("create_game", config)
    assert len(chain) == 2
    assert chain[0][0] == "gemma4:26b"
    assert chain[1][0] == "gemma4:72b"
    assert isinstance(chain[0][1], OllamaClient)
    assert isinstance(chain[1][1], OllamaClient)


def test_create_game_fallback_chain_escalates_through_all_links(monkeypatch) -> None:
    valid_response = (
        '{"kind":"game_spec","objective":"Advance goal","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"section exists"}'
    )
    fail_client = FakeModelClient(responses=[])  # raises RuntimeError immediately
    success_client = FakeModelClient(responses=[valid_response])

    def _chain(role, cfg):
        del cfg
        return [("gemma4:26b", fail_client), ("gemma4:72b", success_client)] if role == "create_game" else []

    monkeypatch.setattr("baps.game.engine.build_fallback_chain_for_role", _chain)
    monkeypatch.setattr("baps.game.engine.build_fallback_chain_for_role", _chain)

    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
        spec_roles={},
    )
    state = create_state(config)

    primary_client = FakeModelClient(responses=["not-json"] * 3)
    game_spec = create_game(config, state, model_client=primary_client)
    assert isinstance(game_spec, GameSpec)

    assert game_spec.target_artifact_id == "main-document"
    assert len(fail_client.prompts) == 1  # called once, raised RuntimeError
    assert len(success_client.prompts) == 1  # called once, succeeded


def test_create_game_chain_exhaustion_raises_runtime_error(monkeypatch) -> None:
    fail_client1 = FakeModelClient(responses=[])
    fail_client2 = FakeModelClient(responses=[])

    def _chain(role, cfg):
        del cfg
        return [("gemma4:26b", fail_client1), ("gemma4:72b", fail_client2)] if role == "create_game" else []

    monkeypatch.setattr("baps.game.engine.build_fallback_chain_for_role", _chain)
    monkeypatch.setattr("baps.game.engine.build_fallback_chain_for_role", _chain)

    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
        spec_roles={},
    )
    state = create_state(config)

    primary_client = FakeModelClient(responses=["not-json"] * 3)
    with pytest.raises(RuntimeError, match="all models in fallback chain exhausted"):
        create_game(config, state, model_client=primary_client)


def test_no_fallback_behavior_unchanged_when_primary_succeeds(monkeypatch) -> None:
    valid_response = (
        '{"kind":"game_spec","objective":"Advance goal","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"section exists"}'
    )
    config = RunConfig(
        workspace=Path(".baps-workspace"),
        project_type="document",
        artifact_id="main-document",
        goal="Write a short report.",
        northstar_markdown="# Goal\n\nWrite a short report.",
        output_path=Path(".baps-workspace/output/report.md"),
        max_iterations=2,
        spec_roles={},
    )
    state = create_state(config)

    primary_client = FakeModelClient(responses=[valid_response])
    game_spec = create_game(config, state, model_client=primary_client)
    assert isinstance(game_spec, GameSpec)

    assert game_spec.target_artifact_id == "main-document"
    assert len(primary_client.prompts) == 1  # called once, no retries needed
