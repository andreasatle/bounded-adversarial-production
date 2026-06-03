"""Integration tests for summarizer wiring through the runtime and pipeline."""

from __future__ import annotations

from pathlib import Path

import baps.state.state as state_module
from baps.adapters.document_adapter import DocumentProjectAdapter
from baps.core.clients import parse_spec_roles
from baps.core.orchestration import run_project_iterations
from baps.core.parsers import NoNewGameError
from baps.core.roles import SpecRole
from baps.core.run_config import RoleConfig, RunConfig
from baps.core.runtime import (
    _initialize_project,
    _resolve_summarize_role,
    build_runtime,
)
from baps.models.models import Backend, FakeModelClient, Role
from baps.state.state import GameSpec, StopReason
from baps.summarizer.summarizer import SummarizationContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_document_config(workspace: Path) -> RunConfig:
    return RunConfig(
        workspace=workspace,
        project_type="document",
        artifact_id="main-document",
        northstar_markdown="# Goal\n\nWrite a report.",
        goal="Write a report.",
        output_path=workspace / "output" / "report.md",
        max_iterations=1,
    )


def _make_summarize_role() -> Role:
    return Role(name="summarize", client=FakeModelClient(["summary text"] * 20))

    # ---------------------------------------------------------------------------
    # SpecRole registration
    # ---------------------------------------------------------------------------


def test_summarize_role_name_accepted_byparse_spec_roles() -> None:
    """SpecRole.SUMMARIZE is in the valid roles set; parse_spec_roles must not raise."""
    result = parse_spec_roles(
        {
            "summarize": {"backend": "anthropic", "model": "claude-haiku-4-5-20251001"},
        }
    )
    assert "summarize" in result
    assert result["summarize"].backend == Backend.ANTHROPIC
    assert result["summarize"].model == "claude-haiku-4-5-20251001"


def test_summarize_is_valid_spec_role_member() -> None:
    assert SpecRole.SUMMARIZE == "summarize"
    assert SpecRole.SUMMARIZE in frozenset(SpecRole)

    # ---------------------------------------------------------------------------
    # _resolve_summarize_role / build_runtime wiring
    # ---------------------------------------------------------------------------


def test_resolve_summarize_role_returns_none_when_no_role_configured(
    tmp_path: Path,
) -> None:
    config = _make_document_config(tmp_path / "ws")
    role = _resolve_summarize_role(config)
    assert role is None


def test_resolve_summarize_role_returns_role_when_configured(
    monkeypatch, tmp_path: Path
) -> None:
    fake_client = FakeModelClient(["summary"])
    monkeypatch.setattr(
        "baps.core.runtime.build_client_for_role",
        lambda _role, _config: fake_client,
    )
    config = RunConfig(
        workspace=tmp_path / "ws",
        project_type="document",
        artifact_id="main-document",
        northstar_markdown="# Goal",
        goal="Write a report.",
        output_path=tmp_path / "output" / "report.md",
        max_iterations=1,
        spec_roles={
            "summarize": RoleConfig(
                backend=Backend.ANTHROPIC, model="claude-haiku-4-5-20251001"
            )
        },
    )
    role = _resolve_summarize_role(config)
    assert role is not None
    assert role.name == SpecRole.SUMMARIZE
    assert role.client is fake_client


def test_build_runtime_summarization_context_has_none_summarizer_without_role(
    tmp_path: Path,
) -> None:
    config = _make_document_config(tmp_path / "ws")
    rt = build_runtime(config)
    assert rt.summarization_context.summarizer is None


