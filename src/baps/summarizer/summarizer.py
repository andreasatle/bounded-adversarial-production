"""Provides a caching SummarizationContext that summarizes artifact content via a model role."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from baps.models.models import Role
from baps.state.state import GameSpec


def _build_api_prompt(content: str) -> str:
    """Build a prompt asking the model to extract the public API surface of the given code."""
    return (
        "Extract the public API surface of this code — function/method signatures, "
        "doc comments, struct/class definitions (no bodies), test function names, and "
        "total line count. Return only the API surface as plain text.\n\n" + content
    )


def _build_objective_prompt(content: str, objective: str) -> str:
    """Build a prompt asking the model to summarize code relative to the given objective."""
    return (
        f"Given this code and the current objective: '{objective}', summarize what this "
        "code does and how it relates to the objective. Be concise.\n\n" + content
    )


@dataclass  # internal only — no serialization boundary
class SummarizationContext:
    """Holds a summarizer Role and a per-instance cache for deduplicating model calls."""

    summarizer: Role | None
    game_spec: GameSpec | None
    _cache: dict[str, str] = field(default_factory=dict, init=False)

    def summarize(self, content: str, objective: str | None) -> str | None:
        """Return a model-generated summary of content, using the cache to avoid redundant calls."""
        if self.summarizer is None:
            return None
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        if objective is None:
            cache_key = f"api:{content_hash}"
        else:
            objective_hash = hashlib.sha256(objective.encode()).hexdigest()
            cache_key = f"objective:{objective_hash}:{content_hash}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        prompt = _build_api_prompt(content) if objective is None else _build_objective_prompt(content, objective)
        result = self.summarizer.generate(prompt)
        self._cache[cache_key] = result
        return result
