"""Tests for all parsing logic: create_game output, red/referee JSON, delta JSON, pytest failures."""
from __future__ import annotations 

import json 
import logging 

import pytest 

from baps .core .parsers import (
NorthStarUpdateNeededError ,
parse_create_game_output ,
parse_red_finding_json ,
parse_referee_decision_json ,
)
import baps .state .state as state_module 


# ---------------------------------------------------------------------------
# NorthStar update-needed signal tests
# ---------------------------------------------------------------------------

def testparse_create_game_output_northstar_update_needed_raises_signal ()->None :
    raw =json .dumps ({
    "northstar_update_needed":True ,
    "rationale":"Accumulated state has drifted from NorthStar intent.",
    "proposed_northstar":"# Updated Goal\n\nNew direction.",
    })
    with pytest .raises (NorthStarUpdateNeededError )as exc_info :
        parse_create_game_output (raw )

    assert exc_info .value .rationale =="Accumulated state has drifted from NorthStar intent."
    assert exc_info .value .proposed_northstar =="# Updated Goal\n\nNew direction."


def testparse_create_game_output_northstar_update_needed_flag_false_falls_through_to_game_spec ()->None :
# false marker → not classified as northstar response; falls through to GameSpec missing-keys error
    raw =json .dumps ({
    "northstar_update_needed":False ,
    "rationale":"some reason",
    "proposed_northstar":"new northstar",
    })
    with pytest .raises (ValueError ,match ="missing required keys"):
        parse_create_game_output (raw )


def testparse_create_game_output_northstar_update_needed_empty_rationale_raises ()->None :
    raw =json .dumps ({
    "northstar_update_needed":True ,
    "rationale":"   ",
    "proposed_northstar":"new northstar",
    })
    with pytest .raises (ValueError ,match ="rationale must be non-empty"):
        parse_create_game_output (raw )


def testparse_create_game_output_northstar_update_needed_empty_proposed_northstar_raises ()->None :
    raw =json .dumps ({
    "northstar_update_needed":True ,
    "rationale":"valid rationale",
    "proposed_northstar":"   ",
    })
    with pytest .raises (ValueError ,match ="proposed_northstar must be non-empty"):
        parse_create_game_output (raw )


        # ---------------------------------------------------------------------------
        # Decompose spec parsing
        # ---------------------------------------------------------------------------

def testparse_create_game_output_returns_decompose_spec ()->None :
    from baps .state .state import DecomposeSpec 

    text =json .dumps ({
    "decompose":True ,
    "rationale":"Gap is too large",
    "sub_gaps":[
    {"description":"Implement auth module"},
    {"description":"Implement user model"},
    ],
    })
    result =parse_create_game_output (text )
    assert isinstance (result ,DecomposeSpec )
    assert result .rationale =="Gap is too large"
    assert len (result .sub_gaps )==2 
    assert result .sub_gaps [0 ].description =="Implement auth module"
    assert result .sub_gaps [1 ].description =="Implement user model"


def testparse_create_game_output_decompose_requires_non_empty_sub_gaps ()->None :
    text =json .dumps ({
    "decompose":True ,
    "rationale":"Too large",
    "sub_gaps":[],
    })
    with pytest .raises (ValueError ,match ="non-empty list"):
        parse_create_game_output (text )


def testparse_create_game_output_decompose_requires_rationale ()->None :
    text =json .dumps ({
    "decompose":True ,
    "rationale":"",
    "sub_gaps":[{"description":"x"}],
    })
    with pytest .raises (ValueError ,match ="rationale must be non-empty"):
        parse_create_game_output (text )


def testparse_create_game_output_truncates_sub_gaps_when_over_max ()->None :
    from baps .state .state import DecomposeSpec 

    sub_gaps =[{"description":f"Gap {i }"}for i in range (7 )]
    text =json .dumps ({"decompose":True ,"rationale":"Too large","sub_gaps":sub_gaps })
    result =parse_create_game_output (text ,max_sub_gaps =5 )
    assert isinstance (result ,DecomposeSpec )
    assert len (result .sub_gaps )==5 
    assert result .sub_gaps [0 ].description =="Gap 0"
    assert result .sub_gaps [4 ].description =="Gap 4"


