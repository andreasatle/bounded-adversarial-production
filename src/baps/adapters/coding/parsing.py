"""Parses and validates Blue model output into typed coding delta objects."""

from __future__ import annotations 

import ast 
import json 
import re 
from pathlib import Path 

from baps .models .model_output import extract_json_candidate ,parse_model_output 
from baps .state .state import DeltaCodingBatchState ,DeltaCodingState ,DeltaDeleteCodingState 

from .common import BLUE_CONTENT_FORBIDDEN_MARKERS ,validate_file_path 

_BLUE_CODING_KEYS =frozenset ({"artifact_id","operation","payload"})


def _fix_one_file_content_quotes (file_data :dict )->None :
    """Fix escaped double-quotes in a single file dict's content field if safe to do so."""
    content =file_data .get ("content")
    path =file_data .get ("path")
    if not isinstance (content ,str )or '\\"'not in content :
        return 
    if "\n"not in content :
        file_data ["content"]=content .replace ('\\"','"')
        return 
    if not isinstance (path ,str )or not path .endswith (".py"):
        return 
    try :
        ast .parse (content )
        return 
    except SyntaxError :
        candidate =content .replace ('\\"','"')
        try :
            ast .parse (candidate )
            file_data ["content"]=candidate 
        except SyntaxError :
            pass 


def _fix_delta_file_content_quotes (parsed :dict )->None :
    """Apply quote-fixing to all file content fields in a parsed coding delta dict."""
    operation =parsed .get ("operation")
    payload =parsed .get ("payload")
    if not isinstance (payload ,dict ):
        return 
    if operation =="write_files":
        files =payload .get ("files")
        if not isinstance (files ,list ):
            return 
        for file_data in files :
            if isinstance (file_data ,dict ):
                _fix_one_file_content_quotes (file_data )
        return 
    file_data =payload .get ("file")
    if isinstance (file_data ,dict ):
        _fix_one_file_content_quotes (file_data )


def validate_coding_write_file_artifact_purity (delta :DeltaCodingState )->None :
    """Raise ValueError if the write_file delta contains an unsafe path or forbidden reasoning markers."""
    validate_file_path (delta .payload .file .path )
    lowered =delta .payload .file .content .lower ()
    for marker in BLUE_CONTENT_FORBIDDEN_MARKERS :
        if marker .lower ()in lowered :
            raise ValueError (
            "blue model output failed DeltaCodingState validation: "
            f"write_file content contains forbidden reasoning marker {marker !r }"
            )


def validate_coding_write_files_purity (delta :DeltaCodingBatchState )->None :
    """Raise ValueError if any file in a write_files delta has an unsafe path or forbidden marker."""
    for code_file in delta .payload .files :
        validate_file_path (code_file .path )
        lowered =code_file .content .lower ()
        for marker in BLUE_CONTENT_FORBIDDEN_MARKERS :
            if marker .lower ()in lowered :
                raise ValueError (
                "blue model output failed DeltaCodingBatchState validation: "
                f"write_files file {code_file .path !r } contains forbidden reasoning marker {marker !r }"
                )


def _recover_malformed_coding_delta_json (text :str )->dict [str ,object ]|None :
    """Attempt to reconstruct a valid coding delta dict from malformed JSON text, or return None."""
    artifact_match =re .search (r'"artifact_id"\s*:\s*"([^"]+)"',text )
    operation_match =re .search (r'"operation"\s*:\s*"([^"]+)"',text )
    path_match =re .search (r'"path"\s*:\s*"([^"]+)"',text )
    content_start_match =re .search (r'"content"\s*:\s*"',text )
    if (
    artifact_match is None 
    or operation_match is None 
    or path_match is None 
    or content_start_match is None 
    ):
        return None 

    start =content_start_match .end ()
    remainder =text [start :]
    end_patterns =(
    re .compile (r'"\s*}\s*}\s*}\s*$',re .DOTALL ),
    re .compile (r'"\s*}\s*}\s*$',re .DOTALL ),
    re .compile (r'"\s*}\s*$',re .DOTALL ),
    )
    end_index :int |None =None 
    for pattern in end_patterns :
        match =pattern .search (remainder )
        if match is not None :
            end_index =match .start ()
            break 
    if end_index is None :
        return None 

    raw_content =remainder [:end_index ]
    escaped_content =(
    raw_content .replace ("\\","\\\\")
    .replace ('"','\\"')
    .replace ("\r","\\r")
    .replace ("\n","\\n")
    .replace ("\t","\\t")
    )
    reconstructed =(
    "{"
    f'"artifact_id":"{artifact_match .group (1 )}",'
    f'"operation":"{operation_match .group (1 )}",'
    '"payload":{"file":{'
    f'"path":"{path_match .group (1 )}",'
    f'"content":"{escaped_content }"'
    "}}"
    "}"
    )
    try :
        parsed =json .loads (reconstructed )
    except json .JSONDecodeError :
        return None 
    if not isinstance (parsed ,dict ):
        return None 
    return parsed 


def parse_coding_delta_json (text :str ,workspace :Path |None =None )->DeltaCodingState |DeltaCodingBatchState :
    """Parse Blue model text output into a validated coding delta, with malformed-JSON recovery."""
    try :
        parsed ,_ =parse_model_output (text ,_BLUE_CODING_KEYS ,context ="blue:coding",workspace =workspace )
    except ValueError as exc :
        if "must be valid JSON"not in str (exc ):
            raise 
        parsed =_recover_malformed_coding_delta_json (extract_json_candidate (text ))
        if parsed is None :
            raise 
    if not _BLUE_CODING_KEYS .issubset (parsed .keys ()):
        raise ValueError ("blue model output must contain keys: artifact_id, operation, payload")

    _fix_delta_file_content_quotes (parsed )

    operation =parsed .get ("operation")
    if operation =="write_files":
        try :
            delta =DeltaCodingBatchState .model_validate (parsed )
        except Exception as exc :
            raise ValueError (
            f"blue model output failed DeltaCodingBatchState validation: {exc }"
            )from exc 
        validate_coding_write_files_purity (delta )
        return delta 

    if operation =="delete_file":
        try :
            delta_delete =DeltaDeleteCodingState .model_validate (parsed )
        except Exception as exc :
            raise ValueError (
            f"blue model output failed DeltaDeleteCodingState validation: {exc }"
            )from exc 
        validate_file_path (delta_delete .payload .path )
        return delta_delete 

    try :
        delta =DeltaCodingState .model_validate (parsed )
    except Exception as exc :
        raise ValueError (
        f"blue model output failed DeltaCodingState validation: {exc }"
        )from exc 
    validate_coding_write_file_artifact_purity (delta )
    return delta 
