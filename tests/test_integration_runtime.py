import inspect
from pathlib import Path

import pytest

from baps.adapters.document_adapter import DocumentProjectAdapter
from baps.game.engine import create_game
import baps.state.state as state_module


def test_create_state_output_flows_into_create_game(
    monkeypatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "flow-ws"
    import baps.core.run as run_module

    captured: dict[str, object] = {}
    original_create_game = create_game

    def _capturing_create_game(
        config,
        state,
        adapter=None,
        verification_result=None,
        context_chain=(),
        depth=0,
        **_kwargs,
    ):
        captured.setdefault("state", state)
        return original_create_game(
            config,
            state,
            adapter=adapter,
            verification_result=verification_result,
        )

    monkeypatch.setattr("baps.core.orchestration.create_game", _capturing_create_game)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
            "--goal",
            "Write a report.",
            "--output",
            "output/report.md",
        ],
    )

    run_module.main()

    forwarded_state = captured.get("state")
    assert forwarded_state is not None
    assert forwarded_state.model_dump(mode="json") == {
        "artifacts": [{"id": "main-document", "kind": "document", "sections": []}],
    }


def test_main_integration_uses_state_service_apply_delta(
    monkeypatch, tmp_path: Path
) -> None:
    from baps.state.state_service import StateService
    import baps.core.run as run_module

    called = {"value": False}
    original_apply = StateService.apply_delta

    def _capture_apply(self, delta):
        called["value"] = True
        return original_apply(self, delta)

    monkeypatch.setattr(StateService, "apply_delta", _capture_apply)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(tmp_path / "ws-service"),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
            "--goal",
            "Write a report.",
            "--output",
            "output/report.md",
        ],
    )
    run_module.main()
    assert called["value"] is True


def test_main_persists_updated_state_with_appended_section(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.core.run as run_module
    from baps.state.state_store import JsonStateStore

    workspace = tmp_path / "ws-persist"
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(workspace),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
            "--goal",
            "Write a report.",
            "--output",
            "output/report.md",
        ],
    )
    run_module.main()

    persisted = JsonStateStore(workspace / "state" / "state.json").load()
    doc = next(a for a in persisted.artifacts if a.id == "main-document")
    assert isinstance(doc, state_module.DocumentArtifact)
    assert len(doc.sections) == 2
    assert doc.sections[0].title == "Introduction"
    assert doc.sections[0].body == "Advance goal"


def test_main_unsupported_delta_operation_fails_explicitly(
    monkeypatch, capsys, caplog, tmp_path: Path
) -> None:
    import baps.core.run as run_module
    import logging

    monkeypatch.setattr(
        "baps.core.orchestration.play_game",
        lambda _state, _spec, adapter=None, verification_result=None, **_kwargs: (
            state_module.DeltaCodingState(
                artifact_id="main-document",
                operation="write_file",
                payload=state_module.WriteFileDelta(
                    file=state_module.CodeFile(path="foo.py", content="x")
                ),
            )
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(tmp_path / "ws-unsupported-op"),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
            "--goal",
            "Write a report.",
            "--output",
            "output/report.md",
        ],
    )
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
        run_module.main()
    assert exc.value.code == 2
    assert "DocumentArtifact does not support delta type" in caplog.text


def test_document_export_markdown_contains_sections_in_order(tmp_path: Path) -> None:

    adapter = DocumentProjectAdapter()
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.DocumentArtifact(
                id="main-document",
                sections=(
                    state_module.Section(title="Introduction", body="Intro body"),
                    state_module.Section(title="Conclusion", body="Conclusion body"),
                ),
            ),
        ),
    )
    output_path = tmp_path / "nested" / "out" / "report.md"
    changed = adapter.export_state(state, output_path, "main-document")
    assert changed is True
    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8") == (
        "## Introduction\n\nIntro body\n\n## Conclusion\n\nConclusion body"
    )


def test_document_export_creates_parent_directories(tmp_path: Path) -> None:

    adapter = DocumentProjectAdapter()
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(state_module.DocumentArtifact(id="main-document", sections=()),),
    )
    output_path = tmp_path / "a" / "b" / "c" / "report.md"
    adapter.export_state(state, output_path, "main-document")
    assert output_path.parent.exists()


