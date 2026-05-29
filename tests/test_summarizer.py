"""Unit tests for SummarizationContext."""
from __future__ import annotations

from baps.models.models import FakeModelClient, Role
from baps.summarizer.summarizer import (
    SummarizationContext,
    _build_api_prompt,
    _build_objective_prompt,
)


def _make_role(responses: list[str]) -> Role:
    return Role(name="summarize", client=FakeModelClient(responses))


def test_summarize_returns_none_when_summarizer_is_none() -> None:
    ctx = SummarizationContext(summarizer=None, game_spec=None)
    assert ctx.summarize("def foo(): pass\n", objective=None) is None


def test_summarize_returns_none_when_summarizer_is_none_with_objective() -> None:
    ctx = SummarizationContext(summarizer=None, game_spec=None)
    assert ctx.summarize("x = 1\n", objective="fix something") is None


def test_summarize_calls_api_prompt_when_objective_is_none() -> None:
    content = "def foo(): pass\n"
    role = _make_role(["API: def foo(): pass"])
    ctx = SummarizationContext(summarizer=role, game_spec=None)

    result = ctx.summarize(content, objective=None)

    assert result == "API: def foo(): pass"
    assert len(role.client.prompts) == 1
    # Role wraps the prompt; verify the API-surface instruction and content appear in it
    sent = role.client.prompts[0]
    assert "Extract the public API surface" in sent
    assert content in sent


def test_summarize_calls_objective_prompt_when_objective_provided() -> None:
    content = "def bar(): pass\n"
    objective = "Implement bar"
    role = _make_role(["objective summary text"])
    ctx = SummarizationContext(summarizer=role, game_spec=None)

    result = ctx.summarize(content, objective=objective)

    assert result == "objective summary text"
    assert len(role.client.prompts) == 1
    sent = role.client.prompts[0]
    assert objective in sent
    assert content in sent
    assert "Extract the public API surface" not in sent


def test_summarize_cache_hit_second_call_does_not_call_model() -> None:
    content = "x = 1\n"
    role = _make_role(["cached result"])  # only one response — second call would raise
    ctx = SummarizationContext(summarizer=role, game_spec=None)

    r1 = ctx.summarize(content, objective=None)
    r2 = ctx.summarize(content, objective=None)

    assert r1 == "cached result"
    assert r2 == "cached result"
    assert len(role.client.prompts) == 1


def test_summarize_cache_hit_preserves_exact_result() -> None:
    content = "y = 2\n"
    role = _make_role(["first and only"])
    ctx = SummarizationContext(summarizer=role, game_spec=None)

    ctx.summarize(content, objective="obj")
    r2 = ctx.summarize(content, objective="obj")

    assert r2 == "first and only"
    assert len(role.client.prompts) == 1


def test_summarize_cache_miss_different_content_calls_model_again() -> None:
    role = _make_role(["summary-A", "summary-B"])
    ctx = SummarizationContext(summarizer=role, game_spec=None)

    r1 = ctx.summarize("content A", objective=None)
    r2 = ctx.summarize("content B", objective=None)

    assert r1 == "summary-A"
    assert r2 == "summary-B"
    assert len(role.client.prompts) == 2


def test_summarize_cache_miss_same_content_different_objective_calls_model_again() -> None:
    content = "def baz(): pass\n"
    role = _make_role(["summary-obj1", "summary-obj2"])
    ctx = SummarizationContext(summarizer=role, game_spec=None)

    r1 = ctx.summarize(content, objective="objective one")
    r2 = ctx.summarize(content, objective="objective two")

    assert r1 == "summary-obj1"
    assert r2 == "summary-obj2"
    assert len(role.client.prompts) == 2


def test_cache_key_includes_objective_not_just_content() -> None:
    """Verify (content, obj=None) and (content, obj='X') are separate cache entries."""
    content = "def fn(): pass\n"
    role = _make_role(["no-obj-summary", "with-obj-summary"])
    ctx = SummarizationContext(summarizer=role, game_spec=None)

    r_no_obj = ctx.summarize(content, objective=None)
    r_with_obj = ctx.summarize(content, objective="some objective")

    assert r_no_obj == "no-obj-summary"
    assert r_with_obj == "with-obj-summary"
    assert len(role.client.prompts) == 2

    # A third call with the same objective hits the cache — no new model call
    r_cached = ctx.summarize(content, objective="some objective")
    assert r_cached == "with-obj-summary"
    assert len(role.client.prompts) == 2


def test_two_context_instances_have_independent_caches() -> None:
    """Each SummarizationContext instance owns its own cache dict."""
    ctx1 = SummarizationContext(summarizer=None, game_spec=None)
    ctx2 = SummarizationContext(summarizer=None, game_spec=None)
    assert ctx1._cache is not ctx2._cache


def test_cache_populated_by_first_ctx_not_visible_in_second_ctx() -> None:
    content = "z = 3\n"
    role1 = _make_role(["result-from-ctx1"])
    role2 = _make_role(["result-from-ctx2"])
    ctx1 = SummarizationContext(summarizer=role1, game_spec=None)
    ctx2 = SummarizationContext(summarizer=role2, game_spec=None)

    ctx1.summarize(content, objective=None)
    # ctx2 must call its own model, not use ctx1's cache
    r2 = ctx2.summarize(content, objective=None)

    assert r2 == "result-from-ctx2"
    assert len(role2.client.prompts) == 1
