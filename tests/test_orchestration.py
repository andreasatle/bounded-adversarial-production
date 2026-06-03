"""Tests for _solve_gap, run_project_iterations, stop conditions, decomposition, NorthStar proposals."""
from __future__ import annotations 

import json 
import logging 
from pathlib import Path 

import pytest 

from baps .core .run import create_state ,main 
from baps .core .run_config import RunConfig 
from baps .adapters .document_adapter import DocumentProjectAdapter 
from baps .core .parsers import NoNewGameError ,NorthStarUpdateNeededError 
from baps .state .state import (
GameSpec ,
DecomposeSpec ,
SubGapSpec ,
State ,
)
from baps .adapters .project_adapter import VerificationResult 
from baps .state .state_service import StateService 
from baps .state .state_store import JsonStateStore 
from baps .core .orchestration import run_project_iterations 
import baps .state .state as state_module 
from baps .core .runtime import _initialize_project 
def test_main_calls_play_game_with_gamespec_from_create_game (monkeypatch ,tmp_path :Path )->None :

    captured :dict [str ,object ]={}
    expected =GameSpec (
    objective ="O",
    target_artifact_id ="main-document",
    allowed_delta_type ="DeltaDocumentState",
    success_condition ="S",
    )

    monkeypatch .setattr (
    "baps.core.orchestration.create_game",
    lambda config ,state ,adapter =None ,verification_result =None ,context_chain =(),depth =0 ,**_kwargs :expected ,
    )

    def _capture_play_game (state ,spec ,adapter =None ,verification_result =None ,**_kwargs ):
        captured ["state"]=state 
        captured ["spec"]=spec 
        return state_module .DeltaDocumentState (
        artifact_id =spec .target_artifact_id ,
        operation ="append_section",
        payload =state_module .AppendSectionDelta (
        section =state_module .Section (title ="Introduction",body =spec .objective )
        ),
        )

    monkeypatch .setattr ("baps.core.orchestration.play_game",_capture_play_game )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run",
    "start",
    "--workspace",
    str (tmp_path /"ws-main-play"),
    "--project-type",
    "document",
    "--artifact-id","main-document","--goal","Write a report.","--output","output/report.md",],
    )

    main ()

    assert captured ["spec"]==expected 
    assert captured ["state"]is not None 


def test_main_exits_cleanly_if_play_game_returns_none (monkeypatch ,capsys ,tmp_path :Path )->None :
    # play_game returns None → PLAY_GAME_NO_DELTA → outer loop retries.
    # On retry, create_game raises NoNewGameError → loop stops cleanly.
    _cg_calls :dict [str ,int ]={"n":0 }

    def _mock_create_game (*args ,**kwargs ):
        _cg_calls ["n"]+=1
        if _cg_calls ["n"]>1 :
            raise NoNewGameError ("no more games after retry")
        from baps .game .engine import create_game as _real
        return _real (*args ,**kwargs )

    monkeypatch .setattr ("baps.core.orchestration.play_game",lambda _state ,_spec ,adapter =None ,verification_result =None ,**_kwargs :None )
    monkeypatch .setattr ("baps.core.orchestration.create_game",_mock_create_game )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run",
    "start",
    "--workspace",
    str (tmp_path /"ws-play-none"),
    "--project-type",
    "document",
    "--artifact-id","main-document","--goal","Write a report.","--output","output/report.md",],
    )
    main ()
    captured =capsys .readouterr ()
    assert "error: play_game produced no DeltaState"not in captured .err
    assert "update_applied=False"in captured .out
    assert "state_changed=False"in captured .out
    assert "stop_reason=create_game_no_new_game"in captured .out


def test_orchestration_does_not_apply_delta_when_play_game_has_no_integration_eligible_delta (
monkeypatch ,tmp_path :Path 
)->None :
    called ={"apply_delta":0 }

    def _count_apply_delta (self ,delta ):
        called ["apply_delta"]+=1 
        return self .store .load ()

    _cg_calls2 :dict [str ,int ]={"n":0 }

    def _mock_create_game2 (*args ,**kwargs ):
        _cg_calls2 ["n"]+=1
        if _cg_calls2 ["n"]>1 :
            raise NoNewGameError ("no more games after retry")
        from baps .game .engine import create_game as _real
        return _real (*args ,**kwargs )

    monkeypatch .setattr ("baps.core.orchestration.play_game",lambda *_a ,**_k :None )
    monkeypatch .setattr ("baps.core.orchestration.create_game",_mock_create_game2 )
    monkeypatch .setattr ("baps.core.orchestration.StateService.apply_delta",_count_apply_delta )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run",
    "start",
    "--workspace",
    str (tmp_path /"ws-no-eligible-delta"),
    "--project-type",
    "document",
    "--artifact-id","main-document","--goal","Write a report.","--output","output/report.md",
    ],
    )
    main ()
    assert called ["apply_delta"]==0


