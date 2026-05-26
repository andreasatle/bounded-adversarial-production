from __future__ import annotations

import ast
import hashlib
import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from baps.language_plugin import LanguagePlugin
from baps.models import ToolCall, ToolDefinition
from baps.northstar_projection import ProjectionType, StateView
from baps.project_adapter import (
    VerificationResult,
    _config_artifact_id,
    _config_northstar_markdown,
    normalize_json_candidate,
    render_blue_prompt_core,
    sanitize_model_string,
    sanitize_model_title,
)
from baps.state import (
    CodingArtifact,
    CodeFile,
    DeltaCodingBatchState,
    DeltaCodingState,
    DeltaDeleteCodingState,
    DeltaState,
    GameSpec,
    State,
    StateUpdateProposal,
    StateUpdateTarget,
    WriteFileDelta,
    WriteFilesDelta,
)


_UNSAFE_PATH_CHARS_RE = re.compile(r'[;&|`$<>!\x00]')


def _validate_file_path(path: str) -> None:
    """Reject file paths that could escape the output directory or inject into shell commands."""
    if not path or not path.strip():
        raise ValueError("file path must be non-empty")
    p = Path(path)
    if p.is_absolute():
        raise ValueError(f"file path must be relative, not absolute: {path!r}")
    if ".." in p.parts:
        raise ValueError(f"file path must not contain '..' components: {path!r}")
    if _UNSAFE_PATH_CHARS_RE.search(path):
        raise ValueError(f"file path contains unsafe characters: {path!r}")


_BLUE_CONTENT_FORBIDDEN_MARKERS: tuple[str, ...] = (
    "Note:",
    "Correction:",
    "Correcting",
    "Re-writing",
    "Rewriting",
    "self-contained issue",
    "Re-reading context",
)


def _build_language_registry() -> dict[str, LanguagePlugin]:
    from baps.language_python import PythonLanguagePlugin
    from baps.language_zig import ZigLanguagePlugin

    return {
        "python": PythonLanguagePlugin(),
        "zig": ZigLanguagePlugin(),
    }


def _plugin_for(language: str) -> LanguagePlugin:
    registry = _build_language_registry()
    if language not in registry:
        available = ", ".join(sorted(registry))
        raise ValueError(
            f"Language {language!r} is not supported. Available languages: {available}"
        )
    return registry[language]


def _config_language(config: dict[str, object]) -> str:
    language = config.get("language")
    if not language:
        registry = _build_language_registry()
        available = ", ".join(sorted(registry))
        raise ValueError(
            f"coding project spec requires a 'language' field. Available languages: {available}"
        )
    return str(language)


def coding_artifact_from_state(state: State, artifact_id: str) -> CodingArtifact:
    artifact = next((a for a in state.artifacts if a.id == artifact_id), None)
    if artifact is None:
        raise ValueError(f"target coding artifact not found in state: {artifact_id}")
    if not isinstance(artifact, CodingArtifact):
        raise ValueError(f"target artifact must be CodingArtifact: {artifact_id}")
    return artifact


def build_coding_create_game_state_view(state: State, config: dict[str, Any]) -> StateView:
    artifact_id = _config_artifact_id(config)
    target_artifact = coding_artifact_from_state(state, artifact_id)
    northstar_content = _config_northstar_markdown(config)

    _MAX_LINES_PER_FILE = 30  # lines shown in CreateGame view per file

    file_lines: list[str] = []
    if target_artifact.files:
        for file in target_artifact.files:
            file_lines.append(f"### {sanitize_model_title(file.path)}")
            file_lines.append("")
            lines = file.content.splitlines()
            displayed = lines[:_MAX_LINES_PER_FILE] if len(lines) > _MAX_LINES_PER_FILE else lines
            fence = "````" if "```" in "\n".join(displayed) else "```"
            file_lines.append(fence)
            file_lines.extend(sanitize_model_string(line) for line in displayed)
            if len(lines) > _MAX_LINES_PER_FILE:
                file_lines.append(f"... ({len(lines) - _MAX_LINES_PER_FILE} more lines)")
            file_lines.append(fence)
            file_lines.append("")
    else:
        file_lines.append("No files.")

    content = "\n".join(
        [
            "=== StateView Start ===",
            "",
            "--- NorthStar ---",
            "",
            northstar_content if northstar_content else "No NorthStar content.",
            "",
            "--- State Artifacts ---",
            "",
            f"## Artifact: {target_artifact.id}",
            "",
            f"kind: {target_artifact.kind}",
            f"files: {len(target_artifact.files)}",
            "",
            "### Current Files",
            "",
            *file_lines,
            "=== StateView End ===",
        ]
    ).rstrip()
    input_fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return StateView(
        id=f"state-view:create-game:{target_artifact.id}:{input_fingerprint[:12]}",
        projection_type=ProjectionType.NORTH_STAR,
        content=content,
        input_fingerprint=input_fingerprint,
        metadata={
            "target_artifact_id": target_artifact.id,
            "language": target_artifact.language,
            "files": [file.model_dump(mode="json") for file in target_artifact.files],
        },
    )


