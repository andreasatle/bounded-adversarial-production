from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from baps.northstar_projection import ProjectionType, StateView
from baps.project_adapter import VerificationResult, _normalize_json_candidate, render_blue_prompt_core
from baps.state import (
    CodingArtifact,
    CodeFile,
    DeltaCodingState,
    DeltaState,
    DocumentArtifact,
    GameSpec,
    NorthStar,
    State,
    StateUpdateProposal,
    StateUpdateTarget,
)
from baps.document_adapter import build_northstar_artifact_from_markdown


def _config_artifact_id(config: dict[str, Any]) -> str:
    if "artifact_id" not in config:
        raise ValueError("artifact_id must be non-empty")
    value = str(config["artifact_id"])
    if value.strip() == "":
        raise ValueError("artifact_id must be non-empty")
    return value


def _config_northstar_markdown(config: dict[str, Any]) -> str:
    value = str(config.get("northstar_markdown", ""))
    if value.strip() == "":
        raise ValueError("northstar_markdown must be non-empty")
    return value



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
    northstar_content_parts: list[str] = []
    for artifact in state.northstar.artifacts:
        if isinstance(artifact, DocumentArtifact):
            for section in artifact.sections:
                northstar_content_parts.append(section.body)
    northstar_content = "\n\n".join(northstar_content_parts).strip()

    file_lines: list[str] = []
    if target_artifact.files:
        for file in target_artifact.files:
            file_lines.append(f"- {file.path}")
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
            "",
            "### Current Files",
            "",
            *file_lines,
            "",
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
            "files": [file.model_dump(mode="json") for file in target_artifact.files],
        },
    )


def build_coding_state_view(state: State, game_spec: GameSpec) -> StateView:
    artifact = coding_artifact_from_state(state, game_spec.target_artifact_id)
    file_lines: list[str] = []
    if artifact.files:
        for file in artifact.files:
            file_lines.append(f"### {file.path}")
            file_lines.append("")
            file_lines.append(file.content)
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
            "files": [file.model_dump(mode="json") for file in artifact.files],
        },
    )


def render_coding_blue_prompt(
    state_view: StateView,
    game_spec: GameSpec,
    attempt_number: int,
    previous_feedback: dict[str, object] | None,
) -> str:
    coding_delta_instructions = (
        "Coding delta rules:\n"
        "- file.path and file.content must be non-empty strings.\n"
        "- Prefer production code under src/.\n"
        "- Prefer tests under tests/.\n"
        "- Prefer pytest-discoverable tests at tests/test_*.py.\n"
        "- Test files must import from their corresponding production module using standard Python imports (e.g. from src.fibonacci import fibonacci).\n"
        "- Test files must NOT redefine or duplicate production functions.\n"
        "- Keep code and tests as separate files (do not embed unittest in production file).\n"
        "- content must be a valid JSON string: escape internal double quotes as \\\" and newlines as \\n.\n"
        "- write_file content MUST contain final artifact content only.\n"
        "- write_file content MUST NOT include reasoning, planning notes, self-corrections, or alternative explanations.\n"
        "- Forbidden markers in content include: 'Note:', 'Correction:', 'Correcting', 'Re-writing', 'Rewriting', 'self-contained issue', 'Re-reading context'.\n"
        "- Return one complete JSON object with balanced braces.\n"
        "Required JSON shape:\n"
        "{\n"
        '  "artifact_id": "<game_spec.target_artifact_id>",\n'
        '  "operation": "write_file",\n'
        '  "payload": {\n'
        '    "file": {\n'
        '      "path": "<relative path>",\n'
        '      "content": "<full file content>"\n'
        "    }\n"
        "  }\n"
        "}"
    )
    return render_blue_prompt_core(
        state_view=state_view,
        game_spec=game_spec,
        attempt_number=attempt_number,
        previous_feedback=previous_feedback,
        project_delta_instructions=coding_delta_instructions,
    )