def test_orchestration_runtime_integration_calls_apply_delta (
monkeypatch ,tmp_path :Path 
)->None :
    calls ={"apply_delta":0 }

    original_apply_delta =StateService .apply_delta 

    def _capture_apply_delta (self ,delta ):
        calls ["apply_delta"]+=1 
        return original_apply_delta (self ,delta )

    monkeypatch .setattr ("baps.core.orchestration.StateService.apply_delta",_capture_apply_delta )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run",
    "start",
    "--workspace",
    str (tmp_path /"ws-apply-delta-runtime"),
    "--project-type",
    "document",
    "--artifact-id","main-document","--goal","Write a report.","--output","output/report.md",
    "--max-iterations","1",
    ],
    )
    main ()
    assert calls ["apply_delta"]>=1 


def test_main_max_iterations_two_runs_two_iterations_with_state_carry_forward (
monkeypatch ,capsys ,tmp_path :Path 
)->None :

    create_game_seen_sections :list [list [str ]]=[]

    def _create_game (config ,state ,adapter =None ,verification_result =None ,context_chain =(),depth =0 ,**_kwargs ):
        del verification_result 
        document =next (a for a in state .artifacts if a .id =="main-document")
        section_titles =[s .title for s in document .sections ]
        create_game_seen_sections .append (section_titles )
        if "Introduction"not in section_titles :
            objective ="Add introduction section"
        else :
            objective ="Add conclusion section"
        return GameSpec (
        objective =objective ,
        target_artifact_id ="main-document",
        allowed_delta_type ="DeltaDocumentState",
        success_condition =objective ,
        )

    def _play_game (_state ,spec ,adapter =None ,verification_result =None ,**_kwargs ):
        title ="Introduction"if "introduction"in spec .objective .lower ()else "Conclusion"
        return state_module .DeltaDocumentState (
        artifact_id ="main-document",
        operation ="append_section",
        payload =state_module .AppendSectionDelta (
        section =state_module .Section (title =title ,body =f"{title } body")
        ),
        )

    monkeypatch .setattr ("baps.core.orchestration.create_game",_create_game )
    monkeypatch .setattr ("baps.core.orchestration.play_game",_play_game )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run",
    "start",
    "--workspace",
    str (tmp_path /"ws-multi-iter"),
    "--project-type",
    "document",
    "--artifact-id","main-document","--goal","Write a report.","--output","output/report.md","--max-iterations",
    "2",
    ],
    )

    main ()
    out =capsys .readouterr ().out 

    assert len (create_game_seen_sections )==2 
    assert create_game_seen_sections [0 ]==[]
    assert create_game_seen_sections [1 ]==["Introduction"]
    assert "update_applied=True"in out 
    assert "state_changed=True"in out 
    assert "output_exported=True"in out 
    persisted =JsonStateStore (tmp_path /"ws-multi-iter"/"state"/"state.json").load ()
    doc =next (a for a in persisted .artifacts if a .id =="main-document")
    assert [section .title for section in doc .sections ]==["Introduction","Conclusion"]


def test_main_create_state_called_once_for_multi_iteration (monkeypatch ,tmp_path :Path )->None :

    calls ={"count":0 }
    original_initialize_project =_initialize_project 

    def _capture_initialize_project (config ,create_state_fn =None ):
        calls ["count"]+=1 
        return original_initialize_project (config ,create_state_fn =create_state_fn )

    monkeypatch .setattr ("baps.core.runtime._initialize_project",_capture_initialize_project )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run",
    "start",
    "--workspace",
    str (tmp_path /"ws-create-once"),
    "--project-type",
    "document",
    "--artifact-id","main-document","--goal","Write a report.","--output","output/report.md","--max-iterations",
    "2",
    ],
    )

    main ()
    assert calls ["count"]==1 


