"""Builds CreateGame and PlayGame StateViews for coding-type projects."""

from __future__ import annotations 

from typing import TYPE_CHECKING ,Any 

from baps .adapters .project_adapter import config_artifact_id ,config_northstar_markdown ,sanitize_model_string ,sanitize_model_title 
from baps .northstar .northstar_projection import ProjectionType ,StateView ,assemble_state_view 
from baps .state .state import GameSpec ,State 

if TYPE_CHECKING :
    from baps .summarizer .summarizer import SummarizationContext 

from .common import coding_artifact_from_state ,plugin_for 


def _render_api_summary (file ,plugin )->tuple [str ,str ]:
    """Return (label, content) for deterministic structural summary of a file."""
    try :
        api_text =plugin .extract_api (file )
    except Exception :# noqa: BLE001
        api_text =""
    if (
    isinstance (api_text ,str )
    and api_text .strip ()
    and api_text .strip ()!=file .content .strip ()
    ):
        return "api",sanitize_model_string (api_text )
    return (
    "api-empty",
    "No structural API signatures were extracted for this file. "
    "Use research tools (fetch_module/fetch_entity) for deeper inspection.",
    )


def build_coding_create_game_state_view (
state :State ,
config :dict [str ,Any ],
summarization_context :SummarizationContext |None =None ,
)->StateView :
    """Build the CreateGame StateView for a coding project, including NorthStar and current files."""
    del summarization_context 
    artifact_id =config_artifact_id (config )
    target_artifact =coding_artifact_from_state (state ,artifact_id )
    language =(
    str (config .get ("language"))
    if config .get ("language")
    else target_artifact .language 
    )
    plugin =plugin_for (language )
    northstar_content =config_northstar_markdown (config )

    file_lines :list [str ]=[]
    if target_artifact .files :
        for file in target_artifact .files :
            lines =file .content .splitlines ()
            line_count =len (lines )
            file_lines .append (f"### {sanitize_model_title (file .path )} ({line_count } lines)")
            file_lines .append ("")
            label ,summary =_render_api_summary (file ,plugin )
            file_lines .append (f"[{label }]")
            file_lines .append ("")
            file_lines .append (summary )
            file_lines .append ("")
    else :
        file_lines .append ("No files.")

    return assemble_state_view (
    stage ="create-game",
    artifact_id =target_artifact .id ,
    projection_type =ProjectionType .CREATE_GAME ,
    inner_lines =[
    "--- NorthStar ---",
    "",
    northstar_content if northstar_content else "No NorthStar content.",
    "",
    "--- State Artifacts ---",
    "",
    f"## Artifact: {target_artifact .id }",
    "",
    f"kind: {target_artifact .kind }",
    f"files: {len (target_artifact .files )}",
    "",
    "### Current Files",
    "",
    *file_lines ,
    ],
    metadata ={
    "target_artifact_id":target_artifact .id ,
    "language":target_artifact .language ,
    "files":[file .model_dump (mode ="json")for file in target_artifact .files ],
    },
    )


def build_coding_state_view (
state :State ,
game_spec :GameSpec ,
summarization_context :SummarizationContext |None =None ,
)->StateView :
    """Build the PlayGame StateView for a coding project, with per-file summaries when a summarizer is available."""
    del summarization_context 
    artifact =coding_artifact_from_state (state ,game_spec .target_artifact_id )
    plugin =plugin_for (artifact .language )
    target_entity =game_spec .target_entity 
    known_paths ={file .path for file in artifact .files }
    matched_target =target_entity is not None and target_entity in known_paths
    file_lines :list [str ]=[]
    if target_entity is not None and not matched_target :
        file_lines .append ("WARNING: target_entity did not match any known file.")
        file_lines .append (f"target_entity: {sanitize_model_title (target_entity )}")
        file_lines .append ("No full file was expanded; rendering compact structural views for all files.")
        file_lines .append ("")
    if artifact .files :
        for file in artifact .files :
            line_count =len (file .content .splitlines ())
            if matched_target and file .path ==target_entity :
                file_lines .append (f"### {sanitize_model_title (file .path )} ({line_count } lines) [full]")
                file_lines .append ("")
                fence ="````"if "```"in file .content else "```"
                file_lines .append (fence )
                file_lines .append (sanitize_model_string (file .content ))
                file_lines .append (fence )
                file_lines .append ("")
                continue 
            file_lines .append (f"### {sanitize_model_title (file .path )} ({line_count } lines) [api]")
            file_lines .append ("")
            label ,summary =_render_api_summary (file ,plugin )
            if label !="api":
                file_lines .append (f"[{label }]")
                file_lines .append ("")
            file_lines .append (summary )
            file_lines .append ("")
    else :
        file_lines .append ("No files.")

    return assemble_state_view (
    stage ="blue",
    artifact_id =artifact .id ,
    projection_type =ProjectionType .PLAY_GAME ,
    inner_lines =[
    "--- State Artifacts ---",
    "",
    f"## Artifact: {artifact .id }",
    "",
    f"kind: {artifact .kind }",
    "",
    "### Current Files",
    "",
    *file_lines ,
    ],
    metadata ={
    "target_artifact_id":artifact .id ,
    "language":artifact .language ,
    "files":[file .model_dump (mode ="json")for file in artifact .files ],
    },
    )
