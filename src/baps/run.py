from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Protocol

import yaml

from baps.models import ModelClient, OllamaClient
from baps.northstar_projection import ProjectionType, StateView
from baps.state import (
    AppendSectionDelta,
    DeltaDocumentState,
    DeltaState,
    DocumentArtifact,
    GameSpec,
    NorthStar,
    PlayGameRuntime,
    RedFinding,
    RefereeDecision,
    Section,
    State,
    StateArtifact,
    StateUpdateProposal,
    StateUpdateTarget,
    fingerprint_state,
    apply_referee_decision_to_runtime,
    build_default_state_artifact_registry,
)
from baps.state_service import StateService
from baps.state_store import JsonStateStore

REQUEST = "Write a short report."


class NoNewAtomicGameError(ValueError):
    """Raised when the model explicitly indicates no new atomic game is available."""


def _debug_enabled() -> bool:
    return os.getenv("BAPS_DEBUG") == "1"


def _format_debug_yaml_like(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        if not value:
            return [f"{prefix}{{}}"]
        lines: list[str] = []
        for key in sorted(value.keys()):
            item = value[key]
            if isinstance(item, dict):
                if not item:
                    lines.append(f"{prefix}{key}: {{}}")
                else:
                    lines.append(f"{prefix}{key}:")
                    lines.extend(_format_debug_yaml_like(item, indent + 2))
            elif isinstance(item, (list, tuple)):
                if len(item) == 0:
                    lines.append(f"{prefix}{key}: []")
                else:
                    lines.append(f"{prefix}{key}:")
                    lines.extend(_format_debug_yaml_like(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {item}")
        return lines
    if isinstance(value, (list, tuple)):
        if len(value) == 0:
            return [f"{prefix}[]"]
        lines = []
        for item in value:
            if isinstance(item, dict):
                if not item:
                    lines.append(f"{prefix}- {{}}")
                    continue
                keys = sorted(item.keys())
                first_key = keys[0]
                first_value = item[first_key]
                if isinstance(first_value, (dict, list, tuple)):
                    lines.append(f"{prefix}- {first_key}:")
                    lines.extend(_format_debug_yaml_like(first_value, indent + 4))
                else:
                    lines.append(f"{prefix}- {first_key}: {first_value}")
                for key in keys[1:]:
                    nested = item[key]
                    if isinstance(nested, (dict, list, tuple)):
                        if isinstance(nested, dict) and not nested:
                            lines.append(f"{prefix}  {key}: {{}}")
                        elif isinstance(nested, (list, tuple)) and len(nested) == 0:
                            lines.append(f"{prefix}  {key}: []")
                        else:
                            lines.append(f"{prefix}  {key}:")
                            lines.extend(_format_debug_yaml_like(nested, indent + 4))
                    else:
                        lines.append(f"{prefix}  {key}: {nested}")
            elif isinstance(item, (list, tuple)):
                if len(item) == 0:
                    lines.append(f"{prefix}- []")
                else:
                    lines.append(f"{prefix}-")
                    lines.extend(_format_debug_yaml_like(item, indent + 2))
            else:
                lines.append(f"{prefix}- {item}")
        return lines
    return [f"{prefix}{value}"]


def _debug_print_read_config(args: argparse.Namespace, spec_data: dict[str, Any], config: dict[str, Any]) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] read_config.input:")
    input_payload = {
        "cli_args": {
            "workspace": args.workspace,
            "artifact_id": args.artifact_id,
            "goal": args.goal,
            "output": args.output,
            "max_iterations": args.max_iterations,
            "spec": args.spec,
        },
        "yaml_values": spec_data,
    }
    for line in _format_debug_yaml_like(input_payload, indent=2):
        print(line)
    print()
    print("[DEBUG] read_config.output:")
    output_payload = {
        "workspace": str(config["workspace"]),
        "artifact_id": config["artifact_id"],
        "northstar_markdown": config["northstar_markdown"],
        "goal": config["goal"],
        "output_path": str(config["output_path"]),
        "max_iterations": config["max_iterations"],
    }
    for line in _format_debug_yaml_like(output_payload, indent=2):
        print(line)
    print()


def _debug_print_create_state(config: dict[str, Any], state: State) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] create_state.input:")
    input_payload = {
        "project_type": config["project_type"],
        "artifact_id": _config_artifact_id(config),
        "northstar_markdown": _config_northstar_markdown(config),
        "workspace": str(config["workspace"]),
        "goal": config["goal"],
        "output_path": str(config["output_path"]),
        "max_iterations": config["max_iterations"],
    }
    for line in _format_debug_yaml_like(input_payload, indent=2):
        print(line)
    print()
    print("[DEBUG] create_state.output:")
    output_payload = {
        "state": state.model_dump(mode="json"),
    }
    for line in _format_debug_yaml_like(output_payload, indent=2):
        print(line)
    print()


def _debug_print_create_game_input(state: State) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] create_game.input:")
    input_payload = {
        "state": state.model_dump(mode="json"),
    }
    for line in _format_debug_yaml_like(input_payload, indent=2):
        print(line)
    print()