def test_main_stops_when_create_game_cannot_produce_new_game (
monkeypatch ,capsys ,tmp_path :Path 
)->None :

    calls ={"count":0 }

    def _create_game (_config ,_state ,adapter =None ,verification_result =None ,context_chain =(),depth =0 ,**_kwargs ):
        del verification_result 
        calls ["count"]+=1 
        if calls ["count"]==1 :
            return GameSpec (
            objective ="Add introduction section",
            target_artifact_id ="main-document",
            allowed_delta_type ="DeltaDocumentState",
            success_condition ="Introduction section exists",
            )
        raise NoNewGameError ("no further game")

    monkeypatch .setattr ("baps.core.orchestration.create_game",_create_game )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run",
    "start",
    "--workspace",
    str (tmp_path /"ws-stop-no-game"),
    "--project-type",
    "document",
    "--artifact-id","main-document","--goal","Write a report.","--output","output/report.md","--max-iterations",
    "3",
    ],
    )

    main ()
    out =capsys .readouterr ().out 
    assert "stop_reason=create_game_no_new_game"in out 


def test_no_new_game_accepted_when_no_verification_has_run (
monkeypatch ,capsys ,tmp_path :Path 
)->None :
    """no_new_game is a valid stop when verification has never run (non-coding)."""

    monkeypatch .setattr (
    "baps.core.orchestration.create_game",
    lambda _c ,_s ,adapter =None ,verification_result =None ,context_chain =(),depth =0 ,**_kw :(
    (_ for _ in ()).throw (NoNewGameError ("done"))
    ),
    )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run","start",
    "--workspace",str (tmp_path /"ws-no-vr-no-new-game"),
    "--project-type","document",
    "--artifact-id","main-document",
    "--goal","Write a report.","--output","output/report.md",
    ],
    )
    main ()
    out =capsys .readouterr ().out 
    assert "stop_reason=create_game_no_new_game"in out 


def test_no_new_game_accepted_when_verification_passed (
monkeypatch ,capsys ,tmp_path :Path 
)->None :
    """no_new_game is a valid stop when the last verification passed."""

    create_calls ={"n":0 }

    def _create_game (_config ,_state ,adapter =None ,verification_result =None ,context_chain =(),depth =0 ,**_kwargs ):
        create_calls ["n"]+=1 
        if create_calls ["n"]==1 :
            return GameSpec (
            objective ="Write a file",
            target_artifact_id ="main-codebase",
            allowed_delta_type ="DeltaCodingState",
            success_condition ="file exists",
            )
        raise NoNewGameError ("done — tests pass")

    import baps .state .state as state_module 

    def _play_game (_state ,_spec ,adapter =None ,verification_result =None ,**_kwargs ):
        return state_module .DeltaCodingState (
        artifact_id ="main-codebase",
        operation ="write_file",
        payload =state_module .WriteFileDelta (
        file =state_module .CodeFile (path ="main.py",content ="x=1\n")
        ),
        )

    monkeypatch .setattr ("baps.core.orchestration.create_game",_create_game )
    monkeypatch .setattr ("baps.core.orchestration.play_game",_play_game )
    monkeypatch .setattr (
    "baps.core.orchestration.verify_export_with_adapter",
    lambda _a ,_o ,_s ,_id ,**_kw :VerificationResult (
    command ="pytest",cwd ="/tmp",exit_code =0 ,stdout ="1 passed",stderr ="",passed =True 
    ),
    )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run","start",
    "--workspace",str (tmp_path /"ws-vr-pass-no-new-game"),
    "--project-type","coding",
    "--artifact-id","main-codebase",
    "--goal","Write a file.","--output","output/project",
    "--language","python",
    ],
    )
    main ()
    out =capsys .readouterr ().out 
    assert "stop_reason=create_game_no_new_game"in out 