def build_coding_state_view(state: State, game_spec: GameSpec) -> StateView:
    artifact = coding_artifact_from_state(state, game_spec.target_artifact_id)
    file_lines: list[str] = []
    if artifact.files:
        for file in artifact.files:
            file_lines.append(f"### {sanitize_model_title(file.path)}")
            file_lines.append("")
            fence = "````" if "```" in file.content else "```"
            file_lines.append(fence)
            file_lines.append(sanitize_model_string(file.content))
            file_lines.append(fence)
            file_lines.append("")
    else:
        file_lines.append("No files.")

    content = "\n".join(
        [
            "=== StateView Start ===",
            "",
            "--- State Artifacts ---",
            "",
            f"## Artifact: {artifact.id}",
            "",
            f"kind: {artifact.kind}",
            "",
            "### Current Files",
            "",
            *file_lines,
            "=== StateView End ===",
        ]
    ).rstrip()
    input_fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return StateView(
        id=f"state-view:blue:{artifact.id}:{input_fingerprint[:12]}",
        projection_type=ProjectionType.NORTH_STAR,
        content=content,
        input_fingerprint=input_fingerprint,
        metadata={
            "target_artifact_id": artifact.id,
            "language": artifact.language,
            "files": [file.model_dump(mode="json") for file in artifact.files],
        },
    )


def _render_verification_feedback_section(
    previous_feedback: dict[str, object] | None,
    plugin: LanguagePlugin,
) -> str:
    if previous_feedback is None:
        return ""
    section = ""
    if "prior_export_verification" in previous_feedback:
        pv = previous_feedback["prior_export_verification"]
        exit_code = pv.get("exit_code", "?")
        stdout = str(pv.get("stdout", ""))
        failures = plugin.parse_test_failures(stdout)
        if failures:
            lines = "\n".join(f"  - {f['test_id']}: {f['reason']}" for f in failures)
            section += (
                f"\nPrevious export verification failed (exit_code={exit_code}):\n"
                f"{lines}\n"
                "- Fix these specific test failures in your delta.\n"
            )
        elif exit_code not in (0, "0"):
            section += (
                f"\nPrevious export verification failed (exit_code={exit_code}).\n"
                "- Inspect prior_export_verification in previous_feedback_json and repair the cause.\n"
            )
    if "candidate_verification" in previous_feedback:
        cv = previous_feedback["candidate_verification"]
        exit_code = cv.get("exit_code", "?")
        stdout = str(cv.get("stdout", ""))
        failures = plugin.parse_test_failures(stdout)
        if failures:
            lines = "\n".join(f"  - {f['test_id']}: {f['reason']}" for f in failures)
            section += (
                f"\nCandidate verification failed (exit_code={exit_code}) — your last delta did not pass tests:\n"
                f"{lines}\n"
                "- Repair these test failures in this attempt.\n"
            )
        elif exit_code not in (0, "0"):
            section += (
                f"\nCandidate verification failed (exit_code={exit_code}).\n"
                "- Inspect candidate_verification in previous_feedback_json and repair the cause.\n"
            )
    return section


