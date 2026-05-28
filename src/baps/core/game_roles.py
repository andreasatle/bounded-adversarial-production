from __future__ import annotations

from pathlib import Path
from typing import Any

from baps.core.clients import (
    SpecRole,
    _build_client_for_role,
    _build_fallback_chain_for_role,
    _build_role_client,
    _make_fallback_chain_fn,
    _resolve_backend_model,
)
from baps.models.models import ModelClient, Role
from baps.adapters.project_adapter import ProjectTypeAdapter, VerificationResult


# Keep schemas colocated with role wiring to avoid duplicating literals.
_RED_FINDING_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "disposition": {"type": "string", "enum": ["accept", "revise", "reject"]},
        "rationale": {"type": "string", "maxLength": 500},
        "success_condition_met": {"type": ["boolean", "null"]},
        "findings": {"type": "array", "items": {"type": "string", "maxLength": 300}},
    },
    "required": ["disposition", "rationale"],
    "additionalProperties": False,
}

_REFEREE_DECISION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "disposition": {"type": "string", "enum": ["accept", "revise", "reject"]},
        "rationale": {"type": "string", "maxLength": 500},
        "red_override": {"type": ["boolean", "null"]},
        "improvement_hints": {"type": "array", "items": {"type": "string", "maxLength": 300}},
    },
    "required": ["disposition", "rationale"],
    "additionalProperties": False,
}


def _initial_play_game_feedback(
    verification_result: VerificationResult | None,
) -> dict[str, Any] | None:
    if verification_result is None:
        return None
    return {
        "prior_export_verification": {
            "exit_code": verification_result.exit_code,
            "passed": verification_result.passed,
            "stdout": verification_result.stdout,
            "stderr": verification_result.stderr,
        }
    }


def _resolve_play_game_roles(
    resolved_adapter: ProjectTypeAdapter,
    config: dict[str, Any] | None,
    model_client: ModelClient | None,
    red_model_client: ModelClient | None,
    referee_model_client: ModelClient | None,
    build_client_for_role_fn: Any = _build_client_for_role,
    build_role_client_fn: Any = _build_role_client,
) -> tuple[Role, Role, Role]:
    def _get_client(explicit: ModelClient | None, role: str) -> ModelClient:
        if explicit is not None:
            return explicit
        if config is not None:
            return build_client_for_role_fn(role, config)
        return build_role_client_fn(role)

    blue_role = Role(
        SpecRole.BLUE,
        _get_client(model_client, SpecRole.BLUE),
        resolved_adapter.build_blue_output_format(),
        constrained=False,
    )
    red_role = Role(
        SpecRole.RED,
        _get_client(red_model_client, SpecRole.RED),
        _RED_FINDING_SCHEMA,
        constrained=True,
    )
    referee_role = Role(
        SpecRole.REFEREE,
        _get_client(referee_model_client, SpecRole.REFEREE),
        _REFEREE_DECISION_SCHEMA,
        constrained=True,
    )
    return blue_role, red_role, referee_role


def _build_play_game_fallbacks(
    config: dict[str, Any] | None,
    red_model_client: ModelClient | None,
    referee_model_client: ModelClient | None,
    build_fallback_chain_for_role_fn: Any = _build_fallback_chain_for_role,
) -> tuple[Path | None, Any, Any]:
    workspace = config.get("workspace") if config else None
    if config is None:
        return workspace, None, None
    try:
        red_primary = (
            _resolve_backend_model(SpecRole.RED, config)[1]
            if red_model_client is None
            else "(provided)"
        )
    except ValueError:
        red_primary = "(unknown)"
    try:
        referee_primary = (
            _resolve_backend_model(SpecRole.REFEREE, config)[1]
            if referee_model_client is None
            else "(provided)"
        )
    except ValueError:
        referee_primary = "(unknown)"
    red_fallback_fn = _make_fallback_chain_fn(
        SpecRole.RED, red_primary, build_fallback_chain_for_role_fn(SpecRole.RED, config)
    )
    referee_fallback_fn = _make_fallback_chain_fn(
        SpecRole.REFEREE,
        referee_primary,
        build_fallback_chain_for_role_fn(SpecRole.REFEREE, config),
    )
    return workspace, red_fallback_fn, referee_fallback_fn