def testparse_create_game_output_does_not_truncate_at_exactly_max ()->None :
    from baps .state .state import DecomposeSpec 

    sub_gaps =[{"description":f"Gap {i }"}for i in range (5 )]
    text =json .dumps ({"decompose":True ,"rationale":"Decomposing","sub_gaps":sub_gaps })
    result =parse_create_game_output (text ,max_sub_gaps =5 )
    assert isinstance (result ,DecomposeSpec )
    assert len (result .sub_gaps )==5 


def testparse_create_game_output_max_sub_gaps_1_allows_only_one ()->None :
    from baps .state .state import DecomposeSpec 

    sub_gaps =[{"description":"First"},{"description":"Second"}]
    text =json .dumps ({"decompose":True ,"rationale":"Big gap","sub_gaps":sub_gaps })
    result =parse_create_game_output (text ,max_sub_gaps =1 )
    assert isinstance (result ,DecomposeSpec )
    assert len (result .sub_gaps )==1 
    assert result .sub_gaps [0 ].description =="First"


def testparse_create_game_output_strips_empty_sub_gaps_and_logs_warning (
caplog :pytest .LogCaptureFixture ,
)->None :
    from baps .state .state import DecomposeSpec 

    sub_gaps =[
    {"description":"write the API"},
    {"description":""},
    {"description":"   "},
    ]
    text =json .dumps ({"decompose":True ,"rationale":"gap is large","sub_gaps":sub_gaps })
    with caplog .at_level (logging .WARNING ):
        result =parse_create_game_output (text ,max_sub_gaps =5 )
    assert isinstance (result ,DecomposeSpec )
    assert len (result .sub_gaps )==1 
    assert result .sub_gaps [0 ].description =="write the API"
    assert "stripped 2 sub-gap(s) with empty description"in caplog .text 


def testparse_create_game_output_all_empty_sub_gaps_no_fallback_raises ()->None :
    text =json .dumps ({
    "decompose":True ,
    "rationale":"gap is large",
    "sub_gaps":[{"description":""},{"description":"   "}],
    })
    with pytest .raises (ValueError ,match ="no valid entries"):
        parse_create_game_output (text ,max_sub_gaps =5 )


def testparse_create_game_output_all_empty_sub_gaps_with_fallback_escalates ()->None :
    from baps .state .state import DecomposeSpec 

    valid_decompose =json .dumps ({
    "decompose":True ,
    "rationale":"gap is large",
    "sub_gaps":[{"description":"write the implementation"}],
    })
    fallback_calls :list [str ]=[]

    def fallback_fn (prompt :str )->str :
        fallback_calls .append (prompt )
        return valid_decompose 

    text =json .dumps ({
    "decompose":True ,
    "rationale":"gap is large",
    "sub_gaps":[{"description":""},{"description":"   "}],
    })
    result =parse_create_game_output (text ,max_sub_gaps =5 ,fallback_fn =fallback_fn )
    assert isinstance (result ,DecomposeSpec )
    assert len (result .sub_gaps )==1 
    assert result .sub_gaps [0 ].description =="write the implementation"
    assert len (fallback_calls )==1 


def testparse_create_game_output_unrecognizable_shape_no_fallback_raises ()->None :
    text =json .dumps ({"something_unexpected":"value"})
    with pytest .raises (ValueError ,match ="missing required keys"):
        parse_create_game_output (text ,max_sub_gaps =5 )


def testparse_create_game_output_unrecognizable_shape_with_fallback_escalates ()->None :
    from baps .state .state import GameSpec 

    valid_game_spec =json .dumps ({
    "objective":"Close the gap",
    "target_artifact_id":"main-document",
    "allowed_delta_type":"DeltaDocumentState",
    "success_condition":"section present",
    })
    fallback_calls :list [str ]=[]

    def fallback_fn (prompt :str )->str :
        fallback_calls .append (prompt )
        return valid_game_spec 

    text =json .dumps ({"something_unexpected":"value"})
    result =parse_create_game_output (text ,max_sub_gaps =5 ,fallback_fn =fallback_fn )
    assert isinstance (result ,GameSpec )
    assert result .target_artifact_id =="main-document"
    assert len (fallback_calls )==1 


