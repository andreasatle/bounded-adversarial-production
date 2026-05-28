from __future__ import annotations

import json
import subprocess
from pathlib import Path

from baps.adapters.project_adapter import (
    VerificationResult,
    _config_artifact_id,
    _verification_result_to_dict,
)
from baps.adapters.coding.common import (
    _config_language,
    _plugin_for,
    _validate_file_path,
    coding_artifact_from_state,
)
from baps.adapters.coding.delta_apply import _apply_delta_to_files, _normalize_coding_export_content
from baps.adapters.coding.parsing import (
    _validate_coding_write_file_artifact_purity,
    _validate_coding_write_files_purity,
    parse_coding_delta_json,
)
from baps.adapters.coding.prompting import (
    _render_coding_evaluation_supplement,
    _truncate_lines,
    render_coding_blue_prompt,
)
from baps.adapters.coding.state_updates import derive_coding_state_update_from_delta
from baps.adapters.coding.views import build_coding_create_game_state_view, build_coding_state_view
from baps.models.models import ToolCall, ToolDefinition
from baps.northstar.northstar_projection import StateView
from baps.state.state import (
    CodingArtifact,
    DeltaCodingBatchState,
    DeltaCodingState,
    DeltaDeleteCodingState,
    DeltaState,
    GameSpec,
    State,
    StateUpdateProposal,
)

__all__ = [
    "CodingProjectAdapter",
    "_apply_delta_to_files",
    "_truncate_lines",
    "build_coding_create_game_state_view",
    "build_coding_state_view",
    "coding_artifact_from_state",
    "derive_coding_state_update_from_delta",
    "parse_coding_delta_json",
    "render_coding_blue_prompt",
]