def _build_create_game_state_view(state: State, artifact_id: str) -> StateView:
    target_artifact = _document_artifact_from_state(state, artifact_id)
    northstar_content_parts: list[str] = []
    for artifact in state.northstar.artifacts:
        if isinstance(artifact, DocumentArtifact):
            for section in artifact.sections:
                northstar_content_parts.append(section.body)
    northstar_content = "\n\n".join(northstar_content_parts).strip()
    section_summaries = [
        {"title": section.title, "body": section.body}
        for section in target_artifact.sections
    ]
    metadata = {
        "northstar_content": northstar_content,
        "target_artifact": {
            "id": target_artifact.id,
            "kind": target_artifact.kind,
            "sections": section_summaries,
        },
        "state_summary": {
            "northstar_artifact_ids": [artifact.id for artifact in state.northstar.artifacts],
            "artifact_ids": [artifact.id for artifact in state.artifacts],
        },
    }
    section_lines: list[str] = []
    if target_artifact.sections:
        for section in target_artifact.sections:
            section_lines.append(f"### {section.title}")
            section_lines.append(section.body)
            section_lines.append("")
    else:
        section_lines.append("No sections.")

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
            "### Current Sections",
            "",
            *section_lines,
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
        metadata=metadata,
    )


def _debug_print_create_game_output(game_spec: GameSpec) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] create_game.output:")
    output_payload = {
        "game_spec": game_spec.model_dump(mode="json"),
    }
    for line in _format_debug_yaml_like(output_payload, indent=2):
        print(line)
    print()


def _debug_print_create_game_prompt(prompt: str) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] create_game.prompt:")
    for line in prompt.splitlines() or [""]:
        print(f"  {line}")
    print()


def _debug_print_play_game_input(state: State, game_spec: GameSpec) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] play_game.input:")
    payload = {
        "state": state.model_dump(mode="json"),
        "game_spec": game_spec.model_dump(mode="json"),
    }
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_play_game_output(delta: DeltaState | None) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] play_game.output:")
    payload = {
        "current_best_delta": None if delta is None else delta.model_dump(mode="json"),
    }
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_play_game_attempt(attempt: int) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] play_game.attempt:")
    payload = {"attempt": attempt}
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_blue_raw_model_output(raw_text: str) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] blue.raw_model_output:")
    for line in raw_text.splitlines() or [""]:
        print(f"  {line}")
    print()


def _debug_print_attempt_rejected(attempt: int, reason: str) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] play_game.attempt_rejected:")
    payload = {
        "attempt": attempt,
        "reason": reason,
    }
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_blue_input(
    state_view: StateView,
    game_spec: GameSpec,
    attempt_number: int,
    previous_feedback: dict[str, Any] | None,
) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] blue.input:")
    payload = {
        "game_spec": game_spec.model_dump(mode="json"),
        "state_view": state_view.model_dump(mode="json"),
        "attempt_number": attempt_number,
        "previous_feedback": previous_feedback,
    }
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_blue_output(delta: DeltaState) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] blue.output:")
    payload = {"delta_state": delta.model_dump(mode="json")}
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_red_input(
    state_view: StateView,
    game_spec: GameSpec,
    delta_state: DeltaState,
) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] red.input:")
    payload = {
        "game_spec": game_spec.model_dump(mode="json"),
        "state_view": state_view.model_dump(mode="json"),
        "delta_state": delta_state.model_dump(mode="json"),
    }
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_red_output(red_finding: RedFinding) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] red.output:")
    payload = {"red_finding": red_finding.model_dump(mode="json")}
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_referee_input(
    state_view: StateView,
    game_spec: GameSpec,
    delta_state: DeltaState,
    red_finding: RedFinding,
) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] referee.input:")
    payload = {
        "game_spec": game_spec.model_dump(mode="json"),
        "state_view": state_view.model_dump(mode="json"),
        "delta_state": delta_state.model_dump(mode="json"),
        "red_finding": red_finding.model_dump(mode="json"),
    }
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_referee_output(referee_decision: RefereeDecision) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] referee.output:")
    payload = {"referee_decision": referee_decision.model_dump(mode="json")}
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_create_game_raw_model_output(raw_text: str) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] create_game.raw_model_output:")
    for line in raw_text.splitlines() or [""]:
        print(f"  {line}")
    print()


def _build_create_game_model_client() -> ModelClient:
    model = os.getenv("BAPS_OLLAMA_MODEL", "llama3.2")
    base_url = os.getenv("BAPS_OLLAMA_BASE_URL", "http://localhost:11434")
    return OllamaClient(model=model, base_url=base_url)


def _build_blue_model_client() -> ModelClient:
    model = os.getenv("BAPS_OLLAMA_MODEL", "llama3.2")
    base_url = os.getenv("BAPS_OLLAMA_BASE_URL", "http://localhost:11434")
    return OllamaClient(model=model, base_url=base_url)


def _build_red_model_client() -> ModelClient:
    model = os.getenv("BAPS_OLLAMA_MODEL", "llama3.2")
    base_url = os.getenv("BAPS_OLLAMA_BASE_URL", "http://localhost:11434")
    return OllamaClient(model=model, base_url=base_url)


def _build_referee_model_client() -> ModelClient:
    model = os.getenv("BAPS_OLLAMA_MODEL", "llama3.2")
    base_url = os.getenv("BAPS_OLLAMA_BASE_URL", "http://localhost:11434")
    return OllamaClient(model=model, base_url=base_url)


def _require_non_empty(value: str, field_name: str) -> str:
    if value.strip() == "":
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _config_artifact_id(config: dict[str, Any]) -> str:
    if "artifact_id" not in config:
        raise ValueError("artifact_id must be non-empty")
    return _require_non_empty(str(config["artifact_id"]), "artifact_id")