def testparse_create_game_output_unrecognizable_shape_fallback_logs_warning (
caplog :pytest .LogCaptureFixture ,
)->None :
    valid_game_spec =json .dumps ({
    "objective":"Close the gap",
    "target_artifact_id":"main-document",
    "allowed_delta_type":"DeltaDocumentState",
    "success_condition":"section present",
    })

    def fallback_fn (prompt :str )->str :
        return valid_game_spec 

    text =json .dumps ({"something_unexpected":"value"})
    with caplog .at_level (logging .WARNING ):
        parse_create_game_output (text ,max_sub_gaps =5 ,fallback_fn =fallback_fn )
    assert "unrecognizable response shape"in caplog .text 


def testparse_create_game_output_unrecognizable_shape_with_retry_fn_retries ()->None :
    from baps .state .state import GameSpec

    valid_game_spec =json .dumps ({
    "objective":"Close the gap",
    "target_artifact_id":"main-document",
    "allowed_delta_type":"DeltaDocumentState",
    "success_condition":"section present",
    })
    retry_calls :list [str ]=[]

    def retry_fn (prompt :str )->str :
        retry_calls .append (prompt )
        return valid_game_spec

    text =json .dumps ({"something_unexpected":"value"})
    result =parse_create_game_output (text ,max_sub_gaps =5 ,retry_fn =retry_fn )
    assert isinstance (result ,GameSpec )
    assert len (retry_calls )==1


def testparse_create_game_output_unexpected_status_key_triggers_retry ()->None :
    from baps .state .state import GameSpec

    valid_game_spec =json .dumps ({
    "objective":"Close the gap",
    "target_artifact_id":"main-document",
    "allowed_delta_type":"DeltaDocumentState",
    "success_condition":"section present",
    })
    retry_calls :list [str ]=[]

    def retry_fn (prompt :str )->str :
        retry_calls .append (prompt )
        return valid_game_spec

    # status is not in _CREATE_GAME_ALL_KEYS — stripped by parse_model_output,
    # leaving an empty dict that fails the shape check and should trigger retry
    text =json .dumps ({"status":"complete"})
    result =parse_create_game_output (text ,max_sub_gaps =5 ,retry_fn =retry_fn )
    assert isinstance (result ,GameSpec )
    assert len (retry_calls )==1


def testparse_create_game_output_correction_retry_no_new_game_escalates_to_fallback ()->None :
    """Correction retry returning no_new_game must not be accepted — fall through to fallback."""
    from baps .state .state import GameSpec

    valid_game_spec =json .dumps ({
    "objective":"Close the gap",
    "target_artifact_id":"main-document",
    "allowed_delta_type":"DeltaDocumentState",
    "success_condition":"section present",
    })
    fallback_calls :list [str ]=[]

    def retry_fn (prompt :str )->str :
        return json .dumps ({"no_new_game":True ,"reason":"nothing to do"})

    def fallback_fn (prompt :str )->str :
        fallback_calls .append (prompt )
        return valid_game_spec

    text =json .dumps ({"status":"complete"})
    result =parse_create_game_output (text ,retry_fn =retry_fn ,fallback_fn =fallback_fn )
    assert isinstance (result ,GameSpec )
    assert len (fallback_calls )==1


def testparse_create_game_output_correction_retry_no_new_game_no_fallback_raises ()->None :
    """Correction retry returning no_new_game with no fallback raises ValueError, not NoNewGameError."""
    from baps .core .parsers import NoNewGameError

    def retry_fn (prompt :str )->str :
        return json .dumps ({"no_new_game":True ,"reason":"nothing to do"})

    text =json .dumps ({"status":"complete"})
    with pytest .raises (ValueError ,match ="missing required keys"):
        parse_create_game_output (text ,retry_fn =retry_fn )