def test_build_runtime_summarization_context_has_summarizer_when_role_configured(
    monkeypatch, tmp_path: Path
) -> None:
    fake_client = FakeModelClient(["s"])
    monkeypatch.setattr(
        "baps.core.runtime.build_client_for_role",
        lambda _role, _config: fake_client,
    )
    config = RunConfig(
        workspace=tmp_path / "ws",
        project_type="document",
        artifact_id="main-document",
        northstar_markdown="# Goal",
        goal="Write a report.",
        output_path=tmp_path / "output" / "report.md",
        max_iterations=1,
        spec_roles={
            "summarize": RoleConfig(
                backend=Backend.ANTHROPIC, model="claude-haiku-4-5-20251001"
            )
        },
    )
    rt = build_runtime(config)
    assert rt.summarization_context.summarizer is not None
    assert rt.summarization_context.summarizer.client is fake_client

    # ---------------------------------------------------------------------------
    # Cache isolation across RuntimeContext instances
    # ---------------------------------------------------------------------------


def test_two_summarization_context_instances_have_independent_caches() -> None:
    """SummarizationContext._cache uses default_factory; each instance is independent."""
    ctx1 = SummarizationContext(summarizer=None, game_spec=None)
    ctx2 = SummarizationContext(summarizer=None, game_spec=None)
    assert ctx1._cache is not ctx2._cache


def test_two_build_runtime_calls_produce_independent_summarization_contexts(
    tmp_path: Path,
) -> None:
    config1 = _make_document_config(tmp_path / "ws1")
    config2 = _make_document_config(tmp_path / "ws2")
    rt1 = build_runtime(config1)
    rt2 = build_runtime(config2)
    assert rt1.summarization_context is not rt2.summarization_context
    assert rt1.summarization_context._cache is not rt2.summarization_context._cache

    # ---------------------------------------------------------------------------
    # summarization_context threads through to play_game
    # ---------------------------------------------------------------------------


