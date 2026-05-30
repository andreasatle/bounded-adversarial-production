from __future__ import annotations

import datetime
import json
import logging
import re
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field


class ParseRecoveryRecord(BaseModel):
    """Structured record of what parser recovery was applied to a model response."""

    unexpected_keys_stripped: list[str] = Field(default_factory=list)
    response_shape_rescued: bool = False
    output_truncated: bool = False
    empty_items_filtered: bool = False
    retry_used: bool = False
    fallback_used: bool = False


class BlackboardEvent(StrEnum):
    """Represent the BlackboardEvent type."""
    NORTHSTAR_UPDATE_PROPOSAL = "northstar_update_proposal"
    UNEXPECTED_KEYS_STRIPPED = "unexpected_keys_stripped"
    GAME = "game"
    CREATE_GAME = "create_game"
    PLAY_GAME = "play_game"
    INTEGRATION = "integration"

logger = logging.getLogger(__name__)

_JSON_ONLY_INSTRUCTION = (
    "You must respond with a single JSON object only. "
    "Do not use tool-calling format, ReAct format, or action/action_input structure. "
    "Do not include any prose, explanation, or markdown before or after the JSON. "
    "Your entire response must be parseable JSON and nothing else."
)

_MAX_RETRIES = 2
_CORRECTION_PROMPT = (
    "Your previous response was not valid JSON. "
    "Respond with only a JSON object and nothing else."
)
_OBJECT_CORRECTION_PROMPT = (
    "Your previous response was valid JSON but not an object. "
    "Respond with only a JSON object (starting with { and ending with }) and nothing else."
)
_REACT_CORRECTION_PROMPT = (
    "Your previous response used tool-calling or ReAct format (action/action_input). "
    "Do not use any tool-calling format, ReAct format, or action/action_input wrapper. "
    "Respond with only a plain JSON object and nothing else."
)
_FALLBACK_CORRECTION_PROMPT = (
    "Your previous responses were not valid JSON objects. "
    "This is a final escalation attempt. "
    "Respond with ONLY a JSON object. No prose, no markdown, no tool-calling format."
)
_BLACKBOARD_DIR = "blackboard"
_STRIPPED_KEYS_FILE = "stripped_keys.jsonl"
_MAX_DELTA_BYTES = 65536

_FENCE_RE = re.compile(
    r"\A```(?:json)?[ \t]*\n(?P<body>[\s\S]*?)\n```[ \t]*\Z",
    re.IGNORECASE,
)


def _extract_json_candidate(text: str) -> str:
    """Normalize raw model text to a JSON candidate string.

    Pipeline:
    1. Reject oversized responses.
    2. Strip markdown fences.
    3. If no leading brace, extract substring from first { to last } to
       recover JSON embedded in prose.
    """
    if len(text.encode("utf-8")) > _MAX_DELTA_BYTES:
        raise ValueError(
            f"model response exceeds maximum allowed size ({_MAX_DELTA_BYTES} bytes)"
        )
    normalized = text.strip()
    fence_match = _FENCE_RE.match(normalized)
    if fence_match is not None:
        normalized = fence_match.group("body").strip()
    if not normalized.startswith("{"):
        first = normalized.find("{")
        last = normalized.rfind("}")
        if first != -1 and last > first:
            logger.debug(
                "prose wrapping detected: extracting JSON from char %d to %d",
                first, last + 1,
            )
            normalized = normalized[first : last + 1]
    return normalized


def _is_react_format(parsed: dict[str, Any]) -> bool:
    """Return True if parsed dict looks like a ReAct/tool-calling wrapper."""
    keys = set(parsed.keys())
    if "action" in keys and "action_input" in keys:
        return True
    if "thought" in keys and "action" in keys:
        return True
    if parsed.get("type") == "tool_use" and "input" in keys:
        return True
    return False


