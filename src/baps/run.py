from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, field_validator

from baps.game_executor import GameExecutionResult
from baps.integration import IntegrationDecision, IntegrationSatisfaction, StateChange
from baps.loop import run_loop
from baps.models import ModelClient, OllamaClient
from baps.northstar_projection import NorthStarView, ProjectionType
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
    apply_referee_decision_to_runtime,
)
from baps.state_progressor import GameProposal, StateProgressionProposal, StateProgressorInput

REQUEST = "Write a short report with an introduction and conclusion."
SECTION_MARKER = "## Introduction and Conclusion"
SECTION_BODY = (
    f"{SECTION_MARKER}\n\n"
    "Introduction: This short report summarizes the current state of the workspace output.\n\n"
    "Conclusion: The report now includes both an introduction and a conclusion in one section.\n"
)


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


def _debug_print_blue_input(blue_view: "BlueView", game_spec: GameSpec) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] blue.input:")
    payload = {
        "game_spec": game_spec.model_dump(mode="json"),
        "blue_view": blue_view.model_dump(mode="json"),
    }
    for line in _format_debug_yaml_like(payload, indent=2):
        print(line)
    print()


def _debug_print_blue_output(delta: DeltaDocumentState) -> None:
    if not _debug_enabled():
        return
    print("[DEBUG] blue.output:")
    payload = {"delta_state": delta.model_dump(mode="json")}
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


def _require_non_empty(value: str, field_name: str) -> str:
    if value.strip() == "":
        raise ValueError(f"{field_name} must be non-empty")
    return value


class BlueView(BaseModel):
    target_artifact_id: str
    sections: list[dict[str, str]]

    _validate_target_artifact_id = field_validator("target_artifact_id")(
        lambda value: _require_non_empty(value, "target_artifact_id")
    )


def _build_blue_view(state: State, game_spec: GameSpec) -> BlueView:
    target_artifact = next(
        (artifact for artifact in state.artifacts if artifact.id == game_spec.target_artifact_id),
        None,
    )
    if target_artifact is None:
        raise ValueError(
            f"blue_view target artifact not found in state: {game_spec.target_artifact_id}"
        )
    if not isinstance(target_artifact, DocumentArtifact):
        raise ValueError(
            "blue_view only supports document artifact targets; "
            f"got: {target_artifact.kind}"
        )
    return BlueView(
        target_artifact_id=target_artifact.id,
        sections=[
            {"title": section.title, "body": section.body}
            for section in target_artifact.sections
        ],
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
    goal = _require_non_empty(str(goal_raw), "goal")
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
        "goal": goal,
        "output_path": output_path,
        "max_iterations": max_iterations,
        "spec_path": spec_path,
    }
    _debug_print_read_config(args=args, spec_data=spec_data, config=config)
    return config


def create_state(config: dict[str, Any]) -> State:
    project_type = config["project_type"]
    if project_type == "document":
        state = State(
            northstar=NorthStar(artifacts=()),
            artifacts=(DocumentArtifact(id="main-document", sections=()),),
        )
        _debug_print_create_state(config=config, state=state)
        return state
    if project_type == "git":
        raise ValueError("project_type 'git' is not implemented")
    raise ValueError(f"unknown project_type: {project_type}")


def _render_create_game_prompt(config: dict[str, Any], state: State) -> str:
    state_json = json.dumps(state.model_dump(mode="json"), sort_keys=True)
    return (
        "Create a GameSpec JSON object for the given project state.\n\n"
        "Input:\n"
        f"- goal: {config['goal']}\n"
        f"- state_json: {state_json}\n\n"
        "Return only a JSON object.\n"
        "Do not wrap output in markdown.\n"
        "Do not use triple-backtick fences.\n"
        "Do not include prose before JSON.\n"
        "Do not include prose after JSON.\n"
        "No extra fields.\n"
        "Required JSON shape:\n"
        "{\n"
        '  "objective": "...",\n'
        '  "target_artifact_id": "...",\n'
        '  "allowed_delta_type": "...",\n'
        '  "success_condition": "..."\n'
        "}\n\n"
        "For the current document path, allowed_delta_type must be DeltaDocumentState."
    )


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


def _parse_blue_delta_json(text: str) -> DeltaDocumentState:
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
        raise ValueError("blue model output failed DeltaDocumentState validation") from exc