def _config_northstar_markdown(config: dict[str, Any]) -> str:
    return _require_non_empty(str(config.get("northstar_markdown", "")), "northstar_markdown")


def _build_northstar_artifact_from_markdown(markdown: str) -> StateArtifact:
    fingerprint = hashlib.sha256(markdown.encode("utf-8")).hexdigest()[:12]
    return DocumentArtifact(
        id=f"northstar:{fingerprint}",
        sections=(Section(title="NorthStar", body=markdown),),
    )


def _build_document_state_view(state: State, game_spec: GameSpec) -> StateView:
    target_artifact = next(
        (artifact for artifact in state.artifacts if artifact.id == game_spec.target_artifact_id),
        None,
    )
    if target_artifact is None:
        raise ValueError(
            f"state_view target artifact not found in state: {game_spec.target_artifact_id}"
        )
    if not isinstance(target_artifact, DocumentArtifact):
        raise ValueError(
            "state_view only supports document artifact targets; "
            f"got: {target_artifact.kind}"
        )
    sections = [
        {"title": section.title, "body": section.body}
        for section in target_artifact.sections
    ]
    metadata = {
        "target_artifact_id": target_artifact.id,
        "sections": sections,
    }
    content = json.dumps(metadata, sort_keys=True)
    input_fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return StateView(
        id=f"state-view:blue:{target_artifact.id}:{input_fingerprint[:12]}",
        projection_type=ProjectionType.NORTH_STAR,
        content=content,
        input_fingerprint=input_fingerprint,
        metadata=metadata,
    )


def _load_spec(spec_path: Path) -> dict[str, Any]:
    if not spec_path.exists():
        raise ValueError(f"spec file not found: {spec_path}")

    loaded = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError("spec file must contain a YAML mapping/object at top level")
    return loaded


def _resolve_output_path(workspace: Path, output_value: str) -> Path:
    output_candidate = Path(output_value)
    if output_candidate.is_absolute():
        return output_candidate
    return workspace / output_candidate


