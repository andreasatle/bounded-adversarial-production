from __future__ import annotations

import json
from pathlib import Path

import pytest

from baps.models.models import Backend
from baps.scheduler.scheduler_policy import ModelConfig, ModelPolicy, compute_reward


# ---------------------------------------------------------------------------
# compute_reward
# ---------------------------------------------------------------------------


def test_reward_no_state_change_with_passing_verification() -> None:
    result = {"stop_reason": "no_state_change", "verification_passed": True}
    assert compute_reward(result) == pytest.approx(1.0)


def test_reward_no_state_change_with_failing_verification() -> None:
    result = {"stop_reason": "no_state_change", "verification_passed": False}
    assert compute_reward(result) == pytest.approx(0.5)


def test_reward_no_state_change_no_verification() -> None:
    result = {"stop_reason": "no_state_change", "verification_passed": None}
    assert compute_reward(result) == pytest.approx(0.7)


def test_reward_iteration_limit_with_passing_verification() -> None:
    result = {"stop_reason": "iteration_limit_reached", "verification_passed": True}
    assert compute_reward(result) == pytest.approx(0.8)


def test_reward_iteration_limit_with_failing_verification() -> None:
    result = {"stop_reason": "iteration_limit_reached", "verification_passed": False}
    assert compute_reward(result) == pytest.approx(0.3)


def test_reward_play_game_no_delta() -> None:
    result = {"stop_reason": "play_game_no_delta", "verification_passed": None}
    assert compute_reward(result) == pytest.approx(0.1)


def test_reward_play_game_no_delta_clamped_to_zero_on_failing_verification() -> None:
    result = {"stop_reason": "play_game_no_delta", "verification_passed": False}
    assert compute_reward(result) == pytest.approx(0.0)


def test_reward_create_game_no_new_game() -> None:
    result = {"stop_reason": "create_game_no_new_game", "verification_passed": None}
    assert compute_reward(result) == pytest.approx(0.6)


def test_reward_unknown_stop_reason() -> None:
    result = {"stop_reason": "totally_unknown", "verification_passed": None}
    assert 0.0 <= compute_reward(result) <= 1.0


def test_reward_missing_fields_does_not_raise() -> None:
    assert 0.0 <= compute_reward({}) <= 1.0


# ---------------------------------------------------------------------------
# ModelPolicy construction
# ---------------------------------------------------------------------------


def _two_models() -> list[ModelConfig]:
    return [
        ModelConfig("cheap", Backend.ANTHROPIC, "claude-haiku-4-5-20251001"),
        ModelConfig("strong", Backend.ANTHROPIC, "claude-sonnet-4-6"),
    ]


def test_policy_requires_non_empty_ladder() -> None:
    with pytest.raises(ValueError):
        ModelPolicy([])


def test_policy_initial_scores_are_neutral() -> None:
    policy = ModelPolicy(_two_models())
    snap = policy.snapshot()
    assert snap["cheap"]["score"] == pytest.approx(0.5)
    assert snap["strong"]["score"] == pytest.approx(0.5)
    assert snap["cheap"]["runs"] == 0


# ---------------------------------------------------------------------------
# ModelPolicy.select
# ---------------------------------------------------------------------------


def test_policy_select_returns_a_model_from_the_ladder() -> None:
    policy = ModelPolicy(_two_models())
    selected = policy.select()
    assert selected.name in {"cheap", "strong"}


def test_policy_select_favors_higher_scored_model() -> None:
    policy = ModelPolicy(_two_models())
    policy._stats["cheap"].score = 0.9
    policy._stats["strong"].score = 0.1
    # Simulate past runs to lower temperature so score difference has real effect.
    policy.total_runs = 200
    wins = sum(1 for _ in range(400) if policy.select().name == "cheap")
    assert wins > 300


def test_policy_select_is_uniform_at_equal_scores() -> None:
    policy = ModelPolicy(_two_models())
    # Both at 0.5 — should be roughly 50/50 over many draws.
    wins = sum(1 for _ in range(500) if policy.select().name == "cheap")
    assert 175 < wins < 325


# ---------------------------------------------------------------------------
# ModelPolicy.update (EMA)
# ---------------------------------------------------------------------------


def test_policy_update_increases_score_on_high_reward() -> None:
    policy = ModelPolicy(_two_models())
    before = policy._stats["cheap"].score
    policy.update("cheap", 1.0)
    assert policy._stats["cheap"].score > before


def test_policy_update_decreases_score_on_zero_reward() -> None:
    policy = ModelPolicy(_two_models())
    before = policy._stats["cheap"].score
    policy.update("cheap", 0.0)
    assert policy._stats["cheap"].score < before


def test_policy_update_increments_runs() -> None:
    policy = ModelPolicy(_two_models())
    policy.update("cheap", 0.8)
    policy.update("cheap", 0.8)
    assert policy._stats["cheap"].runs == 2
    assert policy.total_runs == 2


def test_policy_update_clamps_score_to_unit_interval() -> None:
    policy = ModelPolicy(_two_models())
    policy._stats["cheap"].score = 0.95
    for _ in range(20):
        policy.update("cheap", 1.0)
    assert policy._stats["cheap"].score <= 1.0

    policy._stats["cheap"].score = 0.05
    for _ in range(20):
        policy.update("cheap", 0.0)
    assert policy._stats["cheap"].score >= 0.0


def test_policy_update_ignores_unknown_model() -> None:
    policy = ModelPolicy(_two_models())
    policy.update("nonexistent", 1.0)
    assert policy.total_runs == 0


# ---------------------------------------------------------------------------
# ModelPolicy.escalate_from
# ---------------------------------------------------------------------------


def test_escalate_from_returns_next_model() -> None:
    policy = ModelPolicy(_two_models())
    result = policy.escalate_from(policy.models[0])
    assert result is not None
    assert result.name == "strong"


def test_escalate_from_top_returns_none() -> None:
    policy = ModelPolicy(_two_models())
    assert policy.escalate_from(policy.models[-1]) is None


# ---------------------------------------------------------------------------
# ModelPolicy.temperature
# ---------------------------------------------------------------------------


def test_temperature_decreases_with_runs() -> None:
    policy = ModelPolicy(_two_models())
    t0 = policy.temperature
    for _ in range(10):
        policy.update("cheap", 0.5)
    assert policy.temperature < t0


# ---------------------------------------------------------------------------
# ModelPolicy.save / load_stats
# ---------------------------------------------------------------------------


def test_policy_save_and_load_roundtrip(tmp_path: Path) -> None:
    policy = ModelPolicy(_two_models())
    policy.update("cheap", 0.9)
    policy.update("strong", 0.3)
    path = tmp_path / "policy.json"
    policy.save(path)

    policy2 = ModelPolicy(_two_models())
    policy2.load_stats(path)
    assert policy2.total_runs == 2
    assert policy2._stats["cheap"].runs == 1
    snap = policy2.snapshot()
    assert snap["cheap"]["score"] == pytest.approx(
        policy._stats["cheap"].score, abs=1e-4
    )


def test_policy_load_stats_no_op_when_file_missing(tmp_path: Path) -> None:
    policy = ModelPolicy(_two_models())
    policy.load_stats(tmp_path / "nonexistent.json")
    assert policy.total_runs == 0


def test_policy_load_ignores_unknown_model_names(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "total_runs": 5,
                "stats": {"ghost": {"score": 0.9, "runs": 5}},
            }
        ),
        encoding="utf-8",
    )
    policy = ModelPolicy(_two_models())
    policy.load_stats(path)
    assert policy.total_runs == 5
    assert policy._stats["cheap"].score == pytest.approx(0.5)