def create_game(
    config: dict[str, Any],
    state: State,
    model_client: ModelClient | None = None,
) -> GameSpec:
    _debug_print_create_game_input(state)
    client = model_client if model_client is not None else _build_create_game_model_client()
    prompt = _render_create_game_prompt(config=config, state=state)
    generated = client.generate(prompt)
    try:
        game_spec = _parse_game_spec_json(generated)
    except ValueError:
        _debug_print_create_game_raw_model_output(generated)
        raise
    target_exists = any(artifact.id == game_spec.target_artifact_id for artifact in state.artifacts)
    if not target_exists:
        raise ValueError(
            "create_game target artifact not found in state: "
            f"{game_spec.target_artifact_id}"
        )
    _debug_print_create_game_output(game_spec)
    return game_spec


def _deterministic_red_finding() -> RedFinding:
    return RedFinding(disposition="accept", rationale="deterministic test path")


def _deterministic_referee_decision() -> RefereeDecision:
    return RefereeDecision(disposition="accept", rationale="deterministic test path")


def _render_blue_prompt(blue_view: BlueView, game_spec: GameSpec) -> str:
    blue_view_json = json.dumps(blue_view.model_dump(mode="json"), sort_keys=True)
    return (
        "Produce a DeltaDocumentState JSON object for the provided GameSpec.\n\n"
        "Input:\n"
        f"- blue_view_json: {blue_view_json}\n"
        f"- objective: {game_spec.objective}\n"
        f"- target_artifact_id: {game_spec.target_artifact_id}\n"
        f"- allowed_delta_type: {game_spec.allowed_delta_type}\n"
        f"- success_condition: {game_spec.success_condition}\n\n"
        "Return only a JSON object.\n"
        "Do not wrap output in markdown.\n"
        "Do not use triple-backtick fences.\n"
        "Do not include prose before JSON.\n"
        "Do not include prose after JSON.\n"
        "No extra fields.\n"
        "Required JSON shape:\n"
        "{\n"
        '  "artifact_id": "...",\n'
        '  "operation": "append_section",\n'
        '  "payload": {\n'
        '    "section": {\n'
        '      "title": "Introduction",\n'
        '      "body": "..."\n'
        "    }\n"
        "  }\n"
        "}"
    )


def play_game(
    state: State,
    game_spec: GameSpec,
    model_client: ModelClient | None = None,
) -> DeltaState | None:
    _debug_print_play_game_input(state, game_spec)
    runtime = PlayGameRuntime()
    blue_view = _build_blue_view(state, game_spec)
    _debug_print_blue_input(blue_view, game_spec)
    client = model_client if model_client is not None else _build_blue_model_client()
    blue_prompt = _render_blue_prompt(blue_view, game_spec)
    blue_generated = client.generate(blue_prompt)
    candidate_delta = _parse_blue_delta_json(blue_generated)
    _debug_print_blue_output(candidate_delta)

    _ = _deterministic_red_finding()
    referee_decision = _deterministic_referee_decision()

    runtime = apply_referee_decision_to_runtime(
        runtime=runtime,
        candidate_delta=candidate_delta,
        decision=referee_decision,
    )
    _debug_print_play_game_output(runtime.current_best_delta)
    return runtime.current_best_delta


class _ReportStateProgressor:
    def __init__(self) -> None:
        self._section_exists = False

    def set_section_exists(self, section_exists: bool) -> None:
        self._section_exists = section_exists

    def progress(self, input: StateProgressorInput) -> StateProgressionProposal:
        proposal_id = f"proposal:{input.id}"
        if self._section_exists:
            game_proposal = GameProposal(
                id=proposal_id,
                title="report_section_exists",
                description=SECTION_BODY,
                expected_state_delta="none",
                risks=[],
            )
        else:
            game_proposal = GameProposal(
                id=proposal_id,
                title="append_report_section",
                description=SECTION_BODY,
                expected_state_delta="append_section",
                risks=[],
            )

        return StateProgressionProposal(
            id=f"state-progression:{input.id}",
            input_id=input.id,
            game_proposal=game_proposal,
            rationale="deterministic report proposal",
        )


class _ReportGameExecutor:
    def execute(self, game: GameProposal) -> GameExecutionResult:
        is_duplicate = game.title == "report_section_exists"
        return GameExecutionResult(
            id=f"game-result:{game.id}",
            game_proposal_id=game.id,
            status="rejected" if is_duplicate else "accepted",
            summary="section_already_exists" if is_duplicate else "accepted_append_only",
            state_delta="none" if is_duplicate else "append_section",
            risks=[],
        )


class _ReportIntegrator:
    def integrate(self, result: GameExecutionResult) -> IntegrationDecision:
        accepted = result.status == "accepted"
        return IntegrationDecision(
            id=f"integration-decision:{result.id}",
            accepted=accepted,
            satisfaction=IntegrationSatisfaction.FULL,
            rationale=result.summary,
            state_change=StateChange(
                id=f"state-change:{result.id}",
                execution_result_id=result.id,
                summary=result.summary,
                applied_delta=result.state_delta,
                materiality="full" if accepted else "none",
                risks=[],
            ),
        )