def test_no_new_game_rejected_when_verification_failed (
monkeypatch ,capsys ,tmp_path :Path 
)->None :
    """no_new_game is NOT accepted when the last verification failed.
    The runtime retries once, then escalates if still stuck."""

    create_calls ={"n":0 }
    verification_results_seen :list [VerificationResult |None ]=[]

    failing_vr =VerificationResult (
    command ="pytest",cwd ="/tmp",exit_code =1 ,
    stdout ="FAILED test_foo.py::test_bar",stderr ="",passed =False ,
    )

    def _create_game (_config ,_state ,adapter =None ,verification_result =None ,context_chain =(),depth =0 ,**_kwargs ):
        create_calls ["n"]+=1 
        verification_results_seen .append (verification_result )
        if create_calls ["n"]==1 :
            return GameSpec (
            objective ="Write a file",
            target_artifact_id ="main-codebase",
            allowed_delta_type ="DeltaCodingState",
            success_condition ="file exists",
            )
        raise NoNewGameError ("no gap seen")# on call 2 and 3 — model wrong

    import baps .state .state as state_module 

    def _play_game (_state ,_spec ,adapter =None ,verification_result =None ,**_kwargs ):
        return state_module .DeltaCodingState (
        artifact_id ="main-codebase",
        operation ="write_file",
        payload =state_module .WriteFileDelta (
        file =state_module .CodeFile (path ="main.py",content ="x=1\n")
        ),
        )

    monkeypatch .setattr ("baps.core.orchestration.create_game",_create_game )
    monkeypatch .setattr ("baps.core.orchestration.play_game",_play_game )
    monkeypatch .setattr (
    "baps.core.orchestration.verify_export_with_adapter",
    lambda _a ,_o ,_s ,_id ,**_kw :failing_vr ,
    )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run","start",
    "--workspace",str (tmp_path /"ws-vr-fail-no-new-game"),
    "--project-type","coding",
    "--artifact-id","main-codebase",
    "--goal","Write a file with tests.","--output","output/project",
    "--language","python",
    "--max-iterations","5",
    ],
    )
    main ()
    out =capsys .readouterr ().out 

    # Must NOT stop with create_game_no_new_game while verification is failing
    assert "stop_reason=create_game_no_new_game"not in out 
    # After two consecutive no_new_game with failing verification, escalates
    assert "stop_reason=northstar_update_proposed"in out 
    # create_game was called 3 times: 1 (GameSpec) + 2 (no_new_game override + escalation)
    assert create_calls ["n"]==3 
    # Second and third calls received the failing verification result
    assert verification_results_seen [1 ]is not None 
    assert verification_results_seen [1 ].passed is False 
    assert verification_results_seen [2 ]is not None 
    assert verification_results_seen [2 ].passed is False 


def test_no_new_game_override_resets_after_leaf_game (
monkeypatch ,capsys ,tmp_path :Path 
)->None :
    """After a leaf game runs, the override flag resets so another retry is allowed."""

    # Sequence: GameSpec → (leaf runs, verification fails) → no_new_game (override 1)
    # → GameSpec → (leaf runs, verification fails) → no_new_game (override 2, fresh slate)
    # → no_new_game (escalate after fresh override)
    create_calls ={"n":0 }

    failing_vr =VerificationResult (
    command ="pytest",cwd ="/tmp",exit_code =1 ,
    stdout ="FAILED",stderr ="",passed =False ,
    )

    def _create_game (_config ,_state ,adapter =None ,verification_result =None ,context_chain =(),depth =0 ,**_kwargs ):
        create_calls ["n"]+=1 
        if create_calls ["n"]in (1 ,3 ):
            return GameSpec (
            objective ="Write a file",
            target_artifact_id ="main-codebase",
            allowed_delta_type ="DeltaCodingState",
            success_condition ="file exists",
            )
        raise NoNewGameError ("no gap")

    import baps .state .state as state_module 

    play_calls ={"n":0 }

    def _play_game (_state ,_spec ,adapter =None ,verification_result =None ,**_kwargs ):
        play_calls ["n"]+=1 
        return state_module .DeltaCodingState (
        artifact_id ="main-codebase",
        operation ="write_file",
        payload =state_module .WriteFileDelta (
        file =state_module .CodeFile (path =f"file_{play_calls ['n']}.py",content ="x=1\n")
        ),
        )

    monkeypatch .setattr ("baps.core.orchestration.create_game",_create_game )
    monkeypatch .setattr ("baps.core.orchestration.play_game",_play_game )
    monkeypatch .setattr (
    "baps.core.orchestration.verify_export_with_adapter",
    lambda _a ,_o ,_s ,_id ,**_kw :failing_vr ,
    )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run","start",
    "--workspace",str (tmp_path /"ws-override-reset"),
    "--project-type","coding",
    "--artifact-id","main-codebase",
    "--goal","Write files.","--output","output/project",
    "--language","python",
    "--max-iterations","10",
    ],
    )
    main ()
    out =capsys .readouterr ().out 

    assert "stop_reason=northstar_update_proposed"in out 
    # GameSpec(1) → leaf → no_new_game(2, override) → GameSpec(3) → leaf → no_new_game(4, fresh override) → no_new_game(5, escalate)
    assert create_calls ["n"]==5 


