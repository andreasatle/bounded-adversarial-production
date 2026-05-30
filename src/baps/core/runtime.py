"""Assembles the RuntimeContext and wires together all runtime dependencies for a baps run."""

from __future__ import annotations 

from dataclasses import dataclass 
from pathlib import Path 

from baps .adapters .project_adapter import (
ProjectTypeAdapter ,
resolve_project_type_adapter ,
)
from baps .core .clients import SpecRole ,build_client_for_role ,resolve_backend_model 
from baps .core .debug import debug_print_create_state 
from baps .core .orchestration import IterationRunResult ,run_project_iterations 
from baps .core .run_config import RunConfig 
from baps .core .workspace import (
save_workspace_settings ,
state_path_for_workspace ,
)
from baps .models .models import Role 
from baps .state .state import State ,build_default_state_artifact_registry 
from baps .state .state_service import StateService 
from baps .state .state_store import JsonStateStore 
from baps .summarizer .summarizer import SummarizationContext 


@dataclass (frozen =True )
class RuntimeContext :
    """Immutable bundle of all resolved runtime dependencies for a single baps run."""
    config :RunConfig 
    adapter :ProjectTypeAdapter 
    state_service :StateService 
    initial_state :State 
    summarization_context :SummarizationContext 


def create_state (config :RunConfig )->State :
    """Create and return a new initial State via the adapter for the configured project type."""
    adapter =resolve_project_type_adapter (config .project_type )
    state =adapter .create_initial_state (config .to_adapter_config ())
    debug_print_create_state (config =config ,state =state )
    return state 


def _build_project_type_adapters ()->dict [str ,ProjectTypeAdapter ]:
    """Return the default mapping of project type names to adapter instances."""
    from baps .adapters .project_adapter import build_default_project_type_adapters 

    return build_default_project_type_adapters ()


def _resolve_project_type_adapter (project_type :str )->ProjectTypeAdapter :
    """Return the adapter for the given project type name, raising ValueError if unknown."""
    return resolve_project_type_adapter (project_type )


def _initialize_project (
config :RunConfig ,
create_state_fn =None ,
)->tuple [StateService ,State ]:
    """Create initial State, persist it, save workspace settings, and return (StateService, State)."""
    if create_state_fn is None :
        create_state_fn =create_state 
    workspace =config .workspace 
    initial_state =create_state_fn (config )
    state_store =JsonStateStore (state_path_for_workspace (workspace ))
    state_store .save (initial_state )
    save_workspace_settings (config ,workspace )
    service =StateService (
    store =state_store ,
    registry =build_default_state_artifact_registry (),
    )
    return service ,initial_state 


def _load_project_service (workspace :Path )->StateService :
    """Build and return a StateService backed by the existing JSON state file in workspace."""
    return StateService (
    store =JsonStateStore (state_path_for_workspace (workspace )),
    registry =build_default_state_artifact_registry (),
    )


def prepare_workspace (
config :RunConfig ,
create_state_fn =None ,
)->tuple [StateService ,State ]:
    """Load existing state if present, otherwise initialise a fresh project; return (StateService, State)."""
    if create_state_fn is None :
        create_state_fn =create_state 
    state_path =state_path_for_workspace (config .workspace )
    if state_path .exists ():
        state_service =_load_project_service (config .workspace )
        return state_service ,state_service .load_state ()
    return _initialize_project (config ,create_state_fn =create_state_fn )


def _resolve_summarize_role (config :RunConfig )->Role |None :
    """Return a Role for the summarize spec role if configured, otherwise None."""
    if SpecRole .SUMMARIZE not in (config .spec_roles or {}):
        return None 
    try :
        client =build_client_for_role (SpecRole .SUMMARIZE ,config )
        return Role (name =SpecRole .SUMMARIZE ,client =client )
    except ValueError :
        return None 


def build_runtime (
config :RunConfig ,
create_state_fn =None ,
)->RuntimeContext :
    """Assemble and return a fully resolved RuntimeContext for the given config."""
    if create_state_fn is None :
        create_state_fn =create_state 
    adapter =_resolve_project_type_adapter (config .project_type )
    state_service ,current_state =prepare_workspace (config ,create_state_fn =create_state_fn )
    summarizer =_resolve_summarize_role (config )
    return RuntimeContext (
    config =config ,
    adapter =adapter ,
    state_service =state_service ,
    initial_state =current_state ,
    summarization_context =SummarizationContext (summarizer =summarizer ,game_spec =None ),
    )


def run_project (runtime :RuntimeContext )->IterationRunResult :
    """Execute the project iteration loop using the assembled runtime and return the result."""
    return run_project_iterations (
    config =runtime .config ,
    adapter =runtime .adapter ,
    state_service =runtime .state_service ,
    initial_state =runtime .initial_state ,
    summarization_context =runtime .summarization_context ,
    )


def active_model_info (config :RunConfig |None =None )->dict [str ,str ]:
    """Return a dict with 'backend' and 'model' for the active blue role, or 'unknown' on error."""
    if config is None :
        return {"backend":"unknown","model":"unknown"}
    try :
        backend ,model =resolve_backend_model (SpecRole .BLUE ,config )
        return {"backend":backend ,"model":model }
    except ValueError :
        return {"backend":"unknown","model":"unknown"}