def render_coding_blue_prompt(
    state_view: StateView,
    game_spec: GameSpec,
    attempt_number: int,
    previous_feedback: dict[str, object] | None,
    plugin: LanguagePlugin,
) -> str:
    verification_section = _render_verification_feedback_section(previous_feedback, plugin)
    coding_delta_instructions = (
        "Coding delta rules:\n"
        "- Use write_files (plural) to write one or more files in a single delta — preferred.\n"
        "- Use write_file (singular) only when writing exactly one file.\n"
        "- Use delete_file to remove a file that is no longer needed.\n"
        "- file paths and content must be non-empty strings.\n"
        "- Prefer production code under src/.\n"
        "- Prefer tests under tests/.\n"
        "- Prefer pytest-discoverable tests at tests/test_*.py.\n"
        "- Test files must import from their corresponding production module using standard Python imports (e.g. from src.mymodule import myfunction).\n"
        "- Test files must NOT redefine or duplicate production functions.\n"
        "- Keep code and tests as separate files (do not embed unittest in production file).\n"
        "- content must be a valid JSON string: escape internal double quotes as \\\" and newlines as \\n.\n"
        "- File content MUST contain final artifact content only — no reasoning, planning notes, self-corrections, or alternative explanations.\n"
        f"- Forbidden markers in content include: {', '.join(repr(m) for m in _BLUE_CONTENT_FORBIDDEN_MARKERS)}.\n"
        "- Return one complete JSON object with balanced braces.\n"
        "Preferred JSON shape (write_files — one or more files):\n"
        "{\n"
        '  "artifact_id": "<game_spec.target_artifact_id>",\n'
        '  "operation": "write_files",\n'
        '  "payload": {\n'
        '    "files": [\n'
        '      {"path": "<relative path>", "content": "<full file content>"},\n'
        '      {"path": "<another path>", "content": "<full file content>"}\n'
        "    ]\n"
        "  }\n"
        "}\n"
        "Alternative shape (write_file — single file only):\n"
        "{\n"
        '  "artifact_id": "<game_spec.target_artifact_id>",\n'
        '  "operation": "write_file",\n'
        '  "payload": {\n'
        '    "file": {\n'
        '      "path": "<relative path>",\n'
        '      "content": "<full file content>"\n'
        "    }\n"
        "  }\n"
        "}\n"
        "Alternative shape (delete_file — remove a file):\n"
        "{\n"
        '  "artifact_id": "<game_spec.target_artifact_id>",\n'
        '  "operation": "delete_file",\n'
        '  "payload": {\n'
        '    "path": "<relative path to delete>"\n'
        "  }\n"
        "}"
        f"{verification_section}"
    )
    return render_blue_prompt_core(
        state_view=state_view,
        game_spec=game_spec,
        attempt_number=attempt_number,
        previous_feedback=previous_feedback,
        project_delta_instructions=coding_delta_instructions,
    )


def _fix_one_file_content_quotes(file_data: dict) -> None:
    """Fix residual \\\" in a single file's content caused by model double-escaping."""
    content = file_data.get("content")
    path = file_data.get("path")
    if not isinstance(content, str) or '\\"' not in content:
        return
    if "\n" not in content:
        file_data["content"] = content.replace('\\"', '"')
        return
    if not isinstance(path, str) or not path.endswith(".py"):
        return
    try:
        ast.parse(content)
        return  # already valid
    except SyntaxError:
        candidate = content.replace('\\"', '"')
        try:
            ast.parse(candidate)
            file_data["content"] = candidate
        except SyntaxError:
            pass


def _fix_delta_file_content_quotes(parsed: dict) -> None:
    """Fix residual \\\" in file content caused by model double-escaping quotes in JSON.

    Handles both write_file (single file) and write_files (multiple files).
    For single-line content this is always a transport artifact. For multi-line
    Python files we only unescape when doing so fixes an otherwise invalid syntax.
    """
    operation = parsed.get("operation")
    payload = parsed.get("payload")
    if not isinstance(payload, dict):
        return
    if operation == "write_files":
        files = payload.get("files")
        if not isinstance(files, list):
            return
        for file_data in files:
            if isinstance(file_data, dict):
                _fix_one_file_content_quotes(file_data)
        return
    file_data = payload.get("file")
    if isinstance(file_data, dict):
        _fix_one_file_content_quotes(file_data)


