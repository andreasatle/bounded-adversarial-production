from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from baps.model_output import _STRIPPED_KEYS_FILE, _BLACKBOARD_DIR, parse_model_output


_KEYS = frozenset({"a", "b", "c"})


# --- clean passthrough ---

def test_clean_response_passthrough() -> None:
    text = json.dumps({"a": 1, "b": 2, "c": 3})
    result = parse_model_output(text, _KEYS, context="test")
    assert result == {"a": 1, "b": 2, "c": 3}


def test_subset_of_expected_keys_passes() -> None:
    text = json.dumps({"a": 1})
    result = parse_model_output(text, _KEYS, context="test")
    assert result == {"a": 1}


def test_markdown_fence_stripped() -> None:
    text = "```json\n" + json.dumps({"a": 1}) + "\n```"
    result = parse_model_output(text, _KEYS, context="test")
    assert result == {"a": 1}


# --- extra keys stripped ---

def test_extra_keys_stripped() -> None:
    text = json.dumps({"a": 1, "b": 2, "reasoning": "step by step", "confidence": 0.9})
    result = parse_model_output(text, _KEYS, context="test")
    assert result == {"a": 1, "b": 2}
    assert "reasoning" not in result
    assert "confidence" not in result


def test_extra_keys_logged_as_warning(caplog) -> None:
    text = json.dumps({"a": 1, "thoughts": "hmm"})
    with caplog.at_level(logging.WARNING, logger="baps.model_output"):
        parse_model_output(text, _KEYS, context="myctx")
    assert "myctx" in caplog.text
    assert "thoughts" in caplog.text


def test_extra_keys_written_to_blackboard(tmp_path: Path) -> None:
    text = json.dumps({"a": 1, "extra_field": "noise"})
    parse_model_output(text, _KEYS, context="test:ctx", workspace=tmp_path)
    log_path = tmp_path / _BLACKBOARD_DIR / _STRIPPED_KEYS_FILE
    assert log_path.exists()
    entry = json.loads(log_path.read_text())
    assert entry["event"] == "unexpected_keys_stripped"
    assert entry["context"] == "test:ctx"
    assert entry["stripped_keys"] == ["extra_field"]


def test_no_blackboard_entry_when_no_extra_keys(tmp_path: Path) -> None:
    text = json.dumps({"a": 1})
    parse_model_output(text, _KEYS, context="test", workspace=tmp_path)
    assert not (tmp_path / _BLACKBOARD_DIR / _STRIPPED_KEYS_FILE).exists()


def test_no_blackboard_write_when_workspace_is_none() -> None:
    text = json.dumps({"a": 1, "extra": "noise"})
    parse_model_output(text, _KEYS, context="test", workspace=None)
    # just verify no exception raised; no file to check


# --- invalid JSON retry ---

def test_invalid_json_raises_without_retry_fn() -> None:
    with pytest.raises(ValueError, match="must be valid JSON"):
        parse_model_output("not-json", _KEYS, context="test")


def test_invalid_json_retries_via_retry_fn() -> None:
    valid = json.dumps({"a": 1})
    calls: list[str] = []

    def retry_fn(prompt: str) -> str:
        calls.append(prompt)
        return valid

    result = parse_model_output("not-json", _KEYS, context="test", retry_fn=retry_fn)
    assert result == {"a": 1}
    assert len(calls) == 1


def test_invalid_json_exhausts_retries_then_raises() -> None:
    calls: list[str] = []

    def retry_fn(prompt: str) -> str:
        calls.append(prompt)
        return "still-not-json"

    with pytest.raises(ValueError, match="must be valid JSON"):
        parse_model_output("not-json", _KEYS, context="test", retry_fn=retry_fn)
    assert len(calls) == 2  # _MAX_RETRIES = 2


def test_retry_logs_debug_message(caplog) -> None:
    valid = json.dumps({"a": 1})

    def retry_fn(prompt: str) -> str:
        return valid

    with caplog.at_level(logging.DEBUG, logger="baps.model_output"):
        parse_model_output("not-json", _KEYS, context="retryctx", retry_fn=retry_fn)
    assert "retryctx" in caplog.text
    assert "retrying with correction prompt" in caplog.text


# --- non-dict JSON ---

def test_json_array_raises() -> None:
    with pytest.raises(ValueError, match="must be a JSON object"):
        parse_model_output("[1, 2, 3]", _KEYS, context="test")


def test_json_string_raises() -> None:
    with pytest.raises(ValueError, match="must be a JSON object"):
        parse_model_output('"hello"', _KEYS, context="test")


# --- context prefix in error messages ---

def test_context_prefix_in_json_error() -> None:
    with pytest.raises(ValueError, match="mycontext: model output must be valid JSON"):
        parse_model_output("bad", _KEYS, context="mycontext")


def test_context_prefix_in_object_error() -> None:
    with pytest.raises(ValueError, match="mycontext: model output must be a JSON object"):
        parse_model_output("[1]", _KEYS, context="mycontext")