def testparse_create_game_output_correction_prompt_excludes_no_new_game ()->None :
    """The correction prompt must not list no_new_game as a valid option."""
    from baps .core .parsers import _UNRECOGNIZABLE_SHAPE_CORRECTION_PROMPT
    assert '"no_new_game": true'not in _UNRECOGNIZABLE_SHAPE_CORRECTION_PROMPT
    assert "Do not return no_new_game"in _UNRECOGNIZABLE_SHAPE_CORRECTION_PROMPT


# ---------------------------------------------------------------------------
# Ambiguity guard tests (mixed control-plane signals + GameSpec fields)
# ---------------------------------------------------------------------------

def testparse_create_game_output_no_new_game_with_gamespec_fields_raises ()->None :
    """A response mixing a terminal signal with GameSpec fields must not be silently resolved."""
    text =json .dumps ({
    "no_new_game":True ,
    "reason":"done",
    "objective":"Add intro section",
    "target_artifact_id":"doc-main",
    "allowed_delta_type":"append_section",
    "success_condition":"section present",
    })
    with pytest .raises (ValueError ):
        parse_create_game_output (text )


def testparse_create_game_output_multiple_terminal_signals_raises ()->None :
    """A response with two active terminal signals must not be resolved by silent priority."""
    text =json .dumps ({
    "no_new_game":True ,
    "reason":"done",
    "decompose":True ,
    "rationale":"too large",
    "sub_gaps":[{"description":"step one"}],
    })
    with pytest .raises (ValueError ):
        parse_create_game_output (text )


def testparse_create_game_output_northstar_and_decompose_signals_raises ()->None :
    """northstar_update_needed + decompose share the rationale key; mixed response must be rejected."""
    text =json .dumps ({
    "northstar_update_needed":True ,
    "decompose":True ,
    "rationale":"shared rationale",
    "proposed_northstar":"new direction",
    "sub_gaps":[{"description":"step one"}],
    })
    with pytest .raises (ValueError ):
        parse_create_game_output (text )


def testparse_create_game_output_ambiguous_retry_recovers_with_valid_gamespec ()->None :
    """Ambiguous response routes through shape-correction retry; valid GameSpec on retry succeeds."""
    from baps .state .state import GameSpec

    valid_game_spec =json .dumps ({
    "objective":"Add intro section",
    "target_artifact_id":"doc-main",
    "allowed_delta_type":"append_section",
    "success_condition":"section present",
    })
    retry_calls :list [str ]=[]

    def retry_fn (prompt :str )->str :
        retry_calls .append (prompt )
        return valid_game_spec

    text =json .dumps ({
    "no_new_game":True ,
    "reason":"done",
    "objective":"Add intro section",
    "target_artifact_id":"doc-main",
    "allowed_delta_type":"append_section",
    "success_condition":"section present",
    })
    result =parse_create_game_output (text ,retry_fn =retry_fn )
    assert isinstance (result ,GameSpec )
    assert len (retry_calls )==1


def testparse_create_game_output_fallback_returning_terminal_signal_is_blocked ()->None :
    """Fallback returning a terminal signal in shape-correction context must not propagate as NoNewGameError."""
    from baps .core .parsers import NoNewGameError

    def fallback_fn (prompt :str )->str :
        return json .dumps ({"no_new_game":True ,"reason":"nothing to do"})

    text =json .dumps ({"something_unexpected":"value"})
    with pytest .raises (ValueError ):
        parse_create_game_output (text ,fallback_fn =fallback_fn )
    # Specifically: NoNewGameError must not escape (it is a subclass of ValueError,
    # but the raised error must come from the shape-failure path, not the terminal path).
    try :
        parse_create_game_output (text ,fallback_fn =fallback_fn )
    except NoNewGameError :
        pytest .fail ("NoNewGameError must not escape from shape-correction fallback context")
    except ValueError :
        pass  # expected: shape failure, not terminal signal


