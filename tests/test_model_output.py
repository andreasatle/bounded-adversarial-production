from __future__ import annotations 

import json 
import logging 
from pathlib import Path 

import pytest 

from baps .models .model_output import (
_BLACKBOARD_DIR ,
_CORRECTION_PROMPT ,
_FALLBACK_CORRECTION_PROMPT ,
_JSON_ONLY_INSTRUCTION ,
_MAX_DELTA_BYTES ,
_MAX_RETRIES ,
_OBJECT_CORRECTION_PROMPT ,
_REACT_CORRECTION_PROMPT ,
_STRIPPED_KEYS_FILE ,
extract_json_candidate ,
_is_react_format ,
_rescue_react_payload ,
parse_model_output ,
wrap_json_prompt ,
ParseRecoveryRecord ,
)


_KEYS =frozenset ({"a","b","c"})


# ---------------------------------------------------------------------------
# extract_json_candidate
# ---------------------------------------------------------------------------

class TestExtractJsonCandidate :
    def test_plain_json_object_unchanged (self )->None :
        text ='{"a": 1}'
        assert extract_json_candidate (text )=='{"a": 1}'

    def test_strips_leading_trailing_whitespace (self )->None :
        text ='   {"a": 1}   '
        assert extract_json_candidate (text )=='{"a": 1}'

    def test_strips_json_markdown_fence (self )->None :
        text ="```json\n{\"a\": 1}\n```"
        assert extract_json_candidate (text )=='{"a": 1}'

    def test_strips_plain_markdown_fence (self )->None :
        text ="```\n{\"a\": 1}\n```"
        assert extract_json_candidate (text )=='{"a": 1}'

    def test_extracts_json_from_leading_prose (self )->None :
        text ='Here is the answer: {"a": 1}'
        assert extract_json_candidate (text )=='{"a": 1}'

    def test_extracts_json_from_surrounding_prose (self )->None :
        text ='The result is {"a": 1} as requested.'
        assert extract_json_candidate (text )=='{"a": 1}'

    def test_extracts_json_from_multiline_prose (self )->None :
        text ="Thinking...\nStep 1: analyze\nStep 2: output\n\n{\"a\": 1}"
        assert extract_json_candidate (text )=='{"a": 1}'

    def test_extracts_nested_json_correctly (self )->None :
        text ='prefix {"a": {"b": 1}} suffix'
        result =extract_json_candidate (text )
        assert result =='{"a": {"b": 1}}'

    def test_no_brace_returns_as_is (self )->None :
    # No { → no extraction, return stripped text (may fail later at parse)
        text ="[1, 2, 3]"
        assert extract_json_candidate (text )=="[1, 2, 3]"

    def test_size_limit_raises (self )->None :
        big ="x"*(_MAX_DELTA_BYTES +1 )
        with pytest .raises (ValueError ,match ="exceeds maximum allowed size"):
            extract_json_candidate (big )

    def test_exactly_at_size_limit_passes (self )->None :
    # A large but valid JSON is within the limit
        content ="a"*100 
        text =json .dumps ({"data":content })
        # Should not raise (it's well under the limit)
        result =extract_json_candidate (text )
        assert result .startswith ("{")

    def test_fence_stripped_then_prose_extraction (self )->None :
    # Fence contains prose + JSON
        inner ='some text {"a": 1}'
        text =f"```json\n{inner }\n```"
        result =extract_json_candidate (text )
        assert result =='{"a": 1}'


        # ---------------------------------------------------------------------------
        # _is_react_format
        # ---------------------------------------------------------------------------

class TestIsReactFormat :
    def test_action_and_action_input (self )->None :
        assert _is_react_format ({"action":"respond","action_input":{"a":1 }})

    def test_thought_and_action (self )->None :
        assert _is_react_format ({"thought":"...","action":"write","action_input":{}})

    def test_thought_action_without_action_input (self )->None :
        assert _is_react_format ({"thought":"...","action":"X"})

    def test_tool_use_type_with_input (self )->None :
        assert _is_react_format ({"type":"tool_use","name":"output","input":{"a":1 }})

    def test_normal_dict_not_react (self )->None :
        assert not _is_react_format ({"objective":"do X","target_artifact_id":"doc"})

    def test_action_key_alone_not_react (self )->None :
    # 'action' alone without 'action_input' or 'thought' is not ReAct
        assert not _is_react_format ({"action":"accept"})

    def test_tool_use_type_without_input_not_react (self )->None :
        assert not _is_react_format ({"type":"tool_use","name":"output"})

    def test_empty_dict_not_react (self )->None :
        assert not _is_react_format ({})


        # ---------------------------------------------------------------------------
        # _rescue_react_payload
        # ---------------------------------------------------------------------------

