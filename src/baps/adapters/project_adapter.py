from __future__ import annotations

import functools
import re
import types
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from baps.models.models import ToolCall, ToolDefinition
from baps.northstar.northstar_projection import StateView
from baps.state.state import DeltaState, GameSpec, State


_MODEL_INJECTION_RE = re.compile(
    r"(ignore|disregard|forget|override)\s+(all\s+)?(previous|prior|above|earlier)\s+"
    r"(instructions?|prompts?|context|rules?)"
    r"|^[\t ]*system\s*:"
    r"|^[\t ]*assistant\s*:"
    r"|^[\t ]*user\s*:",
    re.IGNORECASE | re.MULTILINE,
)


def sanitize_model_string(text: str) -> str:
    """Strip injection patterns from model-generated content before embedding in prompts."""
    normalized = unicodedata.normalize("NFKC", text)
    return _MODEL_INJECTION_RE.sub("[content removed]", normalized)


def sanitize_model_title(text: str) -> str:
    """Sanitize a model-generated string used as a markdown heading label.

    Collapses to a single line (newlines would escape heading context) and
    strips leading # characters that would create nested headings.
    """
    single_line = " ".join(text.splitlines()).strip()
    single_line = single_line.lstrip("#").strip()
    return sanitize_model_string(single_line)


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



@dataclass(frozen=True)
class VerificationResult:
    command: str
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    passed: bool


def _verification_result_to_dict(result: VerificationResult) -> dict[str, Any]:
    return {
        "command": result.command,
        "cwd": result.cwd,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "passed": result.passed,
    }


class ProjectTypeAdapter(Protocol):
    project_type: str
    supported_delta_type: str

    def create_initial_state(self, config: dict[str, object]) -> State:
        ...

    def build_create_game_state_view(self, state: State, config: dict[str, object]) -> StateView:
        ...

    def render_create_game_prompt_supplement(
        self,
        state: State,
        config: dict[str, object],
        state_view: StateView,
        verification_result: VerificationResult | None,
    ) -> str:
        ...

    def normalize_game_spec(
        self, game_spec: GameSpec, state: State, config: dict[str, object]
    ) -> GameSpec:
        ...

    def build_state_view(self, state: State, game_spec: GameSpec) -> StateView:
        ...

    def render_blue_prompt(
        self,
        state_view: StateView,
        game_spec: GameSpec,
        attempt_number: int,
        previous_feedback: dict[str, object] | None,
    ) -> str:
        ...

    def render_red_prompt_supplement(
        self,
        state_view: StateView,
        game_spec: GameSpec,
        delta_state: DeltaState,
        verification_result: VerificationResult | None,
    ) -> str:
        ...

    def render_referee_prompt_supplement(
        self,
        state_view: StateView,
        game_spec: GameSpec,
        delta_state: DeltaState,
        verification_result: VerificationResult | None,
    ) -> str:
        ...

    def build_blue_output_format(self) -> str | dict | None:
        ...

    def build_blue_tools(self) -> list[ToolDefinition]:
        ...

    def build_research_tools(self, role: str) -> list[ToolDefinition]:
        ...

    def tool_call_to_delta(self, tool_call: ToolCall) -> DeltaState:
        ...

    def parse_blue_delta(self, text: str) -> DeltaState:
        ...

    def export_state(self, state: State, output_path: Path, artifact_id: str) -> bool:
        ...

    def verify_export(
        self, output_path: Path, state: State, artifact_id: str, sandbox_mode: str = "docker"
    ) -> VerificationResult | None:
        ...


def build_default_project_type_adapters() -> dict[str, ProjectTypeAdapter]:
    from baps.adapters.coding_adapter import CodingProjectAdapter
    from baps.adapters.document_adapter import DocumentProjectAdapter
    from baps.adapters.audit_adapter import AuditProjectAdapter

    return {
        DocumentProjectAdapter.project_type: DocumentProjectAdapter(),
        CodingProjectAdapter.project_type: CodingProjectAdapter(),
        AuditProjectAdapter.project_type: AuditProjectAdapter(),
    }


@functools.lru_cache(maxsize=None)
def _cached_default_adapters() -> types.MappingProxyType:
    return types.MappingProxyType(build_default_project_type_adapters())


def resolve_project_type_adapter(project_type: str) -> ProjectTypeAdapter:
    if project_type == "git":
        raise ValueError("project_type 'git' is not implemented")
    adapter = _cached_default_adapters().get(project_type)
    if adapter is None:
        raise ValueError(f"unknown project_type: {project_type}")
    return adapter


def resolve_adapter_for_allowed_delta_type(allowed_delta_type: str) -> ProjectTypeAdapter:
    for adapter in _cached_default_adapters().values():
        if adapter.supported_delta_type == allowed_delta_type:
            return adapter
    raise ValueError(f"unknown allowed_delta_type: {allowed_delta_type}")


def render_blue_prompt_core(
    state_view: StateView,
    game_spec: GameSpec,
    attempt_number: int,
    previous_feedback: dict[str, object] | None,
    project_delta_instructions: str = "",
) -> str:
    import json

    previous_feedback_json = json.dumps(previous_feedback, sort_keys=True)
    context_block = ""
    if game_spec.context_chain:
        lines = ["Planning context (coarsest → finest scope):"]
        for i, desc in enumerate(game_spec.context_chain):
            lines.append(f"  [{i + 1}] {desc}")
        context_block = "\n".join(lines) + "\n\n"
    max_words_input = f"- max_words: {game_spec.max_words}\n" if game_spec.max_words else ""
    max_words_rule = (
        "- Hard word budget: your output must not exceed max_words words. Cut, do not pad.\n"
        if game_spec.max_words else ""
    )
    return (
        "Produce exactly one delta JSON object allowed by GameSpec.allowed_delta_type.\n\n"
        f"{context_block}"
        "Input:\n"
        "- state_view:\n"
        "\n"
        f"{state_view.content}\n"
        "\n"
        f"- attempt_number: {attempt_number}\n"
        f"- previous_feedback_json: {previous_feedback_json}\n"
        f"- objective: {game_spec.objective}\n"
        f"- target_artifact_id: {game_spec.target_artifact_id}\n"
        f"- allowed_delta_type: {game_spec.allowed_delta_type}\n"
        f"- success_condition: {game_spec.success_condition}\n"
        f"{max_words_input}"
        "\nExecution rules:\n"
        "- Produce one delta that satisfies objective and success_condition.\n"
        "- Use context chain (if present) to understand the broader plan your work belongs to.\n"
        "- Use StateView as the current artifact context.\n"
        "- Do not duplicate existing artifact content.\n"
        "- Do not rewrite unrelated existing state.\n"
        "- Do not emit placeholder or filler content.\n"
        f"{max_words_rule}"
        "- If previous_feedback_json contains validation errors, repair those exact errors in this attempt.\n"
        "- Do not repeat outputs that fail previously reported validation constraints.\n"
        "- When attempt_number > 1, treat previous_feedback_json as mandatory correction requirements.\n\n"
        "Return only a JSON object.\n"
        "Do not wrap output in markdown.\n"
        "Do not use triple-backtick fences.\n"
        "Do not include prose before JSON.\n"
        "Do not include prose after JSON.\n"
        "No extra fields.\n\n"
        f"{project_delta_instructions}"
    )