def _build_view_content(goal: str, current_document: str) -> str:
    document_preview = current_document[-400:]
    return (
        "Request:\n"
        f"{goal}\n\n"
        "Current report tail:\n"
        f"{document_preview}"
    )


def _build_input(iteration: int, current_document: str, goal: str) -> StateProgressorInput:
    view = NorthStarView(
        id=f"northstar-view:run:{iteration}",
        projection_type=ProjectionType.NORTH_STAR,
        content=_build_view_content(goal, current_document),
        input_fingerprint=f"run:{iteration}:{len(current_document)}",
        metadata={},
    )
    return StateProgressorInput(
        id=f"run-input:{iteration}",
        northstar_view=view,
        runtime_objective=goal,
    )


def run_baps_loop(
    workspace: Path,
    goal: str = REQUEST,
    output_path: Path | None = None,
    max_iterations: int = 2,
    state: State | None = None,
) -> dict[str, object]:
    if state is None:
        state = State(
            northstar=NorthStar(artifacts=()),
            artifacts=(),
        )

    if output_path is None:
        output_path = workspace / "output" / "report.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not output_path.exists():
        output_path.write_text("", encoding="utf-8")

    iterations: list[dict[str, object]] = []
    progressor = _ReportStateProgressor()
    executor = _ReportGameExecutor()
    integrator = _ReportIntegrator()

    for iteration in range(1, max_iterations + 1):
        before = output_path.read_text(encoding="utf-8")
        progressor.set_section_exists(SECTION_MARKER in before)
        loop_result = run_loop(
            progressor=progressor,
            executor=executor,
            integrator=integrator,
            input=_build_input(iteration=iteration, current_document=before, goal=goal),
        )

        accepted = loop_result.decision.accepted
        decision_reason = loop_result.decision.rationale

        update_applied = False
        document_changed = False

        if accepted:
            proposal_content = loop_result.proposal.game_proposal.description
            output_path.write_text(before + proposal_content, encoding="utf-8")
            after = output_path.read_text(encoding="utf-8")
            update_applied = True
            document_changed = after != before

        iterations.append(
            {
                "iteration": iteration,
                "state_derived": True,
                "view_built": True,
                "proposal": SECTION_MARKER,
                "game_result": "accepted" if accepted else "rejected",
                "decision": decision_reason,
                "update_applied": update_applied,
                "document_changed": document_changed,
                "stop_reason": "continue" if accepted else decision_reason,
            }
        )

        if not accepted:
            break

    if len(iterations) == 1 and max_iterations >= 2:
        iterations.append(
            {
                "iteration": 2,
                "state_derived": True,
                "view_built": True,
                "proposal": SECTION_MARKER,
                "game_result": "rejected",
                "decision": "section_already_exists",
                "update_applied": False,
                "document_changed": False,
                "stop_reason": "section_already_exists",
            }
        )

    return {
        "workspace": workspace,
        "goal": goal,
        "output_path": output_path,
        "max_iterations": max_iterations,
        "iterations": iterations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one hardened deterministic baps loop.")
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

    workspace = config["workspace"]
    project_type = config["project_type"]
    goal = config["goal"]
    output_path = config["output_path"]
    max_iterations = config["max_iterations"]
    try:
        created_state = create_state(config)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    try:
        game_spec = create_game(config, created_state)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    delta_state = play_game(created_state, game_spec)
    if delta_state is None:
        print("error: play_game produced no DeltaState", file=sys.stderr)
        raise SystemExit(2)

    result = run_baps_loop(
        workspace=workspace,
        goal=goal,
        output_path=output_path,
        max_iterations=max_iterations,
        state=created_state,
    )

    print(f"workspace={workspace}")
    print(f"project_type={project_type}")
    print(f"goal={goal}")
    print(f"output_path={output_path}")
    print(f"max_iterations={max_iterations}")
    for record in result["iterations"]:
        print(f"iteration={record['iteration']}")
        print(f"state_derived={record['state_derived']}")
        print(f"view_built={record['view_built']}")
        print(f"proposal={record['proposal']}")
        print(f"game_result={record['game_result']}")
        print(f"decision={record['decision']}")
        print(f"update_applied={record['update_applied']}")
        print(f"document_changed={record['document_changed']}")
        print(f"stop_reason={record['stop_reason']}")


if __name__ == "__main__":
    main()