def testparse_create_game_output_empty_dict_with_fallback_escalates ()->None :
    from baps .state .state import GameSpec 

    valid_game_spec =json .dumps ({
    "objective":"Close the gap",
    "target_artifact_id":"main-document",
    "allowed_delta_type":"DeltaDocumentState",
    "success_condition":"section present",
    })
    fallback_calls :list [str ]=[]

    def fallback_fn (prompt :str )->str :
        fallback_calls .append (prompt )
        return valid_game_spec 

        # Empty dict: all keys stripped as unexpected, leaving nothing
    text =json .dumps ({})
    result =parse_create_game_output (text ,max_sub_gaps =5 ,fallback_fn =fallback_fn )
    assert isinstance (result ,GameSpec )
    assert len (fallback_calls )==1 


def testparse_create_game_output_game_spec_with_false_marker_keys_and_extra_keys ()->None :
    from baps .state .state import GameSpec 

    # Local models (e.g. qwen2.5-coder) often include false-valued marker keys and
    # extra metadata like confidence in what is intended to be a GameSpec response.
    raw =json .dumps ({
    "objective":"Add introduction section",
    "target_artifact_id":"doc-main",
    "allowed_delta_type":"append_section",
    "success_condition":"Introduction section present",
    "no_new_game":False ,
    "decompose":False ,
    "confidence":0.95 ,
    })
    result =parse_create_game_output (raw )
    assert isinstance (result ,GameSpec )
    assert result .objective =="Add introduction section"


    # ---------------------------------------------------------------------------
    # parse_red_finding_json tests
    # ---------------------------------------------------------------------------

def test_red_finding_optional_fields_parse_when_present ()->None :
    red ,_ =parse_red_finding_json (
    '{"disposition":"revise","rationale":"needs work",'
    '"success_condition_met":false,'
    '"findings":["section body is too short","title duplicates existing section"]}'
    )
    assert red .disposition =="revise"
    assert red .success_condition_met is False 
    assert red .findings ==("section body is too short","title duplicates existing section")


def test_red_finding_defaults_when_optional_fields_absent ()->None :
    red ,_ =parse_red_finding_json (
    '{"disposition":"accept","rationale":"looks good"}'
    )
    assert red .success_condition_met is None 
    assert red .findings ==()


def test_red_finding_unexpected_key_stripped ()->None :
    red ,recovery =parse_red_finding_json (
    '{"disposition":"accept","rationale":"ok","confidence":0.9}'
    )
    assert red .disposition =="accept"
    assert not hasattr (red ,"confidence")
    assert "confidence"in recovery .unexpected_keys_stripped 


def test_red_finding_missing_required_key_rejected ()->None :
    with pytest .raises (ValueError ,match ="missing required keys"):
        parse_red_finding_json ('{"disposition":"accept"}')


        # ---------------------------------------------------------------------------
        # parse_referee_decision_json tests
        # ---------------------------------------------------------------------------

def test_referee_decision_optional_fields_parse_when_present ()->None :
    decision ,_ =parse_referee_decision_json (
    '{"disposition":"revise","rationale":"override Red",'
    '"red_override":true,'
    '"improvement_hints":["add concrete section body","cite NorthStar goal"]}'
    )
    assert decision .disposition =="revise"
    assert decision .red_override is True 
    assert decision .improvement_hints ==("add concrete section body","cite NorthStar goal")


def test_referee_decision_defaults_when_optional_fields_absent ()->None :
    decision ,_ =parse_referee_decision_json (
    '{"disposition":"accept","rationale":"approved"}'
    )
    assert decision .red_override is None 
    assert decision .improvement_hints ==()


def test_referee_decision_unexpected_key_stripped ()->None :
    decision ,recovery =parse_referee_decision_json (
    '{"disposition":"accept","rationale":"ok","confidence":0.9}'
    )
    assert decision .disposition =="accept"
    assert not hasattr (decision ,"confidence")
    assert "confidence"in recovery .unexpected_keys_stripped 


def test_referee_decision_missing_required_key_rejected ()->None :
    with pytest .raises (ValueError ,match ="missing required keys"):
        parse_referee_decision_json ('{"rationale":"ok"}')


        # ---------------------------------------------------------------------------
        # Coding delta JSON parsing
        # ---------------------------------------------------------------------------

