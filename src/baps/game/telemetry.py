from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path

from baps.adapters.project_adapter import VerificationResult, sanitize_model_string
from baps.models.model_output import BlackboardEvent
from baps.models.models import ModelClient
from baps.state.state import DeltaState, GameSpec

logger = logging.getLogger(__name__)

_BLACKBOARD_DIR = "blackboard"
_NORTHSTAR_PROPOSALS_FILE = "northstar_proposals.jsonl"
_GAMES_FILE = "games.jsonl"
_VERIFICATION_SUMMARY_CAP = 500


def _sanitize_feedback_dict(d: dict) -> dict:
    result = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = sanitize_model_string(v)
        elif isinstance(v, list):
            result[k] = [sanitize_model_string(i) if isinstance(i, str) else i for i in v]
        elif isinstance(v, dict):
            result[k] = _sanitize_feedback_dict(v)
        else:
            result[k] = v
    return result


def _summarize_verification_result(result: VerificationResult | None) -> dict | None:
    if result is None:
        return None
    return {
        "passed": result.passed,
        "exit_code": result.exit_code,
        "stdout_summary": result.stdout[:_VERIFICATION_SUMMARY_CAP] if result.stdout else None,
        "stderr_summary": result.stderr[:_VERIFICATION_SUMMARY_CAP] if result.stderr else None,
    }


def _sanitize_game_spec_dict(game_spec: GameSpec) -> dict:
    return {
        "objective": sanitize_model_string(game_spec.objective),
        "target_artifact_id": game_spec.target_artifact_id,
        "allowed_delta_type": game_spec.allowed_delta_type,
        "success_condition": sanitize_model_string(game_spec.success_condition),
    }


def _append_northstar_proposal_to_blackboard(
    workspace: Path, rationale: str, proposed_northstar: str
) -> None:
    blackboard_dir = workspace / _BLACKBOARD_DIR
    blackboard_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "event": BlackboardEvent.NORTHSTAR_UPDATE_PROPOSAL,
        "rationale": sanitize_model_string(rationale),
        "proposed_northstar": sanitize_model_string(proposed_northstar),
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    proposals_path = blackboard_dir / _NORTHSTAR_PROPOSALS_FILE
    with proposals_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _append_game_to_blackboard(
    workspace: Path,
    game_id: str,
    depth: int,
    game_spec: GameSpec,
    attempt_records: list[dict],
    final_disposition: str,
    verification_result: VerificationResult | None,
    current_best_delta: DeltaState | None,
    integration_eligible_delta: DeltaState | None,
) -> None:
    blackboard_dir = workspace / _BLACKBOARD_DIR
    blackboard_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "event": BlackboardEvent.PLAY_GAME,
        "game_id": game_id,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "depth": depth,
        "context_chain": list(game_spec.context_chain),
        "game_spec": _sanitize_game_spec_dict(game_spec),
        "attempts": attempt_records,
        "final_disposition": final_disposition,
        "verification_result": _summarize_verification_result(verification_result),
        "current_best_delta": (
            None
            if current_best_delta is None
            else _sanitize_feedback_dict(current_best_delta.model_dump(mode="json"))
        ),
        "integration_eligible_delta": (
            None
            if integration_eligible_delta is None
            else _sanitize_feedback_dict(integration_eligible_delta.model_dump(mode="json"))
        ),
    }
    games_path = blackboard_dir / _GAMES_FILE
    with games_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _append_create_game_to_blackboard(
    workspace: Path,
    depth: int,
    context_chain: tuple[str, ...],
    state_view_fingerprint: str,
    result_type: str,
    result: dict | None,
    model_used: str,
) -> None:
    blackboard_dir = workspace / _BLACKBOARD_DIR
    blackboard_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "event": BlackboardEvent.CREATE_GAME,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "depth": depth,
        "context_chain": list(context_chain),
        "state_view_fingerprint": state_view_fingerprint,
        "result_type": result_type,
        "result": result,
        "model_used": model_used,
    }
    games_path = blackboard_dir / _GAMES_FILE
    with games_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _append_integration_to_blackboard(
    workspace: Path,
    depth: int,
    proposal_id: str,
    proposal_summary: str,
    state_changed: bool,
    delta_type: str,
) -> None:
    blackboard_dir = workspace / _BLACKBOARD_DIR
    blackboard_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "event": BlackboardEvent.INTEGRATION,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "depth": depth,
        "proposal_id": proposal_id,
        "proposal_summary": sanitize_model_string(proposal_summary),
        "state_changed": state_changed,
        "delta_type": delta_type,
    }
    games_path = blackboard_dir / _GAMES_FILE
    with games_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _client_model_name(client: ModelClient) -> str:
    return getattr(client, "model", type(client).__name__)
