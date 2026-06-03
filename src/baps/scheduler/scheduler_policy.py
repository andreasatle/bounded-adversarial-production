"""EMA-scored softmax model selection policy with temperature decay for the adaptive scheduler."""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from baps.models.models import Backend
from baps.state.state import StopReason


@dataclass  # internal only — no serialization boundary
class ModelConfig:
    """Represent the ModelConfig type."""

    name: str  # short display name, used as key in policy state
    backend: Backend
    model_id: str  # the model string passed to the API


# Base reward by stop_reason. Verification result adds a bonus/penalty on top.
_STOP_REASON_BASE: dict[StopReason, float] = {
    StopReason.NO_STATE_CHANGE: 0.7,
    StopReason.ITERATION_LIMIT_REACHED: 0.5,
    StopReason.CREATE_GAME_NO_NEW_GAME: 0.6,
    StopReason.NORTHSTAR_UPDATE_PROPOSED: 0.4,
    StopReason.PLAY_GAME_NO_DELTA: 0.1,
    StopReason.ERROR: 0.2,  # transient failure; low but doesn't permanently tank score
}


def compute_reward(result: dict) -> float:
    """Map a run-result dict to a reward in [0, 1]."""
    stop_reason = result.get("stop_reason", "unknown")
    verification_passed = result.get("verification_passed")

    score = _STOP_REASON_BASE.get(stop_reason, 0.2)

    if verification_passed is True:
        score = min(1.0, score + 0.3)
    elif verification_passed is False:
        score = max(0.0, score - 0.2)

    return score


class _ModelStats(BaseModel):
    """Represent the _ModelStats type."""

    score: float = 0.5
    runs: int = 0


class ModelPolicy:
    """EMA-scored softmax selection with decaying temperature.

    Starts near-random (high temperature) and shifts toward exploitation as
    run count grows. Good models accumulate higher scores and get selected
    more often; bad ones decay and yield to stronger alternatives via
    escalation in the scheduler.
    """

    EMA_ALPHA: float = 0.3  # blend factor for score updates
    TEMP_INIT: float = 2.0  # starting temperature (exploration)
    TEMP_DECAY: float = 0.02  # temperature = TEMP_INIT / (1 + total_runs * TEMP_DECAY)

    def __init__(self, models: list[ModelConfig]) -> None:
        """Initialize the instance."""
        if not models:
            raise ValueError("model ladder must not be empty")
        self.models = list(models)
        self._stats: dict[str, _ModelStats] = {m.name: _ModelStats() for m in models}
        self.total_runs: int = 0

    @property
    def temperature(self) -> float:
        """Handle temperature."""
        return self.TEMP_INIT / (1 + self.total_runs * self.TEMP_DECAY)

    def select(self) -> ModelConfig:
        """Sample a model proportional to softmax(scores / temperature)."""
        T = self.temperature
        scores = [self._stats[m.name].score for m in self.models]
        logits = [s / T for s in scores]
        max_l = max(logits)
        exps = [math.exp(logit - max_l) for logit in logits]
        total = sum(exps)
        probs = [e / total for e in exps]
        r = random.random()
        cumul = 0.0
        for model, p in zip(self.models, probs):
            cumul += p
            if r <= cumul:
                return model
        return self.models[-1]

    def escalate_from(self, model: ModelConfig) -> ModelConfig | None:
        """Return the next stronger model, or None if already at the top."""
        idx = next((i for i, m in enumerate(self.models) if m.name == model.name), None)
        if idx is None or idx >= len(self.models) - 1:
            return None
        return self.models[idx + 1]

    def update(self, model_name: str, reward: float) -> None:
        """Update EMA score for a model given observed reward."""
        stats = self._stats.get(model_name)
        if stats is None:
            return
        stats.score = (1 - self.EMA_ALPHA) * stats.score + self.EMA_ALPHA * reward
        stats.score = max(0.0, min(1.0, stats.score))
        stats.runs += 1
        self.total_runs += 1

    def snapshot(self) -> dict[str, dict]:
        """Handle snapshot."""
        return {
            name: {"score": round(s.score, 4), "runs": s.runs}
            for name, s in self._stats.items()
        }

    def save(self, path: Path) -> None:
        """Handle save."""
        data = {"total_runs": self.total_runs, "stats": self.snapshot()}
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_stats(self, path: Path) -> None:
        """Load and return stats."""
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        self.total_runs = int(data.get("total_runs", 0))
        for name, s in data.get("stats", {}).items():
            if name in self._stats:
                self._stats[name] = _ModelStats(
                    score=float(s.get("score", 0.5)),
                    runs=int(s.get("runs", 0)),
                )