def test_document_export_output_changed_false_when_unchanged(tmp_path: Path) -> None:

    adapter = DocumentProjectAdapter()
    state = state_module.State(
        northstar=state_module.NorthStar(artifacts=()),
        artifacts=(
            state_module.DocumentArtifact(
                id="main-document",
                sections=(state_module.Section(title="Intro", body="Body"),),
            ),
        ),
    )
    output_path = tmp_path / "out" / "report.md"
    first = adapter.export_state(state, output_path, "main-document")
    second = adapter.export_state(state, output_path, "main-document")
    assert first is True
    assert second is False


def test_document_export_lives_behind_adapter_not_main_orchestration() -> None:
    import baps.core.run as run_module
    import baps.adapters.document_adapter as doc_adapter_module

    main_src = inspect.getsource(run_module.main)
    assert "output_path.write_text" not in main_src
    assert "run_baps_loop(" not in main_src
    # write_text lives in export_document_artifact, not directly in export_state
    free_fn_src = inspect.getsource(doc_adapter_module.export_document_artifact)
    assert "write_text" in free_fn_src


def test_main_uses_project_type_adapter_dispatch_for_document(
    monkeypatch, tmp_path: Path
) -> None:
    import baps.core.run as run_module

    class _RecordingAdapter:
        project_type = "document"
        supported_delta_type = "DeltaDocumentState"

        def __init__(self) -> None:
            self.calls: list[str] = []
            self._delegate = DocumentProjectAdapter()

        def create_initial_state(self, config):
            self.calls.append("create_initial_state")
            return self._delegate.create_initial_state(config)

        def build_create_game_state_view(
            self, state, config, summarization_context=None
        ):
            self.calls.append("build_create_game_state_view")
            return self._delegate.build_create_game_state_view(
                state, config, summarization_context=summarization_context
            )

        def render_create_game_prompt_supplement(
            self, state, config, state_view, verification_result
        ):
            self.calls.append("render_create_game_prompt_supplement")
            return self._delegate.render_create_game_prompt_supplement(
                state, config, state_view, verification_result
            )

        def build_state_view(self, state, game_spec, summarization_context=None):
            self.calls.append("build_state_view")
            return self._delegate.build_state_view(
                state, game_spec, summarization_context=summarization_context
            )

        def render_blue_prompt(
            self, state_view, game_spec, attempt_number, previous_feedback
        ):
            self.calls.append("render_blue_prompt")
            return self._delegate.render_blue_prompt(
                state_view, game_spec, attempt_number, previous_feedback
            )

        def build_blue_output_format(self):
            self.calls.append("build_blue_output_format")
            return self._delegate.build_blue_output_format()

        def build_blue_tools(self):
            self.calls.append("build_blue_tools")
            return self._delegate.build_blue_tools()

        def tool_call_to_delta(self, tool_call):
            self.calls.append("tool_call_to_delta")
            return self._delegate.tool_call_to_delta(tool_call)

        def export_state(self, state, output_path, artifact_id):
            self.calls.append("export_state")
            return self._delegate.export_state(state, output_path, artifact_id)

    adapter = _RecordingAdapter()
    monkeypatch.setattr(
        "baps.core.runtime._resolve_project_type_adapter", lambda _ptype: adapter
    )
    monkeypatch.setattr(
        "baps.core.runtime.create_state",
        lambda _config: adapter.create_initial_state(_config.to_adapter_config()),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-run",
            "start",
            "--workspace",
            str(tmp_path / "ws-adapter-dispatch"),
            "--project-type",
            "document",
            "--artifact-id",
            "main-document",
            "--goal",
            "Write a report.",
            "--output",
            "output/report.md",
            "--max-iterations",
            "1",
        ],
    )
    run_module.main()
    assert "create_initial_state" in adapter.calls
    assert "build_create_game_state_view" in adapter.calls
    assert "render_create_game_prompt_supplement" in adapter.calls
    assert "build_state_view" in adapter.calls
    assert "render_blue_prompt" in adapter.calls
    assert "build_blue_tools" in adapter.calls
    assert "tool_call_to_delta" in adapter.calls
    assert "export_state" in adapter.calls


def test_adapter_registry_includes_document_and_coding() -> None:
    import baps.core.runtime as runtime_module

    adapters = runtime_module._build_project_type_adapters()
    assert "document" in adapters
    assert "coding" in adapters