class TestRescueReactPayload :
    def test_rescues_dict_action_input (self )->None :
        parsed ={"action":"respond","action_input":{"a":1 ,"b":2 }}
        assert _rescue_react_payload (parsed )=={"a":1 ,"b":2 }

    def test_returns_none_for_string_action_input (self )->None :
        parsed ={"action":"respond","action_input":"some string"}
        assert _rescue_react_payload (parsed )is None 

    def test_returns_none_for_list_action_input (self )->None :
        parsed ={"action":"respond","action_input":[1 ,2 ]}
        assert _rescue_react_payload (parsed )is None 

    def test_rescues_tool_use_input (self )->None :
        parsed ={"type":"tool_use","name":"output","input":{"x":99 }}
        assert _rescue_react_payload (parsed )=={"x":99 }

    def test_tool_use_string_input_returns_none (self )->None :
        parsed ={"type":"tool_use","name":"output","input":"string"}
        assert _rescue_react_payload (parsed )is None 

    def test_no_action_input_returns_none (self )->None :
        parsed ={"thought":"...","action":"X"}
        assert _rescue_react_payload (parsed )is None 


        # ---------------------------------------------------------------------------
        # parse_model_output — clean passthrough
        # ---------------------------------------------------------------------------

class TestCleanPassthrough :
    def test_clean_response_passthrough (self )->None :
        text =json .dumps ({"a":1 ,"b":2 ,"c":3 })
        result ,_ =parse_model_output (text ,_KEYS ,context ="test")
        assert result =={"a":1 ,"b":2 ,"c":3 }

    def test_subset_of_expected_keys_passes (self )->None :
        text =json .dumps ({"a":1 })
        result ,_ =parse_model_output (text ,_KEYS ,context ="test")
        assert result =={"a":1 }

    def test_markdown_fence_stripped (self )->None :
        text ="```json\n"+json .dumps ({"a":1 })+"\n```"
        result ,_ =parse_model_output (text ,_KEYS ,context ="test")
        assert result =={"a":1 }

    def test_prose_wrapped_json_extracted (self )->None :
        text ='Here is the result: {"a": 1}'
        result ,_ =parse_model_output (text ,_KEYS ,context ="test")
        assert result =={"a":1 }

    def test_multiline_prose_wrapped_json_extracted (self )->None :
        text ="Thinking step by step...\n\nFinal answer:\n{\"a\": 1, \"b\": 2}"
        result ,_ =parse_model_output (text ,_KEYS ,context ="test")
        assert result =={"a":1 ,"b":2 }


        # ---------------------------------------------------------------------------
        # parse_model_output — extra keys stripped
        # ---------------------------------------------------------------------------

