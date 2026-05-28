from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from baps.adapters.project_adapter import (
    ProjectTypeAdapter,
    resolve_adapter_for_allowed_delta_type,
    resolve_project_type_adapter,
)
from baps.core.clients import SpecRole, _resolve_backend_model
from baps.core.debug import _debug_print_create_state
from baps.core.orchestration import _run_project_iterations
from baps.core.run_config import RunConfig
from baps.core.workspace import (
    save_workspace_settings,
    state_path_for_workspace,
)
from baps.state.state import State, build_default_state_artifact_registry
from baps.state.state_service import StateService
from baps.state.state_store import JsonStateStore


@dataclass(frozen=True)
class RuntimeContext:
    config: RunConfig
    adapter: ProjectTypeAdapter
    state_service: StateService
    initial_state: State


def create_state(config: RunConfig) -> State:
    adapter = resolve_project_type_adapter(config.project_type)
    state = adapter.create_initial_state(config.to_adapter_config())
    _debug_print_create_state(config=config, state=state)
    return state


def _build_project_type_adapters() -> dict[str, ProjectTypeAdapter]:
    from baps.adapters.project_adapter import build_default_project_type_adapters

    return build_default_project_type_adapters()


def _resolve_project_type_adapter(project_type: str) -> ProjectTypeAdapter:
    return resolve_project_type_adapter(project_type)


def _resolve_adapter_for_allowed_delta_type(allowed_delta_type: str) -> ProjectTypeAdapter:
    return resolve_adapter_for_allowed_delta_type(allowed_delta_type)


def _initialize_project(
    config: RunConfig,
    create_state_fn=None,
) -> tuple[StateService, State]:
    if create_state_fn is None:
        create_state_fn = create_state
    workspace = config.workspace
    initial_state = create_state_fn(config)
    state_store = JsonStateStore(state_path_for_workspace(workspace))
    state_store.save(initial_state)
    save_workspace_settings(config, workspace)
    service = StateService(
        store=state_store,
        registry=build_default_state_artifact_registry(),
    )
    return service, initial_state


def _load_project_service(workspace: Path) -> StateService:
    return StateService(
        store=JsonStateStore(state_path_for_workspace(workspace)),
        registry=build_default_state_artifact_registry(),
    )


def prepare_workspace(
    config: RunConfig,
    create_state_fn=None,
) -> tuple[StateService, State]:
    if create_state_fn is None:
        create_state_fn = create_state
    state_path = state_path_for_workspace(config.workspace)
    if state_path.exists():
        state_service = _load_project_service(config.workspace)
        return state_service, state_service.load_state()
    return _initialize_project(config, create_state_fn=create_state_fn)


def build_runtime(
    config: RunConfig,
    create_state_fn=None,
) -> RuntimeContext:
    if create_state_fn is None:
        create_state_fn = create_state
    adapter = _resolve_project_type_adapter(config.project_type)
    state_service, current_state = prepare_workspace(config, create_state_fn=create_state_fn)
    return RuntimeContext(
        config=config,
        adapter=adapter,
        state_service=state_service,
        initial_state=current_state,
    )


def run_project(runtime: RuntimeContext) -> dict[str, object]:
    return _run_project_iterations(
        config=runtime.config,
        adapter=runtime.adapter,
        state_service=runtime.state_service,
        initial_state=runtime.initial_state,
    )


def active_model_info(config: RunConfig | None = None) -> dict[str, str]:
    if config is None:
        return {"backend": "unknown", "model": "unknown"}
    try:
        backend, model = _resolve_backend_model(SpecRole.BLUE, config)
        return {"backend": backend, "model": model}
    except ValueError:
        return {"backend": "unknown", "model": "unknown"}