def test_parse_coding_delta_json_handles_write_files_operation ()->None :
    from baps .adapters .coding_adapter import parse_coding_delta_json 

    text =json .dumps ({
    "artifact_id":"main-codebase",
    "operation":"write_files",
    "payload":{
    "files":[
    {"path":"src/a.py","content":"print('a')"},
    {"path":"src/b.py","content":"print('b')"},
    ]
    },
    })
    delta =parse_coding_delta_json (text )
    assert isinstance (delta ,state_module .DeltaCodingBatchState )
    assert delta .operation =="write_files"
    assert len (delta .payload .files )==2 


def test_parse_coding_delta_json_still_accepts_write_file_operation ()->None :
    from baps .adapters .coding_adapter import parse_coding_delta_json 

    text =json .dumps ({
    "artifact_id":"main-codebase",
    "operation":"write_file",
    "payload":{"file":{"path":"src/a.py","content":"x"}},
    })
    delta =parse_coding_delta_json (text )
    assert isinstance (delta ,state_module .DeltaCodingState )
    assert delta .operation =="write_file"


def test_parse_coding_delta_json_rejects_write_files_with_empty_files_list ()->None :
    from baps .adapters .coding_adapter import parse_coding_delta_json 

    text =json .dumps ({
    "artifact_id":"main-codebase",
    "operation":"write_files",
    "payload":{"files":[]},
    })
    with pytest .raises (ValueError ,match ="DeltaCodingBatchState"):
        parse_coding_delta_json (text )


def test_parse_coding_delta_json_handles_delete_file_operation ()->None :
    from baps .adapters .coding_adapter import parse_coding_delta_json 

    text =json .dumps ({
    "artifact_id":"main-codebase",
    "operation":"delete_file",
    "payload":{"path":"src/old.py"},
    })
    delta =parse_coding_delta_json (text )
    assert isinstance (delta ,state_module .DeltaDeleteCodingState )
    assert delta .payload .path =="src/old.py"


    # ---------------------------------------------------------------------------
    # Document delta JSON parsing
    # ---------------------------------------------------------------------------

def test_parse_document_delta_json_handles_modify_section_operation ()->None :
    from baps .adapters .document_adapter import parse_document_delta_json 

    text =json .dumps ({
    "artifact_id":"main-document",
    "operation":"modify_section",
    "payload":{"section_title":"Intro","new_body":"Updated intro."},
    })
    delta =parse_document_delta_json (text )
    assert isinstance (delta ,state_module .DeltaModifyDocumentState )
    assert delta .payload .section_title =="Intro"
    assert delta .payload .new_body =="Updated intro."


def test_parse_document_delta_json_still_accepts_append_section ()->None :
    from baps .adapters .document_adapter import parse_document_delta_json 

    text =json .dumps ({
    "artifact_id":"main-document",
    "operation":"append_section",
    "payload":{"section":{"title":"New","body":"Body."}},
    })
    delta =parse_document_delta_json (text )
    assert isinstance (delta ,state_module .DeltaDocumentState )


def test_parse_document_delta_json_handles_delete_section_operation ()->None :
    from baps .adapters .document_adapter import parse_document_delta_json 

    text =json .dumps ({
    "artifact_id":"main-document",
    "operation":"delete_section",
    "payload":{"section_title":"Obsolete"},
    })
    delta =parse_document_delta_json (text )
    assert isinstance (delta ,state_module .DeltaDeleteDocumentState )
    assert delta .payload .section_title =="Obsolete"


    # ---------------------------------------------------------------------------
    # Coding parse recovery tests
    # ---------------------------------------------------------------------------

def test_coding_parse_recovers_unescaped_quotes_in_content ()->None :
    import baps .adapters .coding_adapter as coding_module 

    raw =(
    '{"artifact_id":"main-codebase","operation":"write_file","payload":{"file":{'
    '"path":"tests/test_fibonacci.py",'
    '"content":"def test_msg():\n    assert "hello" == "hello"\n"}}}'
    )
    delta =coding_module .parse_coding_delta_json (raw )
    assert delta .artifact_id =="main-codebase"
    assert delta .payload .file .path =="tests/test_fibonacci.py"
    assert 'assert "hello" == "hello"'in delta .payload .file .content 