class TestExtraKeysStripped :
    def test_extra_keys_stripped (self )->None :
        text =json .dumps ({"a":1 ,"b":2 ,"reasoning":"step by step","confidence":0.9 })
        result ,_ =parse_model_output (text ,_KEYS ,context ="test")
        assert result =={"a":1 ,"b":2 }
        assert "reasoning"not in result 
        assert "confidence"not in result 

    def test_extra_keys_logged_as_warning (self ,caplog :pytest .LogCaptureFixture )->None :
        text =json .dumps ({"a":1 ,"thoughts":"hmm"})
        with caplog .at_level (logging .WARNING ,logger ="baps.models.model_output"):
            parse_model_output (text ,_KEYS ,context ="myctx")
        assert "myctx"in caplog .text 
        assert "thoughts"in caplog .text 

    def test_extra_keys_written_to_blackboard (self ,tmp_path :Path )->None :
        text =json .dumps ({"a":1 ,"extra_field":"noise"})
        parse_model_output (text ,_KEYS ,context ="test:ctx",workspace =tmp_path )
        log_path =tmp_path /_BLACKBOARD_DIR /_STRIPPED_KEYS_FILE 
        assert log_path .exists ()
        entry =json .loads (log_path .read_text ())
        assert entry ["event"]=="unexpected_keys_stripped"
        assert entry ["context"]=="test:ctx"
        assert entry ["stripped_keys"]==["extra_field"]

    def test_no_blackboard_entry_when_no_extra_keys (self ,tmp_path :Path )->None :
        text =json .dumps ({"a":1 })
        parse_model_output (text ,_KEYS ,context ="test",workspace =tmp_path )
        assert not (tmp_path /_BLACKBOARD_DIR /_STRIPPED_KEYS_FILE ).exists ()

    def test_no_blackboard_write_when_workspace_is_none (self )->None :
        text =json .dumps ({"a":1 ,"extra":"noise"})
        parse_model_output (text ,_KEYS ,context ="test",workspace =None )

    def test_prose_json_with_extra_keys_stripped (self )->None :
        payload ={"a":1 ,"thoughts":"hmm","confidence":0.9 }
        text ="Here is my answer: "+json .dumps (payload )
        result ,_ =parse_model_output (text ,_KEYS ,context ="test")
        assert result =={"a":1 }


        # ---------------------------------------------------------------------------
        # parse_model_output — ReAct / tool-calling rescue
        # ---------------------------------------------------------------------------

class TestReactRescue :
    def test_react_format_rescued_from_action_input (self )->None :
        payload ={"action":"respond","action_input":{"a":1 }}
        text =json .dumps (payload )
        result ,_ =parse_model_output (text ,_KEYS ,context ="test")
        assert result =={"a":1 }

    def test_react_format_with_thought_rescued (self )->None :
        payload ={"thought":"Let me think...","action":"respond","action_input":{"a":1 ,"b":2 }}
        text =json .dumps (payload )
        result ,_ =parse_model_output (text ,_KEYS ,context ="test")
        assert result =={"a":1 ,"b":2 }

    def test_tool_use_format_rescued (self )->None :
        payload ={"type":"tool_use","name":"output","input":{"a":1 }}
        text =json .dumps (payload )
        result ,_ =parse_model_output (text ,_KEYS ,context ="test")
        assert result =={"a":1 }

    def test_react_rescued_payload_extra_keys_stripped (self )->None :
    # action_input itself has extra keys that should still be stripped
        payload ={"action":"respond","action_input":{"a":1 ,"extra":"noise"}}
        text =json .dumps (payload )
        result ,_ =parse_model_output (text ,_KEYS ,context ="test")
        assert result =={"a":1 }
        assert "extra"not in result 

    def test_react_non_dict_action_input_triggers_retry (self )->None :
        calls :list [str ]=[]
        valid =json .dumps ({"a":1 })

        def retry_fn (prompt :str )->str :
            calls .append (prompt )
            return valid 

        payload ={"action":"respond","action_input":"not a dict"}
        result ,_ =parse_model_output (json .dumps (payload ),_KEYS ,context ="test",retry_fn =retry_fn )
        assert result =={"a":1 }
        assert len (calls )==1 
        assert calls [0 ]==_REACT_CORRECTION_PROMPT 

    def test_react_non_dict_action_input_no_retry_raises (self )->None :
        payload ={"action":"respond","action_input":"not a dict"}
        with pytest .raises (ValueError ,match ="must be valid JSON"):
            parse_model_output (json .dumps (payload ),_KEYS ,context ="test")

    def test_react_correction_prompt_used_on_react_failure (self )->None :
        calls :list [str ]=[]

        def retry_fn (prompt :str )->str :
            calls .append (prompt )
            return "still-bad"

        payload ={"action":"X","action_input":"string"}
        with pytest .raises (ValueError ):
            parse_model_output (json .dumps (payload ),_KEYS ,context ="test",retry_fn =retry_fn )
        assert calls [0 ]==_REACT_CORRECTION_PROMPT 

    def test_react_format_in_prose_wrapper_rescued (self )->None :
    # Prose wraps a ReAct JSON which wraps the real payload
        inner ={"action":"respond","action_input":{"a":1 }}
        text ="Here is the output: "+json .dumps (inner )
        result ,_ =parse_model_output (text ,_KEYS ,context ="test")
        assert result =={"a":1 }


        # ---------------------------------------------------------------------------
        # parse_model_output — invalid JSON retry
        # ---------------------------------------------------------------------------