def test_main_stop_reason_iteration_limit_reached_after_all_iterations_used (
monkeypatch ,capsys ,tmp_path :Path 
)->None :

    create_game_calls ={"n":0 }

    def _create_game (_config ,_state ,adapter =None ,verification_result =None ,context_chain =(),depth =0 ,**_kwargs ):
        create_game_calls ["n"]+=1 
        return GameSpec (
        objective ="Add a section",
        target_artifact_id ="main-document",
        allowed_delta_type ="DeltaDocumentState",
        success_condition ="Section exists.",
        )

    monkeypatch .setattr ("baps.core.orchestration.create_game",_create_game )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run",
    "start",
    "--workspace",str (tmp_path /"ws-iter-limit"),
    "--project-type","document",
    "--artifact-id","main-document",
    "--goal","Write a report.","--output","output/report.md",
    "--max-iterations","2",
    ],
    )
    main ()
    out =capsys .readouterr ().out 
    assert "stop_reason=iteration_limit_reached"in out 
    assert create_game_calls ["n"]==2 


def test_main_stop_reason_no_state_change_when_applied_delta_has_no_effect (
monkeypatch ,capsys ,tmp_path :Path 
)->None :

    import baps .state .state_service as ss_module 
    monkeypatch .setattr (ss_module .StateService ,"states_differ",lambda self ,_b ,_a :False )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run",
    "start",
    "--workspace",str (tmp_path /"ws-no-change"),
    "--project-type","document",
    "--artifact-id","main-document",
    "--goal","Write a report.","--output","output/report.md",
    "--max-iterations","3",
    ],
    )
    main ()
    out =capsys .readouterr ().out 
    assert "stop_reason=northstar_update_proposed"in out 
    assert "northstar_proposal_written=True"in out 
    assert "state_changed=False"in out 
    assert "update_applied=True"in out 


def test_main_no_state_change_stops_loop_before_max_iterations (
monkeypatch ,capsys ,tmp_path :Path 
)->None :

    create_game_calls ={"n":0 }

    def _create_game (_config ,_state ,adapter =None ,verification_result =None ,context_chain =(),depth =0 ,**_kwargs ):
        create_game_calls ["n"]+=1 
        return GameSpec (
        objective ="Add a section",
        target_artifact_id ="main-document",
        allowed_delta_type ="DeltaDocumentState",
        success_condition ="Section exists.",
        )

    import baps .state .state_service as ss_module 
    monkeypatch .setattr ("baps.core.orchestration.create_game",_create_game )
    monkeypatch .setattr (ss_module .StateService ,"states_differ",lambda self ,_b ,_a :False )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run",
    "start",
    "--workspace",str (tmp_path /"ws-no-change-early"),
    "--project-type","document",
    "--artifact-id","main-document",
    "--goal","Write a report.","--output","output/report.md",
    "--max-iterations","5",
    ],
    )
    main ()
    out =capsys .readouterr ().out 
    assert "stop_reason=northstar_update_proposed"in out 
    assert create_game_calls ["n"]==1 


def test_main_no_state_change_after_prior_state_change_reports_state_changed_true (
monkeypatch ,capsys ,tmp_path :Path 
)->None :
    """State changed on iteration 1 (carried forward), then no change on iteration 2."""

    call_count ={"n":0 }

    def _states_differ (self ,_before ,_after ):
        call_count ["n"]+=1 
        # Call 1: iteration 1 — state changed
        # Call 2: iteration 2 — no state change
        return call_count ["n"]<=1 

    import baps .state .state_service as ss_module 
    monkeypatch .setattr (ss_module .StateService ,"states_differ",_states_differ )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run",
    "start",
    "--workspace",str (tmp_path /"ws-change-then-no-change"),
    "--project-type","document",
    "--artifact-id","main-document",
    "--goal","Write a report.","--output","output/report.md",
    "--max-iterations","5",
    ],
    )
    main ()
    out =capsys .readouterr ().out 
    assert "stop_reason=northstar_update_proposed"in out 
    assert "state_changed=True"in out 