def parse_coding_delta_json(text: str) -> DeltaCodingState:
    normalized = _normalize_json_candidate(text)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        parsed = _recover_malformed_coding_delta_json(normalized)
        if parsed is None:
            raise ValueError("blue model output must be valid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("blue model output must be a JSON object")

    required_keys = {"artifact_id", "operation", "payload"}
    if set(parsed.keys()) != required_keys:
        raise ValueError(
            "blue model output must contain exactly keys: artifact_id, operation, payload"
        )

    try:
        delta = DeltaCodingState.model_validate(parsed)
    except Exception as exc:
        raise ValueError(
            f"blue model output failed DeltaCodingState validation: {exc}"
        ) from exc
    _validate_coding_write_file_artifact_purity(delta)
    return delta


def _validate_coding_write_file_artifact_purity(delta: DeltaCodingState) -> None:
    content = delta.payload.file.content
    lowered = content.lower()
    forbidden_markers = (
        "note:",
        "correction:",
        "correcting",
        "re-writing",
        "rewriting",
        "re-reading context",
        "self-contained issue",
    )
    for marker in forbidden_markers:
        if marker in lowered:
            raise ValueError(
                "blue model output failed DeltaCodingState validation: "
                f"write_file content contains forbidden reasoning marker {marker!r}"
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


def derive_coding_state_update_from_delta(delta_state: DeltaState) -> StateUpdateProposal:
    if not isinstance(delta_state, DeltaCodingState):
        raise ValueError(f"unsupported delta type for integration: {type(delta_state).__name__}")
    if delta_state.operation != "write_file":
        raise ValueError(f"unsupported delta operation for integration: {delta_state.operation}")
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


class CodingProjectAdapter:
    project_type = "coding"
    supported_delta_type = "DeltaCodingState"

    def create_initial_state(self, config: dict[str, object]) -> State:
        northstar_markdown = _config_northstar_markdown(config)
        northstar_artifact = build_northstar_artifact_from_markdown(northstar_markdown)
        return State(
            northstar=NorthStar(artifacts=(northstar_artifact,)),
            artifacts=(CodingArtifact(id=_config_artifact_id(config), files=()),),
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
            "- DeltaCodingState write_file changes exactly one file per game.\n"
            "- Choose exactly one missing file task per GameSpec.\n"
            "- Do not request multiple files in one GameSpec.\n"
            "- If no production file exists, choose src/fibonacci.py first.\n"
            "- If production file exists and test file is missing, choose tests/test_fibonacci.py next.\n"
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
        del state, config, state_view
        return (
            f"{base}"
            "Coding CreateGame verification evidence:\n"
            f"- previous_verification_result_json: {verification_json}\n"
            "- Use this as evidence from the previous exported state only.\n"
            "- If evidence shows import/layout errors, prefer a repair game that fixes import/layout.\n"
            "- If evidence shows failing tests, prefer a repair game for implementation/tests aligned to the failure.\n"
        )

    def normalize_game_spec(
        self, game_spec: GameSpec, state: State, config: dict[str, object]
    ) -> GameSpec:
        configured_artifact_id = _config_artifact_id(config)
        artifact = coding_artifact_from_state(state, configured_artifact_id)
        paths = {file.path for file in artifact.files}
        src_path = "src/fibonacci.py"
        test_path = "tests/test_fibonacci.py"
        if src_path not in paths:
            return GameSpec(
                objective=(
                    "Write src/fibonacci.py containing a fibonacci implementation "
                    "for the coding artifact."
                ),
                target_artifact_id=configured_artifact_id,
                allowed_delta_type=game_spec.allowed_delta_type,
                success_condition=(
                    "Artifact contains src/fibonacci.py with a non-empty fibonacci "
                    "implementation."
                ),
            )
        if test_path not in paths:
            return GameSpec(
                objective=(
                    "Write tests/test_fibonacci.py containing pytest tests for the "
                    "existing fibonacci implementation."
                ),
                target_artifact_id=configured_artifact_id,
                allowed_delta_type=game_spec.allowed_delta_type,
                success_condition=(
                    "Artifact contains tests/test_fibonacci.py with non-empty pytest "
                    "tests for fibonacci."
                ),
            )
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
        return render_coding_blue_prompt(
            state_view=state_view,
            game_spec=game_spec,
            attempt_number=attempt_number,
            previous_feedback=previous_feedback,
        )

    def render_red_prompt_supplement(
        self,
        state_view: StateView,
        game_spec: GameSpec,
        delta_state: DeltaState,
        verification_result: VerificationResult | None,
    ) -> str:
        del state_view, game_spec, delta_state, verification_result
        return (
            "Coding evaluation guidance:\n"
            "- target_artifact_id is the artifact id, not a file path.\n"
            "- File path belongs in DeltaCodingState.payload.file.path.\n"
            "- Pytest tests containing assert statements are not empty.\n"
            "- Do not reject tests as empty if assertions are present.\n"
            "- If success_condition only requires non-empty tests, basic asserted tests satisfy that condition.\n"
            "- If verification evidence exists, reason from exit_code/stdout/stderr.\n"
        )

    def render_referee_prompt_supplement(
        self,
        state_view: StateView,
        game_spec: GameSpec,
        delta_state: DeltaState,
        verification_result: VerificationResult | None,
    ) -> str:
        del state_view, game_spec, delta_state, verification_result
        return (
            "Coding evaluation guidance:\n"
            "- target_artifact_id is the artifact id, not a file path.\n"
            "- File path belongs in DeltaCodingState.payload.file.path.\n"
            "- Pytest tests containing assert statements are not empty.\n"
            "- Do not reject tests as empty if assertions are present.\n"
            "- If success_condition only requires non-empty tests, basic asserted tests satisfy that condition.\n"
            "- If verification evidence exists, reason from exit_code/stdout/stderr.\n"
        )

    def parse_blue_delta(self, text: str) -> DeltaState:
        return parse_coding_delta_json(text)

    def delta_to_state_update(self, delta_state: DeltaState) -> StateUpdateProposal:
        return derive_coding_state_update_from_delta(delta_state)

    def export_state(self, state: State, output_path: Path, artifact_id: str) -> bool:
        artifact = coding_artifact_from_state(state, artifact_id)
        output_path.mkdir(parents=True, exist_ok=True)
        changed = False

        conftest_path = output_path / "conftest.py"
        conftest_content = (
            "import sys, os\n"
            'sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))\n'
        )
        conftest_before = (
            conftest_path.read_text(encoding="utf-8") if conftest_path.exists() else None
        )
        if conftest_before != conftest_content:
            conftest_path.write_text(conftest_content, encoding="utf-8")
            changed = True

        for code_file in artifact.files:
            file_path = output_path / code_file.path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            materialized = _normalize_coding_export_content(code_file.content)
            before = file_path.read_text(encoding="utf-8") if file_path.exists() else None
            if before != materialized:
                file_path.write_text(materialized, encoding="utf-8")
                changed = True
        return changed

    def verify_export(
        self, output_path: Path, state: State, artifact_id: str
    ) -> VerificationResult | None:
        del state, artifact_id
        output_path.mkdir(parents=True, exist_ok=True)
        command_args: list[str]
        command: str
        try:
            command_args = ["uv", "run", "pytest"]
            command = "uv run pytest"
            completed = subprocess.run(
                command_args,
                cwd=output_path,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            command_args = [sys.executable, "-m", "pytest"]
            command = f"{sys.executable} -m pytest"
            completed = subprocess.run(
                command_args,
                cwd=output_path,
                capture_output=True,
                text=True,
                check=False,
            )
        return VerificationResult(
            command=command,
            cwd=str(output_path),
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            passed=completed.returncode == 0,
        )