def _rescue_react_payload(parsed: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the actual payload from a ReAct/tool-calling wrapper if possible."""
    action_input = parsed.get("action_input")
    if isinstance(action_input, dict):
        return action_input
    if parsed.get("type") == "tool_use":
        tool_input = parsed.get("input")
        if isinstance(tool_input, dict):
            return tool_input
    return None


def _try_normalize(
    normalized: str,
    expected_keys: frozenset[str],
    context: str,
    workspace: Path | None,
) -> tuple[dict[str, Any] | None, str, str, list[str], bool]:
    """Single-attempt parse and normalize.

    Returns (result, next_correction_prompt, failure_kind, stripped_keys, react_rescued).
    failure_kind: 'json' | 'shape' | 'react'.
    result is None on any failure.
    """
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError:
        return None, _CORRECTION_PROMPT, "json", [], False

    if not isinstance(parsed, dict):
        return None, _OBJECT_CORRECTION_PROMPT, "shape", [], False

    react_rescued = False
    if _is_react_format(parsed):
        rescued = _rescue_react_payload(parsed)
        if rescued is not None:
            logger.debug("%s: rescued payload from ReAct/tool-calling wrapper", context)
            parsed = rescued
            react_rescued = True
        else:
            logger.debug(
                "%s: ReAct format detected but action_input is not a dict; retrying", context
            )
            return None, _REACT_CORRECTION_PROMPT, "react", [], False

    extra = set(parsed.keys()) - expected_keys
    stripped: list[str] = []
    if extra:
        stripped = sorted(extra)
        logger.warning("%s: stripping unexpected keys: %s", context, stripped)
        for k in extra:
            del parsed[k]
        _log_stripped_keys(workspace, stripped, context)

    return parsed, "", "", stripped, react_rescued


def parse_model_output(
    text: str,
    expected_keys: frozenset[str],
    *,
    context: str,
    workspace: Path | None = None,
    retry_fn: Callable[[str], str] | None = None,
    fallback_fn: Callable[[str], str] | None = None,
) -> tuple[dict[str, Any], ParseRecoveryRecord]:
    """Parse raw model text into a clean JSON dict, with a recovery record.

    Normalization pipeline (applied to initial text and each retry):
    1. Strip markdown fences and size-check (_extract_json_candidate).
    2. Extract JSON from prose (first { to last }).
    3. Parse JSON; detect and rescue ReAct/tool-calling wrappers.
    4. Verify result is a dict.
    5. Strip keys not in expected_keys; log warning + blackboard event.
    6. Return cleaned dict and ParseRecoveryRecord describing what recovery occurred.

    On failure: retry up to _MAX_RETRIES times via retry_fn with a targeted
    correction prompt (different prompts for JSON errors, shape errors, and
    ReAct format). On retry exhaustion: escalate to fallback_fn if provided
    (one attempt with a final correction prompt). Raises ValueError if all
    attempts fail.
    """
    retry_used = False

    normalized = _extract_json_candidate(text)
    result, next_prompt, failure_kind, stripped_keys, react_rescued = _try_normalize(
        normalized, expected_keys, context, workspace
    )
    if result is not None:
        return result, ParseRecoveryRecord(
            unexpected_keys_stripped=stripped_keys,
            response_shape_rescued=react_rescued,
        )

    last_failure_kind = failure_kind

    for attempt in range(_MAX_RETRIES):
        if retry_fn is None:
            break
        retry_used = True
        logger.debug(
            "%s: parse failed [%s] (attempt %d/%d), retrying with correction prompt",
            context, failure_kind, attempt + 1, _MAX_RETRIES,
        )
        try:
            raw = retry_fn(next_prompt)
        except Exception as exc:  # noqa: BLE001
            logger.debug("%s: retry_fn raised on attempt %d: %s", context, attempt + 1, exc)
            break
        normalized = _extract_json_candidate(raw)
        result, next_prompt, failure_kind, stripped_keys, react_rescued = _try_normalize(
            normalized, expected_keys, context, workspace
        )
        last_failure_kind = failure_kind
        if result is not None:
            return result, ParseRecoveryRecord(
                unexpected_keys_stripped=stripped_keys,
                response_shape_rescued=react_rescued,
                retry_used=True,
            )

    if fallback_fn is not None:
        logger.warning(
            "%s: primary model exhausted %d retries; escalating to fallback model",
            context, _MAX_RETRIES,
        )
        try:
            raw = fallback_fn(_FALLBACK_CORRECTION_PROMPT)
        except RuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s: fallback_fn raised: %s", context, exc)
        else:
            normalized = _extract_json_candidate(raw)
            result, _, failure_kind, stripped_keys, react_rescued = _try_normalize(
                normalized, expected_keys, context, workspace
            )
            if result is not None:
                return result, ParseRecoveryRecord(
                    unexpected_keys_stripped=stripped_keys,
                    response_shape_rescued=react_rescued,
                    retry_used=retry_used,
                    fallback_used=True,
                )
            last_failure_kind = failure_kind

    if last_failure_kind == "shape":
        raise ValueError(f"{context}: model output must be a JSON object")
    raise ValueError(f"{context}: model output must be valid JSON")


def wrap_json_prompt(text: str) -> str:
    """Wrap a prompt with the JSON-only instruction at both top and bottom."""
    return f"{_JSON_ONLY_INSTRUCTION}\n\n{text}\n\n{_JSON_ONLY_INSTRUCTION}"


def _log_stripped_keys(workspace: Path | None, stripped_keys: list[str], context: str) -> None:
    """Handle log stripped keys."""
    if workspace is None:
        return
    blackboard_dir = workspace / _BLACKBOARD_DIR
    blackboard_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "event": BlackboardEvent.UNEXPECTED_KEYS_STRIPPED,
        "context": context,
        "stripped_keys": stripped_keys,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    with (blackboard_dir / _STRIPPED_KEYS_FILE).open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