def test_play_game_no_delta_retries_then_stops_on_no_new_game (
monkeypatch ,tmp_path :Path ,capsys
)->None :
    # PLAY_GAME_NO_DELTA now causes the outer loop to retry rather than escalate
    # to a NorthStar proposal.  After one retry, create_game signals no_new_game
    # and the loop stops with CREATE_GAME_NO_NEW_GAME.
    workspace =tmp_path /"ws-no-delta-retry"
    _call_count :dict [str ,int ]={"n":0 }

    def _mock_create_game (*args ,**kwargs ):
        _call_count ["n"]+=1
        if _call_count ["n"]>1 :
            raise NoNewGameError ("no more games after retry")
        from baps .game .engine import create_game as _real
        return _real (*args ,**kwargs )

    monkeypatch .setattr ("baps.core.orchestration.play_game",lambda _s ,_g ,adapter =None ,verification_result =None ,**_kw :None )
    monkeypatch .setattr ("baps.core.orchestration.create_game",_mock_create_game )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run","start",
    "--workspace",str (workspace ),
    "--project-type","document",
    "--artifact-id","main-document",
    "--goal","Write a report.","--output","output/report.md",
    ],
    )
    main ()
    out =capsys .readouterr ().out
    assert "stop_reason=create_game_no_new_game"in out


def test_no_state_change_escalates_to_northstar_proposal (
monkeypatch ,tmp_path :Path ,capsys 
)->None :
    import baps .state .state_service as ss_module 

    workspace =tmp_path /"ws-no-change-proposal"
    monkeypatch .setattr (ss_module .StateService ,"states_differ",lambda self ,_b ,_a :False )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run","start",
    "--workspace",str (workspace ),
    "--project-type","document",
    "--artifact-id","main-document",
    "--goal","Write a report.","--output","output/report.md",
    "--max-iterations","3",
    ],
    )
    main ()
    out =capsys .readouterr ().out 
    assert "stop_reason=northstar_update_proposed"in out 
    assert "northstar_proposal_written=True"in out 

    proposals_path =workspace /"blackboard"/"northstar_proposals.jsonl"
    assert proposals_path .exists ()
    entry =json .loads (proposals_path .read_text (encoding ="utf-8").strip ())
    assert entry ["event"]=="northstar_update_proposal"
    assert "no state change"in entry ["rationale"].lower ()
    assert "created_at"in entry 


def test_main_create_game_parse_error_is_not_swallowed_as_no_game (
monkeypatch ,capsys ,caplog ,tmp_path :Path 
)->None :

    def _broken_create_game (_config ,_state ,adapter =None ,verification_result =None ,context_chain =(),depth =0 ,**_kwargs ):
        del verification_result 
        raise ValueError ("create_game model output must be valid JSON")

    monkeypatch .setattr ("baps.core.orchestration.create_game",_broken_create_game )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run",
    "start",
    "--workspace",
    str (tmp_path /"ws-create-game-error"),
    "--project-type",
    "document",
    "--artifact-id",
    "main-document",
    "--goal","Write a report.","--output","output/report.md",
    "--max-iterations",
    "2",
    ],
    )
    with caplog .at_level (logging .ERROR ),pytest .raises (SystemExit )as exc :
        main ()
    assert exc .value .code ==2 
    assert "create_game model output must be valid JSON"in caplog .text 
def test_run_iterations_northstar_update_proposed_writes_blackboard_and_stops (
monkeypatch ,tmp_path :Path ,capsys 
)->None :

    workspace =tmp_path /"ws-northstar-proposal"

    def _create_game_raises (_config ,_state ,adapter =None ,verification_result =None ,context_chain =(),depth =0 ,**_kwargs ):
        raise NorthStarUpdateNeededError (
        rationale ="Game direction contradicts NorthStar.",
        proposed_northstar ="# Revised NorthStar\n\nNew direction.",
        )

    monkeypatch .setattr ("baps.core.orchestration.create_game",_create_game_raises )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run",
    "start",
    "--workspace",str (workspace ),
    "--project-type","document",
    "--artifact-id","main-document",
    "--goal","Write a report.","--output","output/report.md",
    "--max-iterations","3",
    ],
    )

    main ()
    out =capsys .readouterr ().out 

    assert "stop_reason=northstar_update_proposed"in out 
    assert "northstar_proposal_written=True"in out 

    proposals_path =workspace /"blackboard"/"northstar_proposals.jsonl"
    assert proposals_path .exists ()
    entry =json .loads (proposals_path .read_text (encoding ="utf-8").strip ())
    assert entry ["event"]=="northstar_update_proposal"
    assert entry ["rationale"]=="Game direction contradicts NorthStar."
    assert entry ["proposed_northstar"]=="# Revised NorthStar\n\nNew direction."
    assert "created_at"in entry 


