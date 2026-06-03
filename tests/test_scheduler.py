from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from baps.models.models import Backend
from baps.scheduler.scheduler import (
    _FLOOR_MIN_RUNS,
    _KNOWN_MODELS,
    _SCORE_FLOOR,
    _auto_ladder,
    _default_model_ladder,
    _drop_underperformers,
    _env_for_model,
)
from baps.scheduler.scheduler_policy import ModelConfig, ModelPolicy

# ---------------------------------------------------------------------------
# _env_for_model
# ---------------------------------------------------------------------------


def test_env_for_model_anthropic() -> None:
    model = ModelConfig("sonnet", Backend.ANTHROPIC, "claude-sonnet-4-6")
    env = _env_for_model(model)
    assert env["BAPS_BACKEND"] == "anthropic"
    assert env["BAPS_ANTHROPIC_MODEL"] == "claude-sonnet-4-6"


def test_env_for_model_openai() -> None:
    model = ModelConfig("gpt-4o", Backend.OPENAI, "gpt-4o")
    env = _env_for_model(model)
    assert env["BAPS_BACKEND"] == "openai"
    assert env["BAPS_OPENAI_MODEL"] == "gpt-4o"


def test_env_for_model_ollama() -> None:
    model = ModelConfig("llama3", Backend.OLLAMA, "llama3.1:8b")
    env = _env_for_model(model)
    assert env["BAPS_BACKEND"] == "ollama"
    assert env["BAPS_OLLAMA_MODEL"] == "llama3.1:8b"


def test_env_for_model_inherits_existing_env() -> None:
    with patch.dict(os.environ, {"MY_CUSTOM_VAR": "hello"}):
        env = _env_for_model(ModelConfig("sonnet", Backend.ANTHROPIC, "claude-sonnet-4-6"))
    assert env["MY_CUSTOM_VAR"] == "hello"


def test_env_for_model_does_not_mutate_os_environ() -> None:
    before = os.environ.copy()
    _env_for_model(ModelConfig("sonnet", Backend.ANTHROPIC, "claude-sonnet-4-6"))
    assert os.environ == before


# ---------------------------------------------------------------------------
# _auto_ladder
# ---------------------------------------------------------------------------


def test_auto_ladder_anthropic_only() -> None:
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "key"}, clear=True):
        ladder = _auto_ladder()
    names = [m.name for m in ladder]
    assert names == ["haiku", "sonnet", "opus"]


def test_auto_ladder_openai_only() -> None:
    with patch.dict(os.environ, {"OPENAI_API_KEY": "key"}, clear=True):
        ladder = _auto_ladder()
    names = [m.name for m in ladder]
    assert names == ["gpt-4o-mini", "gpt-4o"]


def test_auto_ladder_both_keys_includes_all() -> None:
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k1", "OPENAI_API_KEY": "k2"}, clear=True):
        ladder = _auto_ladder()
    names = [m.name for m in ladder]
    assert "haiku" in names and "gpt-4o" in names


def test_auto_ladder_falls_back_to_sonnet_when_no_keys() -> None:
    with patch.dict(os.environ, {}, clear=True):
        ladder = _auto_ladder()
    assert len(ladder) == 1
    assert ladder[0].name == "sonnet"


# ---------------------------------------------------------------------------
# _default_model_ladder
# ---------------------------------------------------------------------------


def test_default_model_ladder_reads_env_var() -> None:
    with patch.dict(os.environ, {"BAPS_MODEL_LADDER": "haiku,sonnet"}, clear=True):
        ladder = _default_model_ladder()
    assert [m.name for m in ladder] == ["haiku", "sonnet"]


def test_default_model_ladder_skips_unknown_names() -> None:
    with patch.dict(os.environ, {"BAPS_MODEL_LADDER": "haiku,does-not-exist,sonnet"}, clear=True):
        ladder = _default_model_ladder()
    names = [m.name for m in ladder]
    assert "does-not-exist" not in names
    assert "haiku" in names and "sonnet" in names


def test_default_model_ladder_falls_back_when_all_unknown() -> None:
    with patch.dict(
        os.environ,
        {"BAPS_MODEL_LADDER": "nonexistent", "ANTHROPIC_API_KEY": "k"},
        clear=True,
    ):
        ladder = _default_model_ladder()
    # falls back to _auto_ladder → anthropic models
    assert any(m.backend == Backend.ANTHROPIC for m in ladder)