class CodingProjectAdapter:
    project_type = "coding"
    supported_delta_type = "DeltaCodingState"

    def create_initial_state(self, config: dict[str, object]) -> State:
        language = _config_language(config)
        _plugin_for(language)
        return State(
            artifacts=(CodingArtifact(id=_config_artifact_id(config), language=language, files=()),),
        )

    def build_create_game_state_view(self, state: State, config: dict[str, object]) -> StateView:
        return build_coding_create_game_state_view(state, config)

    def render_create_game_prompt_supplement(
        self,
        state: State,
        config: dict[str, object],
        state_view: StateView,
        verification_result: VerificationResult | None,
    ) -> str:
        base = (
            "Coding CreateGame constraints:\n"
            "- Blue can write one or more files per game using write_files (preferred) or write_file.\n"
            "- Group logically related files (e.g. a module and its tests) into one GameSpec.\n"
            "- File paths must be derived from the NorthStar spec, not invented.\n"
            "- Prefer production files under src/ before writing test files.\n"
        )
        if verification_result is None:
            del state, config, state_view
            return base
        verification_json = json.dumps(_verification_result_to_dict(verification_result), sort_keys=True)
        exit_code = verification_result.exit_code
        if exit_code == 5:
            no_tests_hint = (
                "- exit_code=5 means pytest collected zero tests: no test file exists yet.\n"
                "  Choose a game that WRITES the missing test file. Do NOT rewrite src.\n"
            )
        elif exit_code == 1:
            no_tests_hint = (
                "- exit_code=1 means tests were found but failed.\n"
                "  Prefer a repair game that fixes the failing implementation or test.\n"
            )
        else:
            no_tests_hint = ""
        del state, config, state_view
        return (
            f"{base}"
            "Coding CreateGame verification evidence:\n"
            f"- previous_verification_result_json: {verification_json}\n"
            "- Use this as evidence from the previous exported state only.\n"
            f"{no_tests_hint}"
            "- If evidence shows import/layout errors, prefer a repair game that fixes import/layout.\n"
        )

    def normalize_game_spec(
        self, game_spec: GameSpec, state: State, config: dict[str, object]
    ) -> GameSpec:
        del state
        configured_artifact_id = _config_artifact_id(config)
        return GameSpec(
            objective=game_spec.objective,
            target_artifact_id=configured_artifact_id,
            allowed_delta_type=game_spec.allowed_delta_type,
            success_condition=game_spec.success_condition,
        )

    def build_state_view(self, state: State, game_spec: GameSpec) -> StateView:
        return build_coding_state_view(state, game_spec)

    def render_blue_prompt(
        self,
        state_view: StateView,
        game_spec: GameSpec,
        attempt_number: int,
        previous_feedback: dict[str, object] | None,
    ) -> str:
        language = str(state_view.metadata["language"])
        plugin = _plugin_for(language)
        return render_coding_blue_prompt(
            state_view=state_view,
            game_spec=game_spec,
            attempt_number=attempt_number,
            previous_feedback=previous_feedback,
            plugin=plugin,
        )

    def render_red_prompt_supplement(
        self,
        state_view: StateView,
        game_spec: GameSpec,
        delta_state: DeltaState,
        verification_result: VerificationResult | None,
    ) -> str:
        del state_view, game_spec, delta_state
        return _render_coding_evaluation_supplement(verification_result)

    def render_referee_prompt_supplement(
        self,
        state_view: StateView,
        game_spec: GameSpec,
        delta_state: DeltaState,
        verification_result: VerificationResult | None,
    ) -> str:
        del state_view, game_spec, delta_state
        return _render_coding_evaluation_supplement(verification_result)

    def build_blue_output_format(self) -> str | dict | None:
        return None

    def build_blue_tools(self) -> list[ToolDefinition]:
        _file_schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path (non-empty)"},
                "content": {"type": "string", "description": "Full file content"},
            },
            "required": ["path", "content"],
        }
        return [
            ToolDefinition(
                name="write_files",
                description="Write one or more files to the coding artifact in a single delta.",
                parameters={
                    "type": "object",
                    "properties": {
                        "artifact_id": {
                            "type": "string",
                            "description": "Target coding artifact ID",
                        },
                        "files": {
                            "type": "array",
                            "items": _file_schema,
                            "minItems": 1,
                            "description": "List of files to write (path + content each)",
                        },
                    },
                    "required": ["artifact_id", "files"],
                },
            ),
            ToolDefinition(
                name="write_file",
                description="Write a single file to the coding artifact.",
                parameters={
                    "type": "object",
                    "properties": {
                        "artifact_id": {
                            "type": "string",
                            "description": "Target coding artifact ID",
                        },
                        "path": {
                            "type": "string",
                            "description": "Relative file path (non-empty)",
                        },
                        "content": {
                            "type": "string",
                            "description": "Full file content",
                        },
                    },
                    "required": ["artifact_id", "path", "content"],
                },
            ),
            ToolDefinition(
                name="delete_file",
                description="Delete a file from the coding artifact.",
                parameters={
                    "type": "object",
                    "properties": {
                        "artifact_id": {
                            "type": "string",
                            "description": "Target coding artifact ID",
                        },
                        "path": {
                            "type": "string",
                            "description": "Relative file path to delete",
                        },
                    },
                    "required": ["artifact_id", "path"],
                },
            ),
        ]

    def tool_call_to_delta(self, tool_call: ToolCall) -> DeltaState:
        args = tool_call.arguments
        if tool_call.name == "write_files":
            try:
                artifact_id = str(args["artifact_id"])
                files = args["files"]
            except KeyError as exc:
                raise ValueError(f"missing required tool argument: {exc}") from exc
            if not isinstance(files, list):
                raise ValueError("write_files tool argument 'files' must be a list")
            try:
                delta_batch = DeltaCodingBatchState.model_validate(
                    {
                        "artifact_id": artifact_id,
                        "operation": "write_files",
                        "payload": {"files": files},
                    }
                )
            except Exception as exc:
                raise ValueError(
                    f"tool call arguments failed DeltaCodingBatchState validation: {exc}"
                ) from exc
            _validate_coding_write_files_purity(delta_batch)
            return delta_batch
        if tool_call.name == "write_file":
            try:
                artifact_id = str(args["artifact_id"])
                path = str(args["path"])
                content = str(args["content"])
            except KeyError as exc:
                raise ValueError(f"missing required tool argument: {exc}") from exc
            try:
                delta_single = DeltaCodingState.model_validate(
                    {
                        "artifact_id": artifact_id,
                        "operation": "write_file",
                        "payload": {"file": {"path": path, "content": content}},
                    }
                )
            except Exception as exc:
                raise ValueError(
                    f"tool call arguments failed DeltaCodingState validation: {exc}"
                ) from exc
            _validate_coding_write_file_artifact_purity(delta_single)
            return delta_single
        if tool_call.name == "delete_file":
            try:
                artifact_id = str(args["artifact_id"])
                path = str(args["path"])
            except KeyError as exc:
                raise ValueError(f"missing required tool argument: {exc}") from exc
            _validate_file_path(path)
            try:
                return DeltaDeleteCodingState.model_validate(
                    {
                        "artifact_id": artifact_id,
                        "operation": "delete_file",
                        "payload": {"path": path},
                    }
                )
            except Exception as exc:
                raise ValueError(
                    f"tool call arguments failed DeltaDeleteCodingState validation: {exc}"
                ) from exc
        raise ValueError(f"unexpected tool: {tool_call.name!r}")

    def parse_blue_delta(self, text: str) -> DeltaState:
        return parse_coding_delta_json(text)

    def delta_to_state_update(self, delta_state: DeltaState) -> StateUpdateProposal:
        return derive_coding_state_update_from_delta(delta_state)

    def export_state(self, state: State, output_path: Path, artifact_id: str) -> bool:
        artifact = coding_artifact_from_state(state, artifact_id)
        plugin = _plugin_for(artifact.language)
        changed = plugin.initialize(output_path)

        resolved_root = output_path.resolve()
        for code_file in artifact.files:
            dest = (output_path / code_file.path).resolve()
            if not dest.is_relative_to(resolved_root):
                raise ValueError(
                    f"file path escapes output directory: {code_file.path!r}"
                )
            dest.parent.mkdir(parents=True, exist_ok=True)
            materialized = _normalize_coding_export_content(code_file.content)
            before = dest.read_text(encoding="utf-8") if dest.exists() else None
            if before != materialized:
                dest.write_text(materialized, encoding="utf-8")
                changed = True
        return changed

    def commit_export(self, output_path: Path, game_spec: GameSpec) -> bool:
        try:
            if not (output_path / ".git").exists():
                subprocess.run(
                    ["git", "init", "-b", "main"],
                    cwd=output_path,
                    capture_output=True,
                    check=True,
                )
            subprocess.run(
                ["git", "add", "-A"],
                cwd=output_path,
                capture_output=True,
                check=True,
            )
            result = subprocess.run(
                ["git", "commit", "-m", f"baps: {game_spec.objective}"],
                cwd=output_path,
                capture_output=True,
                text=True,
                check=False,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.SubprocessError):
            return False

    def verify_export(
        self, output_path: Path, state: State, artifact_id: str, sandbox_mode: str = "docker"
    ) -> VerificationResult | None:
        output_path.mkdir(parents=True, exist_ok=True)
        artifact = coding_artifact_from_state(state, artifact_id)
        missing_files = [
            code_file.path
            for code_file in artifact.files
            if not (output_path / code_file.path).exists()
        ]
        if missing_files:
            return VerificationResult(
                command="file_presence_check",
                cwd=str(output_path),
                exit_code=1,
                stdout="",
                stderr=f"exported files missing from output: {', '.join(missing_files)}",
                passed=False,
            )
        return _plugin_for(artifact.language).run_tests(output_path, sandbox_mode)

    def verify_candidate(
        self,
        delta_state: DeltaState,
        state: State,
        artifact_id: str,
        sandbox_mode: str = "docker",
    ) -> VerificationResult | None:
        import tempfile

        artifact = coding_artifact_from_state(state, artifact_id)
        plugin = _plugin_for(artifact.language)
        candidate_files = _apply_delta_to_files(artifact.files, delta_state)
        if not plugin.has_tests([f.path for f in candidate_files]):
            return None
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            plugin.initialize(tmp_path)
            resolved_tmp = tmp_path.resolve()
            for code_file in candidate_files:
                dest = (tmp_path / code_file.path).resolve()
                if not dest.is_relative_to(resolved_tmp):
                    raise ValueError(
                        f"file path escapes temp directory: {code_file.path!r}"
                    )
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(
                    _normalize_coding_export_content(code_file.content), encoding="utf-8"
                )
            return plugin.run_tests(tmp_path, sandbox_mode)