def test_summarization_context_is_passed_to_play_game(
    monkeypatch, tmp_path: Path
) -> None:
    """run_project_iterations must forward summarization_context to play_game."""
    captured: dict[str, object] = {}

    _cg1: dict[str, int] = {"n": 0}

    def _mock_create_game1(
        _config,
        _state,
        adapter=None,
        verification_result=None,
        context_chain=(),
        depth=0,
        **_kw,
    ):
        _cg1["n"] += 1
        if _cg1["n"] > 1:
            raise NoNewGameError("done")
        return GameSpec(
            objective="Write intro",
            target_artifact_id="main-document",
            allowed_delta_type="DeltaDocumentState",
            success_condition="section added",
        )

    monkeypatch.setattr("baps.core.orchestration.create_game", _mock_create_game1)

    def _capturing_play_game(_state, _spec, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr("baps.core.orchestration.play_game", _capturing_play_game)

    config = RunConfig(
        workspace=tmp_path / "ws",
        project_type="document",
        artifact_id="main-document",
        northstar_markdown="# Goal",
        goal="Write something",
        output_path=tmp_path / "output" / "report.md",
        max_iterations=1,
    )
    service, state = _initialize_project(config)
    adapter = DocumentProjectAdapter()
    summarize_role = _make_summarize_role()
    ctx = SummarizationContext(summarizer=summarize_role, game_spec=None)

    run_project_iterations(config, adapter, service, state, summarization_context=ctx)

    assert "summarization_context" in captured
    assert captured["summarization_context"] is ctx


def test_summarization_context_none_is_passed_to_play_game_when_not_provided(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    _cg2: dict[str, int] = {"n": 0}

    def _mock_create_game2(_config, _state, **_kw):
        _cg2["n"] += 1
        if _cg2["n"] > 1:
            raise NoNewGameError("done")
        return GameSpec(
            objective="Write something",
            target_artifact_id="main-document",
            allowed_delta_type="DeltaDocumentState",
            success_condition="done",
        )

    monkeypatch.setattr("baps.core.orchestration.create_game", _mock_create_game2)

    def _capturing_play_game(_state, _spec, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr("baps.core.orchestration.play_game", _capturing_play_game)

    config = RunConfig(
        workspace=tmp_path / "ws-none",
        project_type="document",
        artifact_id="main-document",
        northstar_markdown="# Goal",
        goal="Write something",
        output_path=tmp_path / "output" / "report.md",
        max_iterations=1,
    )
    service, state = _initialize_project(config)
    adapter = DocumentProjectAdapter()

    run_project_iterations(config, adapter, service, state)

    # summarization_context kwarg is present and is None when not supplied
    assert "summarization_context" in captured
    assert captured["summarization_context"] is None

    # ---------------------------------------------------------------------------
    # Stop conditions transparent to summarizer
    # ---------------------------------------------------------------------------


def test_stop_reason_same_with_and_without_summarizer(
    monkeypatch, tmp_path: Path
) -> None:
    """Summarizer is transparent to orchestration stop logic."""

    def _no_new_game(*_args, **_kwargs):
        raise NoNewGameError("nothing to do")

    monkeypatch.setattr("baps.core.orchestration.create_game", _no_new_game)

    def _run(workspace: Path, ctx: SummarizationContext | None) -> StopReason:
        config = RunConfig(
            workspace=workspace,
            project_type="document",
            artifact_id="main-document",
            northstar_markdown="# Goal",
            goal="Write something",
            output_path=workspace / "output" / "report.md",
            max_iterations=2,
        )
        service, state = _initialize_project(config)
        result = run_project_iterations(
            config,
            DocumentProjectAdapter(),
            service,
            state,
            summarization_context=ctx,
        )
        return result.stop_reason

    reason_without = _run(tmp_path / "ws-no-sum", None)
    reason_with = _run(
        tmp_path / "ws-with-sum",
        SummarizationContext(summarizer=_make_summarize_role(), game_spec=None),
    )

    assert reason_without == StopReason.CREATE_GAME_NO_NEW_GAME
    assert reason_with == StopReason.CREATE_GAME_NO_NEW_GAME

    # ---------------------------------------------------------------------------
    # Summaries appear in StateViews when summarizer is configured
    # ---------------------------------------------------------------------------


def test_summaries_appear_in_state_view_when_summarizer_configured() -> None:
    """build_state_view with a non-None summarizer and target_entity produces summaries."""
    from baps.adapters.document_adapter import DocumentProjectAdapter

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.DocumentArtifact(
                id="main-document",
                sections=(
                    state_module.Section(title="Target", body="Target section body."),
                    state_module.Section(title="Other", body="Other section body."),
                ),
            ),
        ),
    )
    spec = GameSpec(
        objective="Update Target section",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="Target section updated",
        target_entity="Target",
    )
    ctx = SummarizationContext(
        summarizer=Role(name="summarize", client=FakeModelClient(["summarized other"])),
        game_spec=spec,
    )

    view = DocumentProjectAdapter().build_state_view(
        state, spec, summarization_context=ctx
    )

    assert "### Target [full]" in view.content
    assert "Target section body." in view.content
    assert "### Other [summary]" in view.content
    assert "summarized other" in view.content
    assert "Other section body." not in view.content


def test_no_summaries_when_summarizer_is_none_even_with_target_entity() -> None:
    """When SummarizationContext has summarizer=None, all sections render in full."""
    from baps.adapters.document_adapter import DocumentProjectAdapter

    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.DocumentArtifact(
                id="main-document",
                sections=(
                    state_module.Section(title="Target", body="Target body."),
                    state_module.Section(title="Other", body="Other body."),
                ),
            ),
        ),
    )
    spec = GameSpec(
        objective="Update Target",
        target_artifact_id="main-document",
        allowed_delta_type="DeltaDocumentState",
        success_condition="done",
        target_entity="Target",
    )
    ctx = SummarizationContext(summarizer=None, game_spec=spec)

    view = DocumentProjectAdapter().build_state_view(
        state, spec, summarization_context=ctx
    )

    assert "[summary]" not in view.content
    assert "Target body." in view.content
    assert "Other body." in view.content