class TestInvalidJsonRetry :
    def test_invalid_json_raises_without_retry_fn (self )->None :
        with pytest .raises (ValueError ,match ="must be valid JSON"):
            parse_model_output ("not-json",_KEYS ,context ="test")

    def test_invalid_json_retries_via_retry_fn (self )->None :
        valid =json .dumps ({"a":1 })
        calls :list [str ]=[]

        def retry_fn (prompt :str )->str :
            calls .append (prompt )
            return valid 

        result ,_ =parse_model_output ("not-json",_KEYS ,context ="test",retry_fn =retry_fn )
        assert result =={"a":1 }
        assert len (calls )==1 

    def test_invalid_json_exhausts_retries_then_raises (self )->None :
        calls :list [str ]=[]

        def retry_fn (prompt :str )->str :
            calls .append (prompt )
            return "still-not-json"

        with pytest .raises (ValueError ,match ="must be valid JSON"):
            parse_model_output ("not-json",_KEYS ,context ="test",retry_fn =retry_fn )
        assert len (calls )==_MAX_RETRIES 

    def test_retry_logs_debug_message (self ,caplog :pytest .LogCaptureFixture )->None :
        valid =json .dumps ({"a":1 })

        def retry_fn (prompt :str )->str :
            return valid 

        with caplog .at_level (logging .DEBUG ,logger ="baps.models.model_output"):
            parse_model_output ("not-json",_KEYS ,context ="retryctx",retry_fn =retry_fn )
        assert "retryctx"in caplog .text 
        assert "retrying with correction prompt"in caplog .text 

    def test_correction_prompt_sent_on_json_failure (self )->None :
        calls :list [str ]=[]

        def retry_fn (prompt :str )->str :
            calls .append (prompt )
            return json .dumps ({"a":1 })

        parse_model_output ("bad",_KEYS ,context ="test",retry_fn =retry_fn )
        assert calls [0 ]==_CORRECTION_PROMPT 

    def test_object_correction_prompt_sent_on_shape_failure (self )->None :
        calls :list [str ]=[]

        def retry_fn (prompt :str )->str :
            calls .append (prompt )
            return json .dumps ({"a":1 })

        parse_model_output ("[1, 2]",_KEYS ,context ="test",retry_fn =retry_fn )
        assert calls [0 ]==_OBJECT_CORRECTION_PROMPT 

    def test_retry_fn_exception_treated_as_retry_failure_raises_value_error (self )->None :
        def retry_fn (prompt :str )->str :
            raise RuntimeError ("transport failure")

        with pytest .raises (ValueError ,match ="must be valid JSON"):
            parse_model_output ("bad",_KEYS ,context ="test",retry_fn =retry_fn )

    def test_retry_fn_exception_does_not_propagate_as_runtime_error (self )->None :
        def retry_fn (prompt :str )->str :
            raise RuntimeError ("no fake responses remaining")

            # Must raise ValueError (parse error), not RuntimeError (transport error)
        with pytest .raises (ValueError ):
            parse_model_output ("bad",_KEYS ,context ="test",retry_fn =retry_fn )


            # ---------------------------------------------------------------------------
            # parse_model_output — non-dict JSON
            # ---------------------------------------------------------------------------

class TestNonDictJson :
    def test_json_array_raises (self )->None :
        with pytest .raises (ValueError ,match ="must be a JSON object"):
            parse_model_output ("[1, 2, 3]",_KEYS ,context ="test")

    def test_json_string_raises (self )->None :
        with pytest .raises (ValueError ,match ="must be a JSON object"):
            parse_model_output ('"hello"',_KEYS ,context ="test")

    def test_json_null_raises (self )->None :
        with pytest .raises (ValueError ,match ="must be a JSON object"):
            parse_model_output ("null",_KEYS ,context ="test")

    def test_json_array_with_retry_can_recover (self )->None :
        valid =json .dumps ({"a":1 })

        def retry_fn (prompt :str )->str :
            return valid 

        result ,_ =parse_model_output ("[1, 2]",_KEYS ,context ="test",retry_fn =retry_fn )
        assert result =={"a":1 }


        # ---------------------------------------------------------------------------
        # parse_model_output — context prefix in error messages
        # ---------------------------------------------------------------------------