def test_coding_parse_recovers_multiline_pytest_content ()->None :
    import baps .adapters .coding_adapter as coding_module 

    raw =(
    '{"artifact_id":"main-codebase","operation":"write_file","payload":{"file":{'
    '"path":"tests/test_fibonacci.py",'
    '"content":"import pytest\n'
    'from src.fibonacci import fibonacci\n\n'
    'def test_values():\n'
    '    assert fibonacci(0) == 0\n'
    '    assert fibonacci(5) == 5\n"}}}'
    )
    delta =coding_module .parse_coding_delta_json (raw )
    assert "import pytest"in delta .payload .file .content 
    assert "assert fibonacci(5) == 5"in delta .payload .file .content 


def test_coding_parse_recovers_long_content_payload ()->None :
    import baps .adapters .coding_adapter as coding_module 

    long_lines =["def test_many():"]+[f"    assert {i } == {i }"for i in range (300 )]
    long_content ="\n".join (long_lines )
    raw =(
    '{"artifact_id":"main-codebase","operation":"write_file","payload":{"file":{'
    '"path":"tests/test_fibonacci.py",'
    f'"content":"{long_content }"'
    "}}}"
    )
    delta =coding_module .parse_coding_delta_json (raw )
    assert len (delta .payload .file .content .splitlines ())>=301 
    assert "assert 299 == 299"in delta .payload .file .content 


def test_coding_parse_rejects_reasoning_note_marker ()->None :
    import baps .adapters .coding_adapter as coding_module 

    raw =(
    '{"artifact_id":"main-codebase","operation":"write_file","payload":{"file":{'
    '"path":"tests/test_fibonacci.py",'
    '"content":"import pytest\\n# Note: choosing approach\\ndef test_ok():\\n    assert 1 == 1\\n"'
    "}}}"
    )
    with pytest .raises (ValueError ,match ="forbidden reasoning marker"):
        coding_module .parse_coding_delta_json (raw )


def test_coding_parse_rejects_self_correction_marker ()->None :
    import baps .adapters .coding_adapter as coding_module 

    raw =(
    '{"artifact_id":"main-codebase","operation":"write_file","payload":{"file":{'
    '"path":"tests/test_fibonacci.py",'
    '"content":"def test_ok():\\n    assert 1 == 1\\n# Correcting the above\\n"'
    "}}}"
    )
    with pytest .raises (ValueError ,match ="forbidden reasoning marker"):
        coding_module .parse_coding_delta_json (raw )


def test_coding_parse_rejects_rewriting_commentary_marker ()->None :
    import baps .adapters .coding_adapter as coding_module 

    raw =(
    '{"artifact_id":"main-codebase","operation":"write_file","payload":{"file":{'
    '"path":"tests/test_fibonacci.py",'
    '"content":"import pytest\\n# Re-writing content structure\\ndef test_ok():\\n    assert 1 == 1\\n"'
    "}}}"
    )
    with pytest .raises (ValueError ,match ="forbidden reasoning marker"):
        coding_module .parse_coding_delta_json (raw )


def test_coding_parse_fixes_double_escaped_quotes_in_single_line_content ()->None :
    import baps .adapters .coding_adapter as coding_module 

    # Model double-escaped quotes: after json.loads, content contains \" (backslash + quote)
    # instead of the intended ". Use json.dumps to build valid JSON with that content.
    content_with_escape ='def greet(): return \\"hello\\"'# literal: def greet(): return \"hello\"
    raw =json .dumps ({
    "artifact_id":"main-codebase",
    "operation":"write_file",
    "payload":{"file":{"path":"src/util.py","content":content_with_escape }},
    })
    delta =coding_module .parse_coding_delta_json (raw )
    assert delta .payload .file .content =='def greet(): return "hello"'


