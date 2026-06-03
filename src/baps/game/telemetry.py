"""Writes create_game, play_game, integration, and NorthStar events to the append-only blackboard."""

from __future__ import annotations 

import datetime 
import json 
import logging 
from pathlib import Path 

from baps .adapters .project_adapter import VerificationResult ,sanitize_model_string 
from baps .models .model_output import BlackboardEvent 
from baps .models .models import ModelClient 
from baps .state .state import DeltaState ,GameSpec 

from typing import TYPE_CHECKING 
if TYPE_CHECKING :
    from baps .game .attempt import PlayAttemptRecord 

logger =logging .getLogger (__name__ )

_BLACKBOARD_DIR ="blackboard"
_NORTHSTAR_PROPOSALS_FILE ="northstar_proposals.jsonl"
_GAMES_FILE ="games.jsonl"
VERIFICATION_SUMMARY_CAP =500 


def sanitize_feedback_dict (d :dict )->dict :
    """Recursively sanitize string values in a dict by stripping prompt-injection patterns."""
    result ={}
    for k ,v in d .items ():
        if isinstance (v ,str ):
            result [k ]=sanitize_model_string (v )
        elif isinstance (v ,list ):
            result [k ]=[sanitize_model_string (i )if isinstance (i ,str )else i for i in v ]
        elif isinstance (v ,dict ):
            result [k ]=sanitize_feedback_dict (v )
        else :
            result [k ]=v 
    return result 


def summarize_verification_result (result :VerificationResult |None )->dict |None :
    """Return a truncated summary dict of a VerificationResult, or None if result is None."""
    if result is None :
        return None 
    return {
    "passed":result .passed ,
    "exit_code":result .exit_code ,
    "stdout_summary":result .stdout [:VERIFICATION_SUMMARY_CAP ]if result .stdout else None ,
    "stderr_summary":result .stderr [:VERIFICATION_SUMMARY_CAP ]if result .stderr else None ,
    }


def sanitize_game_spec_dict (game_spec :GameSpec )->dict :
    """Return a sanitized dict representation of a GameSpec for safe blackboard writing."""
    return {
    "objective":sanitize_model_string (game_spec .objective ),
    "target_artifact_id":game_spec .target_artifact_id ,
    "allowed_delta_type":game_spec .allowed_delta_type ,
    "success_condition":sanitize_model_string (game_spec .success_condition ),
    "max_words":game_spec .max_words ,
    "target_entity":(
    sanitize_model_string (game_spec .target_entity )
    if game_spec .target_entity is not None
    else None
    ),
    }


def append_northstar_proposal_to_blackboard (
workspace :Path ,rationale :str ,proposed_northstar :str 
)->None :
    """Append a NorthStar update proposal entry to the northstar_proposals.jsonl blackboard file."""
    blackboard_dir =workspace /_BLACKBOARD_DIR 
    blackboard_dir .mkdir (parents =True ,exist_ok =True )
    entry ={
    "event":BlackboardEvent .NORTHSTAR_UPDATE_PROPOSAL ,
    "rationale":sanitize_model_string (rationale ),
    "proposed_northstar":sanitize_model_string (proposed_northstar ),
    "created_at":datetime .datetime .now (datetime .UTC ).isoformat (),
    }
    proposals_path =blackboard_dir /_NORTHSTAR_PROPOSALS_FILE 
    with proposals_path .open ("a",encoding ="utf-8")as f :
        f .write (json .dumps (entry )+"\n")


def append_game_to_blackboard (
workspace :Path ,
game_id :str ,
depth :int ,
game_spec :GameSpec ,
attempt_records :list [PlayAttemptRecord ],
final_disposition :str ,
verification_result :VerificationResult |None ,
current_best_delta :DeltaState |None ,
integration_eligible_delta :DeltaState |None ,
)->None :
    """Append a completed play_game record to the games.jsonl blackboard file."""
    blackboard_dir =workspace /_BLACKBOARD_DIR 
    blackboard_dir .mkdir (parents =True ,exist_ok =True )
    entry ={
    "event":BlackboardEvent .PLAY_GAME ,
    "game_id":game_id ,
    "created_at":datetime .datetime .now (datetime .UTC ).isoformat (),
    "depth":depth ,
    "context_chain":list (game_spec .context_chain ),
    "game_spec":sanitize_game_spec_dict (game_spec ),
    "attempts":[r .to_telemetry_dict ()for r in attempt_records ],
    "final_disposition":final_disposition ,
    "verification_result":summarize_verification_result (verification_result ),
    "current_best_delta":(
    None 
    if current_best_delta is None 
    else sanitize_feedback_dict (current_best_delta .model_dump (mode ="json"))
    ),
    "integration_eligible_delta":(
    None 
    if integration_eligible_delta is None 
    else sanitize_feedback_dict (integration_eligible_delta .model_dump (mode ="json"))
    ),
    }
    games_path =blackboard_dir /_GAMES_FILE 
    with games_path .open ("a",encoding ="utf-8")as f :
        f .write (json .dumps (entry )+"\n")


def append_create_game_to_blackboard (
workspace :Path ,
depth :int ,
context_chain :tuple [str ,...],
state_view_fingerprint :str ,
result_type :str ,
result :dict |None ,
model_used :str ,
)->None :
    """Append a create_game event record (game_spec, no_new_game, or decompose) to games.jsonl."""
    blackboard_dir =workspace /_BLACKBOARD_DIR 
    blackboard_dir .mkdir (parents =True ,exist_ok =True )
    entry ={
    "event":BlackboardEvent .CREATE_GAME ,
    "created_at":datetime .datetime .now (datetime .UTC ).isoformat (),
    "depth":depth ,
    "context_chain":list (context_chain ),
    "state_view_fingerprint":state_view_fingerprint ,
    "result_type":result_type ,
    "result":result ,
    "model_used":model_used ,
    }
    games_path =blackboard_dir /_GAMES_FILE 
    with games_path .open ("a",encoding ="utf-8")as f :
        f .write (json .dumps (entry )+"\n")


def append_integration_to_blackboard (
workspace :Path ,
depth :int ,
proposal_id :str ,
proposal_summary :str ,
state_changed :bool ,
delta_type :str ,
)->None :
    """Append a state-integration event record to the games.jsonl blackboard file."""
    blackboard_dir =workspace /_BLACKBOARD_DIR 
    blackboard_dir .mkdir (parents =True ,exist_ok =True )
    entry ={
    "event":BlackboardEvent .INTEGRATION ,
    "created_at":datetime .datetime .now (datetime .UTC ).isoformat (),
    "depth":depth ,
    "proposal_id":proposal_id ,
    "proposal_summary":sanitize_model_string (proposal_summary ),
    "state_changed":state_changed ,
    "delta_type":delta_type ,
    }
    games_path =blackboard_dir /_GAMES_FILE 
    with games_path .open ("a",encoding ="utf-8")as f :
        f .write (json .dumps (entry )+"\n")


def client_model_name (client :ModelClient )->str :
    """Return the model name attribute of a client, falling back to the class name."""
    return getattr (client ,"model",type (client ).__name__ )