class TestContextPrefixInErrors :
    def test_context_prefix_in_json_error (self )->None :
        with pytest .raises (ValueError ,match ="mycontext: model output must be valid JSON"):
            parse_model_output ("bad",_KEYS ,context ="mycontext")

    def test_context_prefix_in_object_error (self )->None :
        with pytest .raises (ValueError ,match ="mycontext: model output must be a JSON object"):
            parse_model_output ("[1]",_KEYS ,context ="mycontext")


            # ---------------------------------------------------------------------------
            # parse_model_output — fallback model escalation
            # ---------------------------------------------------------------------------

class TestFallbackEscalation :
    def test_fallback_called_after_retry_exhaustion (self )->None :
        fallback_calls :list [str ]=[]
        valid =json .dumps ({"a":1 })

        def retry_fn (prompt :str )->str :
            return "bad"

        def fallback_fn (prompt :str )->str :
            fallback_calls .append (prompt )
            return valid 

        result ,_ =parse_model_output (
        "bad",_KEYS ,context ="test",retry_fn =retry_fn ,fallback_fn =fallback_fn 
        )
        assert result =={"a":1 }
        assert len (fallback_calls )==1 

    def test_fallback_receives_fallback_correction_prompt (self )->None :
        prompts :list [str ]=[]

        def retry_fn (prompt :str )->str :
            return "bad"

        def fallback_fn (prompt :str )->str :
            prompts .append (prompt )
            return json .dumps ({"a":1 })

        parse_model_output ("bad",_KEYS ,context ="test",retry_fn =retry_fn ,fallback_fn =fallback_fn )
        assert prompts [0 ]==_FALLBACK_CORRECTION_PROMPT 

    def test_fallback_not_called_when_primary_succeeds (self )->None :
        fallback_calls :list [str ]=[]

        def fallback_fn (prompt :str )->str :
            fallback_calls .append (prompt )
            return json .dumps ({"a":1 })

        parse_model_output (json .dumps ({"a":1 }),_KEYS ,context ="test",fallback_fn =fallback_fn )
        assert len (fallback_calls )==0 

    def test_fallback_not_called_when_retry_succeeds (self )->None :
        fallback_calls :list [str ]=[]
        attempt =[0 ]

        def retry_fn (prompt :str )->str :
            attempt [0 ]+=1 
            return json .dumps ({"a":1 })

        def fallback_fn (prompt :str )->str :
            fallback_calls .append (prompt )
            return "irrelevant"

        parse_model_output ("bad",_KEYS ,context ="test",retry_fn =retry_fn ,fallback_fn =fallback_fn )
        assert len (fallback_calls )==0 

    def test_fallback_exhausted_raises (self )->None :
        def retry_fn (prompt :str )->str :
            return "bad"

        def fallback_fn (prompt :str )->str :
            return "also-bad"

        with pytest .raises (ValueError ,match ="must be valid JSON"):
            parse_model_output (
            "bad",_KEYS ,context ="test",retry_fn =retry_fn ,fallback_fn =fallback_fn 
            )

    def test_fallback_called_exactly_once (self )->None :
        call_count =[0 ]

        def retry_fn (prompt :str )->str :
            return "bad"

        def fallback_fn (prompt :str )->str :
            call_count [0 ]+=1 
            return "bad-too"

        with pytest .raises (ValueError ):
            parse_model_output (
            "bad",_KEYS ,context ="test",retry_fn =retry_fn ,fallback_fn =fallback_fn 
            )
        assert call_count [0 ]==1 

    def test_fallback_runtime_error_propagates (self )->None :
        def retry_fn (prompt :str )->str :
            return "bad"

        def fallback_fn (prompt :str )->str :
            raise RuntimeError ("fallback client is down")

        with pytest .raises (RuntimeError ,match ="fallback client is down"):
            parse_model_output (
            "bad",_KEYS ,context ="test",retry_fn =retry_fn ,fallback_fn =fallback_fn 
            )

    def test_fallback_without_retry_called_after_first_failure (self )->None :
        fallback_calls :list [str ]=[]

        def fallback_fn (prompt :str )->str :
            fallback_calls .append (prompt )
            return json .dumps ({"a":1 })

        result ,_ =parse_model_output ("bad",_KEYS ,context ="test",fallback_fn =fallback_fn )
        assert result =={"a":1 }
        assert len (fallback_calls )==1 

    def test_fallback_logs_warning_on_escalation (
    self ,caplog :pytest .LogCaptureFixture 
    )->None :
        def retry_fn (prompt :str )->str :
            return "bad"

        def fallback_fn (prompt :str )->str :
            return json .dumps ({"a":1 })

        with caplog .at_level (logging .WARNING ,logger ="baps.models.model_output"):
            parse_model_output (
            "bad",_KEYS ,context ="myctx",retry_fn =retry_fn ,fallback_fn =fallback_fn 
            )
        assert "myctx"in caplog .text 
        assert "escalating to fallback model"in caplog .text 


        # ---------------------------------------------------------------------------
        # wrap_json_prompt
        # ---------------------------------------------------------------------------