def test_default_model_ladder_falls_back_when_env_empty() -> None:
    with patch.dict(os.environ, {"BAPS_MODEL_LADDER": ""}, clear=True):
        with patch(
            "baps.scheduler.scheduler._auto_ladder",
            return_value=[_KNOWN_MODELS["sonnet"]],
        ):
            ladder = _default_model_ladder()
    assert ladder[0].name == "sonnet"


# ---------------------------------------------------------------------------
# _drop_underperformers
# ---------------------------------------------------------------------------


def _policy_with_low_score(names: list[str], low_name: str) -> ModelPolicy:
    """Build a policy where low_name has been updated _FLOOR_MIN_RUNS times with reward=0."""
    policy = ModelPolicy([_KNOWN_MODELS[n] for n in names])
    for _ in range(_FLOOR_MIN_RUNS):
        policy.update(low_name, 0.0)
        for n in names:
            if n != low_name:
                policy.update(n, 1.0)
    return policy


def test_drop_underperformers_removes_low_scoring_model() -> None:
    policy = _policy_with_low_score(["haiku", "sonnet"], low_name="haiku")
    assert policy._stats["haiku"].score < _SCORE_FLOOR
    dropped = _drop_underperformers(policy)
    assert "haiku" in dropped
    assert [m.name for m in policy.models] == ["sonnet"]


def test_drop_underperformers_keeps_model_below_min_runs() -> None:
    policy = ModelPolicy([_KNOWN_MODELS["haiku"], _KNOWN_MODELS["sonnet"]])
    for _ in range(_FLOOR_MIN_RUNS - 1):
        policy.update("haiku", 0.0)
        policy.update("sonnet", 1.0)
    dropped = _drop_underperformers(policy)
    assert "haiku" not in dropped
    assert "haiku" in [m.name for m in policy.models]


def test_drop_underperformers_never_removes_last_model() -> None:
    policy = ModelPolicy([_KNOWN_MODELS["sonnet"]])
    for _ in range(_FLOOR_MIN_RUNS):
        policy.update("sonnet", 0.0)
    assert policy._stats["sonnet"].score < _SCORE_FLOOR
    dropped = _drop_underperformers(policy)
    assert dropped == []
    assert len(policy.models) == 1


def test_drop_underperformers_keeps_model_above_floor() -> None:
    policy = ModelPolicy([_KNOWN_MODELS["haiku"], _KNOWN_MODELS["sonnet"]])
    for _ in range(_FLOOR_MIN_RUNS):
        policy.update("haiku", 1.0)
        policy.update("sonnet", 1.0)
    dropped = _drop_underperformers(policy)
    assert dropped == []
    assert len(policy.models) == 2


def test_drop_underperformers_returns_empty_when_nothing_to_drop() -> None:
    policy = ModelPolicy([_KNOWN_MODELS["haiku"], _KNOWN_MODELS["sonnet"]])
    dropped = _drop_underperformers(policy)  # no runs yet
    assert dropped == []


# ---------------------------------------------------------------------------
# policy path validation (main)
# ---------------------------------------------------------------------------


def test_main_rejects_policy_path_outside_cwd(tmp_path: Path, monkeypatch) -> None:
    import sys

    outside = tmp_path / "policy.json"
    monkeypatch.setattr(sys, "argv", ["scheduler", "--policy", str(outside), "--rounds", "0"])
    with pytest.raises(SystemExit) as exc_info:
        from baps.scheduler.scheduler import main

        main()
    assert exc_info.value.code == 1


def test_main_accepts_policy_path_within_cwd(monkeypatch, tmp_path: Path) -> None:
    import sys

    policy_file = Path(".baps-test-scheduler-policy-tmp.json")
    monkeypatch.setattr(sys, "argv", ["scheduler", "--policy", str(policy_file), "--rounds", "0"])
    try:
        from baps.scheduler.scheduler import main

        main()  # should not exit(1)
    except SystemExit as e:
        pytest.fail(f"main() exited with code {e.code} for a valid policy path")
    finally:
        policy_file.unlink(missing_ok=True)