def resolve_run_config(args: argparse.Namespace) -> dict[str, Any]:
    spec_data: dict[str, Any] = {}
    if args.spec:
        spec_path = Path(args.spec)
        spec_data = _load_spec(spec_path)
    else:
        spec_path = None

    workspace_raw = (
        args.workspace
        if args.workspace is not None
        else spec_data.get("workspace", ".baps-workspace")
    )
    project_type_raw = (
        args.project_type
        if args.project_type is not None
        else spec_data.get("project_type")
    )
    artifact_id_raw = spec_data.get("artifact_id")
    if args.artifact_id is not None:
        artifact_id_raw = args.artifact_id
    if "required_sections" in spec_data:
        raise ValueError(
            "required_sections is no longer supported; declare required structure in northstar_markdown"
        )
    northstar_markdown_raw = spec_data.get("northstar_markdown")
    northstar_path_raw = spec_data.get("northstar_path")
    if northstar_markdown_raw is None and northstar_path_raw is not None:
        northstar_path = Path(str(northstar_path_raw))
        if not northstar_path.is_absolute():
            northstar_path = Path.cwd() / northstar_path
        if not northstar_path.exists():
            raise ValueError(f"northstar_path file not found: {northstar_path}")
        northstar_markdown_raw = northstar_path.read_text(encoding="utf-8")
    goal_raw = args.goal if args.goal is not None else spec_data.get("goal", REQUEST)
    output_raw = args.output if args.output is not None else spec_data.get("output")
    max_iterations_raw = (
        args.max_iterations
        if args.max_iterations is not None
        else spec_data.get("max_iterations", 2)
    )

    workspace_str = _require_non_empty(str(workspace_raw), "workspace")
    if project_type_raw is None:
        raise ValueError("project_type must be non-empty")
    project_type = _require_non_empty(str(project_type_raw), "project_type")
    if project_type == "document" and artifact_id_raw is None:
        raise ValueError("artifact_id must be non-empty")
    if artifact_id_raw is None:
        artifact_id = ""
    else:
        artifact_id = _require_non_empty(str(artifact_id_raw), "artifact_id")
    goal = _require_non_empty(str(goal_raw), "goal")
    northstar_markdown = _require_non_empty(
        str(northstar_markdown_raw) if northstar_markdown_raw is not None else goal,
        "northstar_markdown",
    )
    workspace = Path(workspace_str)

    if output_raw is None:
        output_path = workspace / "output" / "report.md"
    else:
        output_str = _require_non_empty(str(output_raw), "output")
        output_path = _resolve_output_path(workspace, output_str)

    try:
        max_iterations = int(max_iterations_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_iterations must be an integer >= 1") from exc

    if max_iterations < 1:
        raise ValueError("max_iterations must be >= 1")

    config = {
        "workspace": workspace,
        "project_type": project_type,
        "artifact_id": artifact_id,
        "northstar_markdown": northstar_markdown,
        "goal": goal,
        "output_path": output_path,
        "max_iterations": max_iterations,
        "spec_path": spec_path,
    }
    _debug_print_read_config(args=args, spec_data=spec_data, config=config)
    return config


def create_state(config: dict[str, Any]) -> State:
    project_type = config["project_type"]
    if project_type == "git":
        raise ValueError("project_type 'git' is not implemented")
    adapter = _resolve_project_type_adapter(project_type)
    state = adapter.create_initial_state(config)
    _debug_print_create_state(config=config, state=state)
    return state


class ProjectTypeAdapter(Protocol):
    project_type: str
    supported_delta_type: str

    def create_initial_state(self, config: dict[str, Any]) -> State:
        ...

    def build_state_view(self, state: State, game_spec: GameSpec) -> StateView:
        ...

    def render_blue_prompt(
        self,
        state_view: StateView,
        game_spec: GameSpec,
        attempt_number: int,
        previous_feedback: dict[str, Any] | None,
    ) -> str:
        ...

    def parse_blue_delta(self, text: str) -> DeltaState:
        ...

    def delta_to_state_update(self, delta_state: DeltaState) -> StateUpdateProposal:
        ...

    def export_state(self, state: State, output_path: Path, artifact_id: str) -> bool:
        ...


class DocumentProjectAdapter:
    project_type = "document"
    supported_delta_type = "DeltaDocumentState"

    def create_initial_state(self, config: dict[str, Any]) -> State:
        northstar_markdown = _config_northstar_markdown(config)
        northstar_artifact = _build_northstar_artifact_from_markdown(northstar_markdown)
        return State(
            northstar=NorthStar(artifacts=(northstar_artifact,)),
            artifacts=(DocumentArtifact(id=_config_artifact_id(config), sections=()),),
        )

    def build_state_view(self, state: State, game_spec: GameSpec) -> StateView:
        return _build_document_state_view(state, game_spec)

    def render_blue_prompt(
        self,
        state_view: StateView,
        game_spec: GameSpec,
        attempt_number: int,
        previous_feedback: dict[str, Any] | None,
    ) -> str:
        return _render_document_blue_prompt(
            state_view=state_view,
            game_spec=game_spec,
            attempt_number=attempt_number,
            previous_feedback=previous_feedback,
        )

    def parse_blue_delta(self, text: str) -> DeltaState:
        return _parse_document_delta_json(text)

    def delta_to_state_update(self, delta_state: DeltaState) -> StateUpdateProposal:
        return _derive_document_state_update_from_delta(delta_state)

    def export_state(self, state: State, output_path: Path, artifact_id: str) -> bool:
        artifact = _document_artifact_from_state(state, artifact_id)
        rendered = _render_document_artifact_markdown(artifact)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        before = output_path.read_text(encoding="utf-8") if output_path.exists() else None
        changed = before != rendered
        if changed:
            output_path.write_text(rendered, encoding="utf-8")
        return changed


def _build_project_type_adapters() -> dict[str, ProjectTypeAdapter]:
    return {DocumentProjectAdapter.project_type: DocumentProjectAdapter()}


def _resolve_project_type_adapter(project_type: str) -> ProjectTypeAdapter:
    if project_type == "git":
        raise ValueError("project_type 'git' is not implemented")
    adapter = _build_project_type_adapters().get(project_type)
    if adapter is None:
        raise ValueError(f"unknown project_type: {project_type}")
    return adapter


def _render_create_game_prompt(
    config: dict[str, Any], state: State, adapter: ProjectTypeAdapter | None = None
) -> str:
    resolved_adapter = (
        adapter
        if adapter is not None
        else _resolve_project_type_adapter(config["project_type"])
    )
    state_view = _build_create_game_state_view(state, _config_artifact_id(config))
    return (
        "Create a GameSpec JSON object for the given project state.\n\n"
        "Derive the next atomic game from projected state context, including NorthStar intent.\n"
        "CreateGame is State/NorthStar-aware.\n"
        "PlayGame is GameSpec-bound.\n\n"
        "Input:\n"
        f"- goal: {config['goal']}\n"
        "- state_view:\n"
        "\n"
        f"{state_view.content}\n"
        "\n"
        f"- artifact_id: {_config_artifact_id(config)}\n"
        "- Use StateView NorthStar section as authoritative context.\n\n"
        "Return only a JSON object.\n"
        "Do not wrap output in markdown.\n"
        "Do not use triple-backtick fences.\n"
        "Do not include prose before JSON.\n"
        "Do not include prose after JSON.\n"
        "No extra fields.\n"
        "If no new atomic game exists for current state+northstar, return exactly:\n"
        '{\"no_new_atomic_game\": true, \"reason\": \"...\"}\n'
        "GameSpec must be self-contained for PlayGame execution without independently reading full NorthStar.\n"
        "The objective must describe BOTH:\n"
        "1. structural change\n"
        "2. substantive local intent\n"
        "Do not emit objectives that only describe structure.\n"
        "The GameSpec must contain enough local intent so PlayGame can execute without reading NorthStar.\n"
        "Fold relevant NorthStar intent into objective and success_condition.\n"
        "Avoid purely structural objectives when NorthStar contains substantive intent.\n"
        "Illustrative examples (not fixed policy):\n"
        "BAD objective: Add Introduction section.\n"
        "GOOD objective: Add Introduction section introducing bounded adversarial evaluation and its role in improving software projects.\n"
        "BAD success_condition: document contains Introduction.\n"
        "GOOD success_condition: artifact contains an Introduction section explaining bounded adversarial evaluation and framing the report purpose.\n"
        "GameSpec must be atomic:\n"
        "- target exactly one artifact.\n"
        "- permit exactly one delta type.\n"
        "- require exactly one coherent state change.\n"
        "- success_condition must be checkable from that one change.\n"
        "- do not bundle independent features/tasks in one GameSpec.\n"
        "- if goal needs multiple changes, select only the next missing atomic change.\n"
        "Required JSON shape:\n"
        "{\n"
        '  "objective": "...",\n'
        '  "target_artifact_id": "...",\n'
        '  "allowed_delta_type": "...",\n'
        '  "success_condition": "..."\n'
        "}\n\n"
        f"For this project type, allowed_delta_type must be {resolved_adapter.supported_delta_type}."
    )


def _document_artifact_from_state(state: State, artifact_id: str) -> DocumentArtifact:
    artifact = next((a for a in state.artifacts if a.id == artifact_id), None)
    if artifact is None:
        raise ValueError(f"create_game target artifact not found in state: {artifact_id}")
    if not isinstance(artifact, DocumentArtifact):
        raise ValueError(f"create_game target artifact must be DocumentArtifact: {artifact_id}")
    return artifact


def _render_document_artifact_markdown(artifact: DocumentArtifact) -> str:
    sections = [f"## {section.title}\n\n{section.body}" for section in artifact.sections]
    return "\n\n".join(sections)


def _ensure_target_artifact_exists(state: State, artifact_id: str) -> None:
    _ = next((a for a in state.artifacts if a.id == artifact_id), None)
    if _ is None:
        raise ValueError(f"create_game target artifact not found in state: {artifact_id}")


def _parse_game_spec_json(text: str) -> GameSpec:
    normalized = _normalize_json_candidate(text)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ValueError("create_game model output must be valid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("create_game model output must be a JSON object")

    required_keys = {
        "objective",
        "target_artifact_id",
        "allowed_delta_type",
        "success_condition",
    }
    if set(parsed.keys()) != required_keys:
        raise ValueError(
            "create_game model output must contain exactly keys: "
            "objective, target_artifact_id, allowed_delta_type, success_condition"
        )

    try:
        return GameSpec.model_validate(parsed)
    except Exception as exc:
        raise ValueError("create_game model output failed GameSpec validation") from exc


def _parse_create_game_output(text: str) -> GameSpec:
    normalized = _normalize_json_candidate(text)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ValueError("create_game model output must be valid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("create_game model output must be a JSON object")

    if set(parsed.keys()) == {"no_new_atomic_game", "reason"}:
        if parsed["no_new_atomic_game"] is not True:
            raise ValueError(
                "create_game no-game response must set no_new_atomic_game=true"
            )
        reason = str(parsed["reason"]).strip()
        if not reason:
            raise ValueError("create_game no-game response reason must be non-empty")
        raise NoNewAtomicGameError(reason)

    return _parse_game_spec_json(normalized)


def _is_bundled_change_text(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return False

    bundled_markers = (" and ", ", and ", ",", " plus ")
    return any(marker in lowered for marker in bundled_markers)


def _validate_atomic_game_spec(game_spec: GameSpec) -> None:
    if _is_bundled_change_text(game_spec.objective):
        raise ValueError(
            "create_game model output must describe exactly one atomic change in objective"
        )
    if _is_bundled_change_text(game_spec.success_condition):
        raise ValueError(
            "create_game model output success_condition must describe only the selected atomic change"
        )


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


def _parse_document_delta_json(text: str) -> DeltaDocumentState:
    normalized = _normalize_json_candidate(text)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ValueError("blue model output must be valid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("blue model output must be a JSON object")

    required_keys = {"artifact_id", "operation", "payload"}
    if set(parsed.keys()) != required_keys:
        raise ValueError(
            "blue model output must contain exactly keys: artifact_id, operation, payload"
        )

    try:
        return DeltaDocumentState.model_validate(parsed)
    except Exception as exc:
        raise ValueError(
            f"blue model output failed DeltaDocumentState validation: {exc}"
        ) from exc


def _parse_red_finding_json(text: str) -> RedFinding:
    normalized = _normalize_json_candidate(text)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ValueError("red model output must be valid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("red model output must be a JSON object")

    required_keys = {"disposition", "rationale"}
    if set(parsed.keys()) != required_keys:
        raise ValueError(
            "red model output must contain exactly keys: disposition, rationale"
        )

    try:
        return RedFinding.model_validate(parsed)
    except Exception as exc:
        raise ValueError("red model output failed RedFinding validation") from exc


def _parse_referee_decision_json(text: str) -> RefereeDecision:
    normalized = _normalize_json_candidate(text)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise ValueError("referee model output must be valid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("referee model output must be a JSON object")

    required_keys = {"disposition", "rationale"}
    if set(parsed.keys()) != required_keys:
        raise ValueError(
            "referee model output must contain exactly keys: disposition, rationale"
        )

    try:
        return RefereeDecision.model_validate(parsed)
    except Exception as exc:
        raise ValueError("referee model output failed RefereeDecision validation") from exc


def create_game(
    config: dict[str, Any],
    state: State,
    model_client: ModelClient | None = None,
    adapter: ProjectTypeAdapter | None = None,
) -> GameSpec:
    _debug_print_create_game_input(state)
    resolved_adapter = (
        adapter
        if adapter is not None
        else _resolve_project_type_adapter(config["project_type"])
    )
    client = model_client if model_client is not None else _build_create_game_model_client()
    prompt = _render_create_game_prompt(
        config=config, state=state, adapter=resolved_adapter
    )
    _debug_print_create_game_prompt(prompt)
    generated = client.generate(prompt)
    _debug_print_create_game_raw_model_output(generated)
    try:
        game_spec = _parse_create_game_output(generated)
    except (ValueError, NoNewAtomicGameError):
        raise
    _validate_atomic_game_spec(game_spec)
    expected_artifact_id = _config_artifact_id(config)
    if game_spec.target_artifact_id != expected_artifact_id:
        raise ValueError(
            "create_game target artifact must match configured artifact_id: "
            f"expected {expected_artifact_id}, got {game_spec.target_artifact_id}"
        )
    _ensure_target_artifact_exists(state, game_spec.target_artifact_id)
    if game_spec.allowed_delta_type != resolved_adapter.supported_delta_type:
        raise ValueError(
            "create_game allowed_delta_type must match project adapter: "
            f"expected {resolved_adapter.supported_delta_type}, got {game_spec.allowed_delta_type}"
        )
    _debug_print_create_game_output(game_spec)
    return game_spec


def _render_document_blue_prompt(
    state_view: StateView,
    game_spec: GameSpec,
    attempt_number: int,
    previous_feedback: dict[str, Any] | None,
) -> str:
    state_view_json = json.dumps(state_view.model_dump(mode="json"), sort_keys=True)
    previous_feedback_json = json.dumps(previous_feedback, sort_keys=True)
    return (
        "Produce a DeltaDocumentState JSON object for the provided StateView and GameSpec.\n\n"
        "Input:\n"
        f"- state_view_json: {state_view_json}\n"
        f"- attempt_number: {attempt_number}\n"
        f"- previous_feedback_json: {previous_feedback_json}\n"
        f"- objective: {game_spec.objective}\n"
        f"- target_artifact_id: {game_spec.target_artifact_id}\n"
        f"- allowed_delta_type: {game_spec.allowed_delta_type}\n"
        f"- success_condition: {game_spec.success_condition}\n\n"
        "Validation and repair rules:\n"
        "- section.title and section.body must be non-empty strings.\n"
        "- If previous_feedback_json contains validation errors, repair those exact errors in this attempt.\n"
        "- Do not repeat outputs that fail previously reported validation constraints.\n"
        "- When attempt_number > 1, treat previous_feedback_json as mandatory correction requirements.\n\n"
        "Return only a JSON object.\n"
        "Do not wrap output in markdown.\n"
        "Do not use triple-backtick fences.\n"
        "Do not include prose before JSON.\n"
        "Do not include prose after JSON.\n"
        "No extra fields.\n"
        'Invalid example, do not output: "body": ""\n'
        "Required JSON shape:\n"
        "{\n"
        '  "artifact_id": "<game_spec.target_artifact_id>",\n'
        '  "operation": "append_section",\n'
        '  "payload": {\n'
        '    "section": {\n'
        '      "title": "<section title>",\n'
        '      "body": "Concrete non-empty section body text."\n'
        "    }\n"
        "  }\n"
        "}"
    )


def _render_blue_prompt(
    state_view: StateView,
    game_spec: GameSpec,
    attempt_number: int,
    previous_feedback: dict[str, Any] | None,
) -> str:
    return _render_document_blue_prompt(
        state_view=state_view,
        game_spec=game_spec,
        attempt_number=attempt_number,
        previous_feedback=previous_feedback,
    )


def _render_red_prompt(
    state_view: StateView,
    game_spec: GameSpec,
    delta_state: DeltaState,
) -> str:
    state_view_json = json.dumps(state_view.model_dump(mode="json"), sort_keys=True)
    delta_state_json = json.dumps(delta_state.model_dump(mode="json"), sort_keys=True)
    return (
        "Evaluate the candidate DeltaDocumentState and return a RedFinding JSON object.\n\n"
        "Input:\n"
        f"- state_view_json: {state_view_json}\n"
        f"- delta_state_json: {delta_state_json}\n"
        f"- objective: {game_spec.objective}\n"
        f"- target_artifact_id: {game_spec.target_artifact_id}\n"
        f"- allowed_delta_type: {game_spec.allowed_delta_type}\n"
        f"- success_condition: {game_spec.success_condition}\n\n"
        "Evaluation policy:\n"
        "- Determine whether the candidate DeltaState moves the project toward the objective.\n"
        "- Determine whether the candidate satisfies the success_condition.\n"
        "- Identify inconsistency, harm, incompleteness, or quality issues.\n"
        "- Use revise only when the candidate is promising but needs improvement for goal satisfaction.\n"
        "- Do NOT reject or revise merely because state differs from the original state.\n\n"
        "Return only a JSON object.\n"
        "Do not wrap output in markdown.\n"
        "Do not use triple-backtick fences.\n"
        "Do not include prose before JSON.\n"
        "Do not include prose after JSON.\n"
        "No extra fields.\n"
        "Required JSON shape:\n"
        "{\n"
        '  "disposition": "accept" | "revise" | "reject",\n'
        '  "rationale": "..."\n'
        "}"
    )


def _render_referee_prompt(
    state_view: StateView,
    game_spec: GameSpec,
    delta_state: DeltaState,
    red_finding: RedFinding,
) -> str:
    state_view_json = json.dumps(state_view.model_dump(mode="json"), sort_keys=True)
    delta_state_json = json.dumps(delta_state.model_dump(mode="json"), sort_keys=True)
    red_finding_json = json.dumps(red_finding.model_dump(mode="json"), sort_keys=True)
    return (
        "Act as Referee and decide whether to accept, revise, or reject the candidate delta.\n\n"
        "Input:\n"
        f"- state_view_json: {state_view_json}\n"
        f"- delta_state_json: {delta_state_json}\n"
        f"- red_finding_json: {red_finding_json}\n"
        f"- objective: {game_spec.objective}\n"
        f"- target_artifact_id: {game_spec.target_artifact_id}\n"
        f"- allowed_delta_type: {game_spec.allowed_delta_type}\n"
        f"- success_condition: {game_spec.success_condition}\n\n"
        "Referee authority scope:\n"
        "- You are the game-local authority for this PlayGame decision.\n"
        "- You do NOT decide final State integration; integration is decided later by Integrator.\n\n"
        "Decision policy:\n"
        "- accept: objective/success_condition are satisfied enough for this game AND Red has no unresolved material findings.\n"
        "- revise: objective/success_condition are only partially satisfied OR Red has unresolved improvements that should be addressed.\n"
        "- reject: candidate is invalid, harmful, incoherent, or wrong direction.\n"
        "- Do NOT choose revise merely because state changed.\n\n"
        "Return only a JSON object.\n"
        "Do not wrap output in markdown.\n"
        "Do not use triple-backtick fences.\n"
        "Do not include prose before JSON.\n"
        "Do not include prose after JSON.\n"
        "No extra fields.\n"
        "Required JSON shape:\n"
        "{\n"
        '  "disposition": "accept" | "revise" | "reject",\n'
        '  "rationale": "..."\n'
        "}"
    )


def play_game(
    state: State,
    game_spec: GameSpec,
    adapter: ProjectTypeAdapter | None = None,
    model_client: ModelClient | None = None,
    red_model_client: ModelClient | None = None,
    referee_model_client: ModelClient | None = None,
    max_attempts: int = 3,
) -> DeltaState | None:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    resolved_adapter = adapter if adapter is not None else DocumentProjectAdapter()
    _debug_print_play_game_input(state, game_spec)
    state_view = resolved_adapter.build_state_view(state, game_spec)
    runtime = PlayGameRuntime()
    previous_feedback: dict[str, Any] | None = None
    client = model_client if model_client is not None else _build_blue_model_client()
    red_client = (
        red_model_client if red_model_client is not None else _build_red_model_client()
    )
    referee_client = (
        referee_model_client
        if referee_model_client is not None
        else _build_referee_model_client()
    )
    for attempt in range(1, max_attempts + 1):
        _debug_print_play_game_attempt(attempt)
        _debug_print_blue_input(state_view, game_spec, attempt, previous_feedback)
        blue_prompt = resolved_adapter.render_blue_prompt(
            state_view, game_spec, attempt, previous_feedback
        )
        blue_generated = client.generate(blue_prompt)
        try:
            candidate_delta = resolved_adapter.parse_blue_delta(blue_generated)
        except ValueError as exc:
            _debug_print_blue_raw_model_output(blue_generated)
            reason = f"blue output failed DeltaState validation: {exc}"
            _debug_print_attempt_rejected(attempt, reason)
            previous_feedback = {
                "attempt_rejection": {
                    "stage": "blue",
                    "reason": reason,
                    "validation_error": str(exc),
                }
            }
            continue
        _debug_print_blue_output(candidate_delta)

        _debug_print_red_input(state_view, game_spec, candidate_delta)
        red_prompt = _render_red_prompt(state_view, game_spec, candidate_delta)
        red_generated = red_client.generate(red_prompt)
        red_finding = _parse_red_finding_json(red_generated)
        _debug_print_red_output(red_finding)

        _debug_print_referee_input(state_view, game_spec, candidate_delta, red_finding)
        referee_prompt = _render_referee_prompt(
            state_view, game_spec, candidate_delta, red_finding
        )
        referee_generated = referee_client.generate(referee_prompt)
        referee_decision = _parse_referee_decision_json(referee_generated)
        _debug_print_referee_output(referee_decision)

        runtime = apply_referee_decision_to_runtime(
            runtime=runtime,
            candidate_delta=candidate_delta,
            decision=referee_decision,
        )
        if referee_decision.disposition == "accept":
            _debug_print_play_game_output(runtime.current_best_delta)
            return runtime.current_best_delta
        previous_feedback = {
            "red_finding": red_finding.model_dump(mode="json"),
            "referee_decision": referee_decision.model_dump(mode="json"),
        }
    _debug_print_play_game_output(runtime.current_best_delta)
    return runtime.current_best_delta


def _derive_document_state_update_from_delta(delta_state: DeltaState) -> StateUpdateProposal:
    if not isinstance(delta_state, DeltaDocumentState):
        raise ValueError(f"unsupported delta type for integration: {type(delta_state).__name__}")
    if delta_state.operation != "append_section":
        raise ValueError(f"unsupported delta operation for integration: {delta_state.operation}")
    return StateUpdateProposal(
        id=f"state-update:{delta_state.artifact_id}:append_section",
        target=StateUpdateTarget(artifact_id=delta_state.artifact_id),
        summary=(
            f"Append section '{delta_state.payload.section.title}' "
            f"to document artifact {delta_state.artifact_id}"
        ),
        payload={
            "operation": "append_section",
            "section": delta_state.payload.section.model_dump(mode="json"),
        },
    )


def _derive_state_update_from_delta(
    delta_state: DeltaState, adapter: ProjectTypeAdapter
) -> StateUpdateProposal:
    return adapter.delta_to_state_update(delta_state)


def _state_path_for_workspace(workspace: Path) -> Path:
    return workspace / "state" / "state.json"


def _ensure_not_initialized(workspace: Path) -> None:
    if _state_path_for_workspace(workspace).exists():
        raise ValueError("project already initialized")


def _ensure_initialized(workspace: Path) -> None:
    if not _state_path_for_workspace(workspace).exists():
        raise ValueError("project state not initialized")


def _initialize_project(
    config: dict[str, Any],
) -> tuple[StateService, State]:
    workspace = config["workspace"]
    _ensure_not_initialized(workspace)
    initial_state = create_state(config)
    state_store = JsonStateStore(_state_path_for_workspace(workspace))
    state_store.save(initial_state)
    service = StateService(
        store=state_store,
        registry=build_default_state_artifact_registry(),
    )
    return service, initial_state


def _load_project_service(workspace: Path) -> StateService:
    _ensure_initialized(workspace)
    return StateService(
        store=JsonStateStore(_state_path_for_workspace(workspace)),
        registry=build_default_state_artifact_registry(),
    )


def _run_project_iterations(
    config: dict[str, Any],
    adapter: ProjectTypeAdapter,
    state_service: StateService,
    initial_state: State,
) -> dict[str, object]:
    output_path = config["output_path"]
    max_iterations = config["max_iterations"]
    artifact_id = _config_artifact_id(config)

    current_state = initial_state
    update_applied = False
    state_changed = False
    output_exported = False
    output_changed = False
    stop_reason = "iteration_limit_reached"

    for _iteration in range(1, max_iterations + 1):
        try:
            game_spec = create_game(config, current_state, adapter=adapter)
        except NoNewAtomicGameError:
            stop_reason = "create_game_no_new_atomic_game"
            break

        delta_state = play_game(current_state, game_spec, adapter=adapter)
        if delta_state is None:
            stop_reason = "play_game_no_delta"
            break

        before_state = state_service.load_state()
        proposal = _derive_state_update_from_delta(delta_state, adapter=adapter)
        updated_state = state_service.apply_update(proposal)

        changed_this_iteration = (
            fingerprint_state(before_state) != fingerprint_state(updated_state)
        )
        update_applied = True
        output_changed = adapter.export_state(updated_state, output_path, artifact_id)
        output_exported = True
        if changed_this_iteration:
            state_changed = True
            current_state = updated_state
            continue

        stop_reason = "no_state_change"
        current_state = updated_state
        break

    return {
        "update_applied": update_applied,
        "state_changed": state_changed,
        "output_exported": output_exported,
        "output_changed": output_changed,
        "stop_reason": stop_reason,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one hardened deterministic baps loop.")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("init", "run", "init_and_run"),
        default="init_and_run",
        help="Lifecycle command.",
    )
    parser.add_argument("--spec", default=None, help="YAML spec path.")
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace directory for runtime outputs.",
    )
    parser.add_argument(
        "--project-type",
        default=None,
        help="Project type (currently supported: document).",
    )
    parser.add_argument(
        "--artifact-id",
        default=None,
        help="Artifact id for document project state.",
    )
    parser.add_argument(
        "--goal",
        default=None,
        help="Runtime goal text.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output markdown path (relative paths are resolved under workspace).",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Maximum loop iterations (must be >= 1).",
    )
    args = parser.parse_args()

    try:
        config = resolve_run_config(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    command = args.command
    workspace = config["workspace"]
    project_type = config["project_type"]
    goal = config["goal"]
    output_path = config["output_path"]
    max_iterations = config["max_iterations"]
    try:
        adapter = _resolve_project_type_adapter(project_type)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    update_applied = False
    state_changed = False
    output_exported = False
    output_changed = False
    stop_reason = "not_run"

    try:
        if command == "init":
            _initialize_project(config)
            stop_reason = "initialized_only"
        elif command == "run":
            state_service = _load_project_service(workspace)
            current_state = state_service.load_state()
            results = _run_project_iterations(
                config=config,
                adapter=adapter,
                state_service=state_service,
                initial_state=current_state,
            )
            update_applied = bool(results["update_applied"])
            state_changed = bool(results["state_changed"])
            output_exported = bool(results["output_exported"])
            output_changed = bool(results["output_changed"])
            stop_reason = str(results["stop_reason"])
        else:  # init_and_run
            state_service, current_state = _initialize_project(config)
            results = _run_project_iterations(
                config=config,
                adapter=adapter,
                state_service=state_service,
                initial_state=current_state,
            )
            update_applied = bool(results["update_applied"])
            state_changed = bool(results["state_changed"])
            output_exported = bool(results["output_exported"])
            output_changed = bool(results["output_changed"])
            stop_reason = str(results["stop_reason"])
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    print(f"workspace={workspace}")
    print(f"project_type={project_type}")
    print(f"command={command}")
    print(f"goal={goal}")
    print(f"output_path={output_path}")
    print(f"max_iterations={max_iterations}")
    print(f"update_applied={update_applied}")
    print(f"state_changed={state_changed}")
    print(f"output_exported={output_exported}")
    print(f"output_changed={output_changed}")
    print(f"stop_reason={stop_reason}")


if __name__ == "__main__":
    main()