def test_coding_parse_fixes_double_escaped_quotes_in_multiline_python ()->None :
    import baps .adapters .coding_adapter as coding_module 

    # Multiline .py content with \" where " was intended (syntax error without fix)
    content_with_escape ='def test_empty():\n    assert normalize(\\"") == \\"\\"\n'
    raw =json .dumps ({
    "artifact_id":"main-codebase",
    "operation":"write_file",
    "payload":{"file":{"path":"tests/test_util.py","content":content_with_escape }},
    })
    delta =coding_module .parse_coding_delta_json (raw )
    assert '\\"'not in delta .payload .file .content 
    assert 'normalize("") == ""'in delta .payload .file .content 


def test_coding_parse_leaves_valid_multiline_python_unchanged ()->None :
    import baps .adapters .coding_adapter as coding_module 

    # Valid multiline Python with no backslash-quote issues
    content ='def test_ok():\n    assert 1 == 1\n'
    raw =json .dumps ({
    "artifact_id":"main-codebase",
    "operation":"write_file",
    "payload":{"file":{"path":"tests/test_ok.py","content":content }},
    })
    delta =coding_module .parse_coding_delta_json (raw )
    assert delta .payload .file .content ==content 


def test_coding_parse_does_not_fix_backslash_quotes_in_multiline_non_python_files ()->None :
    import baps .adapters .coding_adapter as coding_module 

    # Multi-line non-.py file: the fix only applies to .py files for multi-line content.
    content ='key: \\"value\\"\nother: \\"field\\"'# literal: key: \"value\"\nother: \"field\"
    raw =json .dumps ({
    "artifact_id":"main-codebase",
    "operation":"write_file",
    "payload":{"file":{"path":"config.yaml","content":content }},
    })
    delta =coding_module .parse_coding_delta_json (raw )
    assert delta .payload .file .content ==content 


    # ---------------------------------------------------------------------------
    # _parse_pytest_failures
    # ---------------------------------------------------------------------------

def test_parse_pytest_failures_empty_stdout ()->None :
    from baps .plugins .language_python import _parse_pytest_failures 
    assert _parse_pytest_failures ("")==[]


def test_parse_pytest_failures_no_failures ()->None :
    from baps .plugins .language_python import _parse_pytest_failures 
    stdout ="collected 3 items\n\n3 passed in 0.1s\n"
    assert _parse_pytest_failures (stdout )==[]


def test_parse_pytest_failures_single_failure_with_reason ()->None :
    from baps .plugins .language_python import _parse_pytest_failures 
    stdout ="FAILED tests/test_foo.py::test_bar - AssertionError: expected 1 got 2\n"
    result =_parse_pytest_failures (stdout )
    assert result ==[{"test_id":"tests/test_foo.py::test_bar","reason":"AssertionError: expected 1 got 2"}]


def test_parse_pytest_failures_multiple_failures ()->None :
    from baps .plugins .language_python import _parse_pytest_failures 
    stdout =(
    "FAILED tests/test_a.py::test_one - AssertionError: wrong\n"
    "FAILED tests/test_b.py::test_two - TypeError: bad type\n"
    )
    result =_parse_pytest_failures (stdout )
    assert len (result )==2 
    assert result [0 ]["test_id"]=="tests/test_a.py::test_one"
    assert result [1 ]["test_id"]=="tests/test_b.py::test_two"


def test_parse_pytest_failures_no_reason_separator ()->None :
    from baps .plugins .language_python import _parse_pytest_failures 
    stdout ="FAILED tests/test_foo.py::test_bar\n"
    result =_parse_pytest_failures (stdout )
    assert result ==[{"test_id":"tests/test_foo.py::test_bar","reason":""}]


def testtruncate_lines_short_text_unchanged ()->None :
    from baps .adapters .coding_adapter import truncate_lines 
    text ="line1\nline2\nline3"
    assert truncate_lines (text ,max_lines =5 )==text 


def testtruncate_lines_truncates_at_limit ()->None :
    from baps .adapters .coding_adapter import truncate_lines 
    text ="\n".join (f"line{i }"for i in range (10 ))
    result =truncate_lines (text ,max_lines =5 )
    lines =result .splitlines ()
    assert len (lines )==6 # 5 content lines + truncation message
    assert "line0"in lines [0 ]
    assert "line4"in lines [4 ]
    assert "more lines"in lines [5 ]