def test_run_iterations_northstar_update_proposed_does_not_apply_state_update (
monkeypatch ,tmp_path :Path 
)->None :

    workspace =tmp_path /"ws-northstar-no-update"

    def _create_game_raises (_config ,_state ,adapter =None ,verification_result =None ,context_chain =(),depth =0 ,**_kwargs ):
        raise NorthStarUpdateNeededError (
        rationale ="Direction mismatch.",
        proposed_northstar ="# New NorthStar",
        )

    monkeypatch .setattr ("baps.core.orchestration.create_game",_create_game_raises )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run",
    "start",
    "--workspace",str (workspace ),
    "--project-type","document",
    "--artifact-id","main-document",
    "--goal","Write a report.","--output","output/report.md",
    "--max-iterations","3",
    ],
    )

    main ()

    state_path =workspace /"state"/"state.json"
    initial_state =State .model_validate (
    json .loads (state_path .read_text (encoding ="utf-8"))
    )
    assert len (initial_state .artifacts )==1 
    artifact =initial_state .artifacts [0 ]
    assert hasattr (artifact ,"sections")or artifact .kind =="document"


def test_run_iterations_northstar_proposal_appends_on_multiple_signals (
monkeypatch ,tmp_path :Path 
)->None :

    workspace =tmp_path /"ws-northstar-append"

    proposals_path =workspace /"blackboard"/"northstar_proposals.jsonl"
    proposals_path .parent .mkdir (parents =True ,exist_ok =True )
    proposals_path .write_text (
    json .dumps ({
    "event":"northstar_update_proposal",
    "rationale":"Earlier proposal.",
    "proposed_northstar":"# Old NorthStar",
    "created_at":"2026-01-01T00:00:00",
    })+"\n",
    encoding ="utf-8",
    )

    def _create_game_raises (_config ,_state ,adapter =None ,verification_result =None ,context_chain =(),depth =0 ,**_kwargs ):
        raise NorthStarUpdateNeededError (
        rationale ="New mismatch.",
        proposed_northstar ="# Newer NorthStar",
        )

    monkeypatch .setattr ("baps.core.orchestration.create_game",_create_game_raises )
    monkeypatch .setattr (
    "sys.argv",
    [
    "baps-run",
    "start",
    "--workspace",str (workspace ),
    "--project-type","document",
    "--artifact-id","main-document",
    "--goal","Write a report.","--output","output/report.md",
    "--max-iterations","1",
    ],
    )

    main ()

    lines =[line for line in proposals_path .read_text (encoding ="utf-8").splitlines ()if line .strip ()]
    assert len (lines )==2 
    first =json .loads (lines [0 ])
    second =json .loads (lines [1 ])
    assert first ["rationale"]=="Earlier proposal."
    assert second ["rationale"]=="New mismatch."