class TestWrapJsonPrompt :
    def test_prepends_and_appends_instruction (self )->None :
        wrapped =wrap_json_prompt ("do the thing")
        assert wrapped .startswith (_JSON_ONLY_INSTRUCTION )
        assert wrapped .endswith (_JSON_ONLY_INSTRUCTION )

    def test_preserves_original_text (self )->None :
        wrapped =wrap_json_prompt ("some prompt body")
        assert "some prompt body"in wrapped 

    def test_instruction_covers_react_and_tool_calling (self )->None :
        assert "ReAct"in _JSON_ONLY_INSTRUCTION 
        assert "action/action_input"in _JSON_ONLY_INSTRUCTION 
        assert "tool-calling"in _JSON_ONLY_INSTRUCTION 

    def test_empty_body_still_wraps (self )->None :
        wrapped =wrap_json_prompt ("")
        assert wrapped .startswith (_JSON_ONLY_INSTRUCTION )
        assert wrapped .endswith (_JSON_ONLY_INSTRUCTION )


        # ---------------------------------------------------------------------------
        # parse_model_output — ParseRecoveryRecord
        # ---------------------------------------------------------------------------

class TestParseRecoveryRecord :
    def test_clean_response_has_empty_recovery (self )->None :
        text =json .dumps ({"a":1 })
        _ ,recovery =parse_model_output (text ,_KEYS ,context ="test")
        assert recovery .unexpected_keys_stripped ==[]
        assert not recovery .response_shape_rescued 
        assert not recovery .retry_used 
        assert not recovery .fallback_used 

    def test_stripped_keys_recorded (self )->None :
        text =json .dumps ({"a":1 ,"extra":"noise","thoughts":"hmm"})
        _ ,recovery =parse_model_output (text ,_KEYS ,context ="test")
        assert "extra"in recovery .unexpected_keys_stripped 
        assert "thoughts"in recovery .unexpected_keys_stripped 
        assert recovery .unexpected_keys_stripped ==sorted (["extra","thoughts"])

    def test_react_rescued_recorded (self )->None :
        payload ={"action":"respond","action_input":{"a":1 }}
        _ ,recovery =parse_model_output (json .dumps (payload ),_KEYS ,context ="test")
        assert recovery .response_shape_rescued is True 

    def test_retry_used_recorded_on_retry_success (self )->None :
        _ ,recovery =parse_model_output (
        "bad-json",
        _KEYS ,
        context ="test",
        retry_fn =lambda _ :json .dumps ({"a":1 }),
        )
        assert recovery .retry_used is True 
        assert not recovery .fallback_used 

    def test_fallback_used_recorded (self )->None :
        _ ,recovery =parse_model_output (
        "bad",
        _KEYS ,
        context ="test",
        retry_fn =lambda _ :"still-bad",
        fallback_fn =lambda _ :json .dumps ({"a":1 }),
        )
        assert recovery .fallback_used is True 
        assert recovery .retry_used is True 

    def test_fallback_without_retry_fn (self )->None :
        _ ,recovery =parse_model_output (
        "bad",
        _KEYS ,
        context ="test",
        fallback_fn =lambda _ :json .dumps ({"a":1 }),
        )
        assert recovery .fallback_used is True 
        assert not recovery .retry_used 

    def test_no_recovery_needed_fields_all_false (self )->None :
        _ ,recovery =parse_model_output (json .dumps ({"a":1 ,"b":2 }),_KEYS ,context ="test")
        assert recovery ==ParseRecoveryRecord ()
