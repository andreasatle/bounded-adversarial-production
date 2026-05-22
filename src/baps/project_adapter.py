from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from baps.models import ToolCall, ToolDefinition
from baps.northstar_projection import StateView
from baps.state import DeltaState, GameSpec, State, StateUpdateProposal


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


def _normalize_json_candidate(text: str) -> str:
    normalized = text.strip()
    fence_pattern = re.compile(
        r"\A```(?:json)?[ \t]*\n(?P<body>[\s\S]*?)\n```[ \t]*\Z",
        re.IGNORECASE,
    )
    fence_match = fence_pattern.match(normalized)
    if fence_match is not None:
        normalized = fence_match.group("body").strip()
    return normalized


@dataclass(frozen=True)
class VerificationResult:
    command: str
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    passed: bool


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

    def build_blue_tools(self) -> list[ToolDefinition]:
        ...

    def tool_call_to_delta(self, tool_call: ToolCall) -> DeltaState:
        ...

    def parse_blue_delta(self, text: str) -> DeltaState:
        ...

    def delta_to_state_update(self, delta_state: DeltaState) -> StateUpdateProposal:
        ...

    def export_state(self, state: State, output_path: Path, artifact_id: str) -> bool:
        ...

    def verify_export(
        self, output_path: Path, state: State, artifact_id: str
    ) -> VerificationResult | None:
        ...


def build_default_project_type_adapters() -> dict[str, ProjectTypeAdapter]:
    from baps.coding_adapter import CodingProjectAdapter
    from baps.document_adapter import DocumentProjectAdapter

    return {
        DocumentProjectAdapter.project_type: DocumentProjectAdapter(),
        CodingProjectAdapter.project_type: CodingProjectAdapter(),
    }


def resolve_project_type_adapter(project_type: str) -> ProjectTypeAdapter:
    if project_type == "git":
        raise ValueError("project_type 'git' is not implemented")
    adapter = build_default_project_type_adapters().get(project_type)
    if adapter is None:
        raise ValueError(f"unknown project_type: {project_type}")
    return adapter


def resolve_adapter_for_allowed_delta_type(allowed_delta_type: str) -> ProjectTypeAdapter:
    for adapter in build_default_project_type_adapters().values():
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
    return (
        "Produce exactly one delta JSON object allowed by GameSpec.allowed_delta_type.\n\n"
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
        f"- success_condition: {game_spec.success_condition}\n\n"
        "Execution rules:\n"
        "- Produce one delta that satisfies objective and success_condition.\n"
        "- Use StateView as the current artifact context.\n"
        "- Do not duplicate existing artifact content.\n"
        "- Do not rewrite unrelated existing state.\n"
        "- Do not emit placeholder or filler content.\n"
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