def parse_coding_delta_json(text: str) -> DeltaCodingState | DeltaCodingBatchState:
    normalized = normalize_json_candidate(text)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        parsed = _recover_malformed_coding_delta_json(normalized)
        if parsed is None:
            raise ValueError("blue model output must be valid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("blue model output must be a JSON object")

    logger.error("blue_delta raw response: %s", parsed)

    required_keys = {"artifact_id", "operation", "payload"}
    extra_keys = set(parsed.keys()) - required_keys
    if extra_keys:
        logger.warning("blue_delta: stripping extra keys: %s", sorted(extra_keys))
        for k in extra_keys:
            del parsed[k]
    if not required_keys.issubset(parsed.keys()):
        raise ValueError(
            "blue model output must contain keys: artifact_id, operation, payload"
        )

    _fix_delta_file_content_quotes(parsed)

    operation = parsed.get("operation")
    if operation == "write_files":
        try:
            delta = DeltaCodingBatchState.model_validate(parsed)
        except Exception as exc:
            raise ValueError(
                f"blue model output failed DeltaCodingBatchState validation: {exc}"
            ) from exc
        _validate_coding_write_files_purity(delta)
        return delta

    if operation == "delete_file":
        try:
            delta_delete = DeltaDeleteCodingState.model_validate(parsed)
        except Exception as exc:
            raise ValueError(
                f"blue model output failed DeltaDeleteCodingState validation: {exc}"
            ) from exc
        _validate_file_path(delta_delete.payload.path)
        return delta_delete

    try:
        delta = DeltaCodingState.model_validate(parsed)
    except Exception as exc:
        raise ValueError(
            f"blue model output failed DeltaCodingState validation: {exc}"
        ) from exc
    _validate_coding_write_file_artifact_purity(delta)
    return delta


def _validate_coding_write_file_artifact_purity(delta: DeltaCodingState) -> None:
    _validate_file_path(delta.payload.file.path)
    content = delta.payload.file.content
    lowered = content.lower()
    for marker in _BLUE_CONTENT_FORBIDDEN_MARKERS:
        if marker.lower() in lowered:
            raise ValueError(
                "blue model output failed DeltaCodingState validation: "
                f"write_file content contains forbidden reasoning marker {marker!r}"
            )


def _validate_coding_write_files_purity(delta: DeltaCodingBatchState) -> None:
    for code_file in delta.payload.files:
        _validate_file_path(code_file.path)
        lowered = code_file.content.lower()
        for marker in _BLUE_CONTENT_FORBIDDEN_MARKERS:
            if marker.lower() in lowered:
                raise ValueError(
                    "blue model output failed DeltaCodingBatchState validation: "
                    f"write_files file {code_file.path!r} contains forbidden reasoning marker {marker!r}"
                )


def _normalize_coding_export_content(content: str) -> str:
    """Normalize transport-escaped file payloads at export materialization time.

    This only decodes common JSON transport escapes when the content appears to
    be single-line escaped text (for example: `import x\\nprint(...)`).
    """
    if "\n" in content:
        return content
    if "\\n" not in content and "\\t" not in content and '\\"' not in content:
        return content
    return content.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')


def _recover_malformed_coding_delta_json(text: str) -> dict[str, object] | None:
    """Deterministic fallback for malformed write_file JSON payloads.

    Handles common model failures where file.content includes unescaped quotes/newlines,
    while the outer object still follows the expected shape.
    """
    artifact_match = re.search(r'"artifact_id"\s*:\s*"([^"]+)"', text)
    operation_match = re.search(r'"operation"\s*:\s*"([^"]+)"', text)
    path_match = re.search(r'"path"\s*:\s*"([^"]+)"', text)
    content_start_match = re.search(r'"content"\s*:\s*"', text)
    if (
        artifact_match is None
        or operation_match is None
        or path_match is None
        or content_start_match is None
    ):
        return None

    start = content_start_match.end()
    remainder = text[start:]
    end_patterns = (
        re.compile(r'"\s*}\s*}\s*}\s*$', re.DOTALL),
        re.compile(r'"\s*}\s*}\s*$', re.DOTALL),
        re.compile(r'"\s*}\s*$', re.DOTALL),
    )
    end_index: int | None = None
    for pattern in end_patterns:
        match = pattern.search(remainder)
        if match is not None:
            end_index = match.start()
            break
    if end_index is None:
        return None

    raw_content = remainder[:end_index]
    escaped_content = (
        raw_content.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    reconstructed = (
        "{"
        f'"artifact_id":"{artifact_match.group(1)}",'
        f'"operation":"{operation_match.group(1)}",'
        '"payload":{"file":{'
        f'"path":"{path_match.group(1)}",'
        f'"content":"{escaped_content}"'
        "}}"
        "}"
    )
    try:
        parsed = json.loads(reconstructed)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _truncate_lines(text: str, max_lines: int) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"


def _render_coding_evaluation_supplement(verification_result: VerificationResult | None) -> str:
    base = (
        "Coding evaluation guidance:\n"
        "- target_artifact_id is the artifact id, not a file path.\n"
        "- For write_file: file path belongs in payload.file.path.\n"
        "- For write_files: file paths belong in payload.files[].path.\n"
        "- Pytest tests containing assert statements are not empty.\n"
        "- Do not reject tests as empty if assertions are present.\n"
        "- If success_condition only requires non-empty tests, basic asserted tests satisfy that condition.\n"
        "- If verification evidence exists, reason from exit_code/stdout/stderr.\n"
    )
    if verification_result is not None:
        return base + "- If pytest discovered tests, do not claim test files are empty.\n"
    return base


def derive_coding_state_update_from_delta(delta_state: DeltaState) -> StateUpdateProposal:
    if isinstance(delta_state, DeltaCodingBatchState):
        paths = ", ".join(f.path for f in delta_state.payload.files)
        return StateUpdateProposal(
            id=f"state-update:{delta_state.artifact_id}:write_files:{len(delta_state.payload.files)}",
            target=StateUpdateTarget(artifact_id=delta_state.artifact_id),
            summary=(
                f"Write {len(delta_state.payload.files)} file(s) "
                f"({paths}) in coding artifact {delta_state.artifact_id}"
            ),
            payload={
                "operation": "write_files",
                "files": [f.model_dump(mode="json") for f in delta_state.payload.files],
            },
        )
    if isinstance(delta_state, DeltaCodingState):
        return StateUpdateProposal(
            id=f"state-update:{delta_state.artifact_id}:write_file:{delta_state.payload.file.path}",
            target=StateUpdateTarget(artifact_id=delta_state.artifact_id),
            summary=(
                f"Write file '{delta_state.payload.file.path}' "
                f"in coding artifact {delta_state.artifact_id}"
            ),
            payload={
                "operation": "write_file",
                "file": delta_state.payload.file.model_dump(mode="json"),
            },
        )
    if isinstance(delta_state, DeltaDeleteCodingState):
        return StateUpdateProposal(
            id=f"state-update:{delta_state.artifact_id}:delete_file:{delta_state.payload.path}",
            target=StateUpdateTarget(artifact_id=delta_state.artifact_id),
            summary=f"Delete file '{delta_state.payload.path}' from coding artifact {delta_state.artifact_id}",
            payload={
                "operation": "delete_file",
                "path": delta_state.payload.path,
            },
        )
    raise ValueError(f"unsupported delta type for integration: {type(delta_state).__name__}")


def _apply_delta_to_files(
    current_files: tuple[CodeFile, ...],
    delta: DeltaState,
) -> list[CodeFile]:
    files = list(current_files)
    if isinstance(delta, DeltaCodingBatchState):
        for new_file in delta.payload.files:
            files = [f for f in files if f.path != new_file.path]
            files.append(new_file)
    elif isinstance(delta, DeltaCodingState):
        new_file = delta.payload.file
        files = [f for f in files if f.path != new_file.path]
        files.append(new_file)
    elif isinstance(delta, DeltaDeleteCodingState):
        files = [f for f in files if f.path != delta.payload.path]
    return files


class CodingProjectAdapter:
    project_type = "coding"
    supported_delta_type = "DeltaCodingState"

    def create_initial_state(self, config: dict[str, object]) -> State:
        language = _config_language(config)
        _plugin_for(language)  # validate early — raises ValueError on unknown language
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
        verification_json = json.dumps(
            {
                "command": verification_result.command,
                "cwd": verification_result.cwd,
                "exit_code": verification_result.exit_code,
                "stdout": verification_result.stdout,
                "stderr": verification_result.stderr,
                "passed": verification_result.passed,
            },
            sort_keys=True,
        )
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
        # Constrained decoding schema — Blue may use write_file or write_files.
        # The payload shape differs per operation; returning None here lets the
        # prompt instructions drive the format rather than a single rigid schema.
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