def test_solve_gap_decompose_then_play (monkeypatch ,tmp_path :Path )->None :
    """Decompose at depth 0 → two sub-games played at depth 1, then no_new_game."""
    import baps .state .state as state_module 

    played :list [str ]=[]
    top_calls =[0 ]

    def _fake_create_game (config ,state ,adapter =None ,verification_result =None ,context_chain =(),depth =0 ,**_kwargs ):
        if not context_chain :
            top_calls [0 ]+=1 
            if top_calls [0 ]>1 :
                raise NoNewGameError ("all gaps closed")
            return DecomposeSpec (
            rationale ="Too large",
            sub_gaps =(
            SubGapSpec (description ="Sub-gap A"),
            SubGapSpec (description ="Sub-gap B"),
            ),
            )
            # leaf — return a game spec for each sub-gap
        return GameSpec (
        objective =f"Do {context_chain [-1 ]}",
        target_artifact_id ="main-document",
        allowed_delta_type ="DeltaDocumentState",
        success_condition ="done",
        )

    def _fake_play_game (state ,game_spec ,adapter =None ,**kwargs ):
        played .append (game_spec .objective )
        return state_module .DeltaDocumentState (
        artifact_id ="main-document",
        operation ="append_section",
        payload =state_module .AppendSectionDelta (
        section =state_module .Section (title =game_spec .objective ,body ="body"),
        ),
        )

    monkeypatch .setattr ("baps.core.orchestration.create_game",_fake_create_game )
    monkeypatch .setattr ("baps.core.orchestration.play_game",_fake_play_game )

    config =RunConfig (
    workspace =tmp_path /"ws",
    project_type ="document",
    artifact_id ="main-document",
    northstar_markdown ="# Goal",
    goal ="Write something",
    output_path =tmp_path /"ws"/"output"/"report.md",
    max_iterations =10 ,
    max_depth =2 ,
    )
    service ,state =_initialize_project (config )
    adapter =DocumentProjectAdapter ()

    result =run_project_iterations (config ,adapter ,service ,state )

    assert len (played )==2 
    assert "Sub-gap A"in played [0 ]
    assert "Sub-gap B"in played [1 ]
    assert result .iterations_completed ==2 


def test_solve_gap_context_chain_injected_into_game_spec (monkeypatch ,tmp_path :Path )->None :
    """The context chain accumulated through decomposition reaches Blue's GameSpec."""
    import baps .state .state as state_module 

    captured_chain :list [tuple [str ,...]]=[]
    top_calls =[0 ]

    def _fake_create_game (config ,state ,adapter =None ,verification_result =None ,context_chain =(),depth =0 ,**_kwargs ):
        if not context_chain :
            top_calls [0 ]+=1 
            if top_calls [0 ]>1 :
                raise NoNewGameError ("done")
            return DecomposeSpec (
            rationale ="Top level too large",
            sub_gaps =(SubGapSpec (description ="Level-1 gap"),),
            )
        return GameSpec (
        objective ="Leaf game",
        target_artifact_id ="main-document",
        allowed_delta_type ="DeltaDocumentState",
        success_condition ="done",
        )

    def _fake_play_game (state ,game_spec ,adapter =None ,**kwargs ):
        captured_chain .append (game_spec .context_chain )
        return state_module .DeltaDocumentState (
        artifact_id ="main-document",
        operation ="append_section",
        payload =state_module .AppendSectionDelta (
        section =state_module .Section (title ="Leaf game",body ="body"),
        ),
        )

    monkeypatch .setattr ("baps.core.orchestration.create_game",_fake_create_game )
    monkeypatch .setattr ("baps.core.orchestration.play_game",_fake_play_game )

    config =RunConfig (
    workspace =tmp_path /"ws",
    project_type ="document",
    artifact_id ="main-document",
    northstar_markdown ="# Goal",
    goal ="Write something",
    output_path =tmp_path /"ws"/"output"/"report.md",
    max_iterations =5 ,
    max_depth =3 ,
    )
    service ,state =_initialize_project (config )
    adapter =DocumentProjectAdapter ()
    run_project_iterations (config ,adapter ,service ,state )

    assert len (captured_chain )==1 
    assert captured_chain [0 ]==("Level-1 gap",)


def test_solve_gap_max_depth_stops_recursion (monkeypatch ,tmp_path :Path )->None :
    """Decompose always → max_depth_reached stop reason."""

    def _always_decompose (config ,state ,adapter =None ,verification_result =None ,context_chain =(),depth =0 ,**_kwargs ):
        return DecomposeSpec (
        rationale ="Always decompose",
        sub_gaps =(SubGapSpec (description ="inner"),),
        )

    monkeypatch .setattr ("baps.core.orchestration.create_game",_always_decompose )

    config =RunConfig (
    workspace =tmp_path /"ws",
    project_type ="document",
    artifact_id ="main-document",
    northstar_markdown ="# Goal",
    goal ="Write something",
    output_path =tmp_path /"ws"/"output"/"report.md",
    max_iterations =5 ,
    max_depth =2 ,
    )
    service ,state =_initialize_project (config )
    adapter =DocumentProjectAdapter ()
    result =run_project_iterations (config ,adapter ,service ,state )

    assert result .stop_reason .value =="max_depth_reached"
    assert result .iterations_completed ==0 
