from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any, Callable

from baps.project_adapter import normalize_json_candidate

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
_BLACKBOARD_DIR = "blackboard"
_STRIPPED_KEYS_FILE = "stripped_keys.jsonl"


def parse_model_output(
    text: str,
    expected_keys: frozenset[str],
    *,
    context: str,
    workspace: Path | None = None,
    retry_fn: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """
    Parse raw model text into a clean JSON dict.

    1. Strip markdown fences and validate size (normalize_json_candidate).
    2. Parse JSON; on failure, retry via retry_fn with a correction prompt up to _MAX_RETRIES times.
    3. Verify the result is a dict.
    4. Strip keys not in expected_keys; log warning and write a blackboard event if workspace given.
    5. Return the cleaned dict — callers do domain-specific validation.
    """
    normalized = normalize_json_candidate(text)
    parsed: dict[str, Any] | None = None
    last_exc: json.JSONDecodeError | None = None

    for attempt in range(_MAX_RETRIES + 1):
        try:
            result = json.loads(normalized)
            if not isinstance(result, dict):
                raise ValueError(f"{context}: model output must be a JSON object")
            parsed = result
            break
        except json.JSONDecodeError as exc:
            last_exc = exc
            if retry_fn is None or attempt >= _MAX_RETRIES:
                break
            logger.debug(
                "%s: JSON parse failed (attempt %d/%d), retrying with correction prompt",
                context,
                attempt + 1,
                _MAX_RETRIES,
            )
            normalized = normalize_json_candidate(retry_fn(_CORRECTION_PROMPT))

    if parsed is None:
        raise ValueError(f"{context}: model output must be valid JSON") from last_exc

    extra = set(parsed.keys()) - expected_keys
    if extra:
        logger.warning("%s: stripping unexpected keys: %s", context, sorted(extra))
        for k in extra:
            del parsed[k]
        _log_stripped_keys(workspace, sorted(extra), context)

    return parsed


def wrap_json_prompt(text: str) -> str:
    """Wrap a prompt with the JSON-only instruction at both top and bottom."""
    return f"{_JSON_ONLY_INSTRUCTION}\n\n{text}\n\n{_JSON_ONLY_INSTRUCTION}"


def _log_stripped_keys(workspace: Path | None, stripped_keys: list[str], context: str) -> None:
    if workspace is None:
        return
    blackboard_dir = workspace / _BLACKBOARD_DIR
    blackboard_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "event": "unexpected_keys_stripped",
        "context": context,
        "stripped_keys": stripped_keys,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    with (blackboard_dir / _STRIPPED_KEYS_FILE).open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
