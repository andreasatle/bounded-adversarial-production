from __future__ import annotations

import logging

from baps.core.debug import debug_event


def test_debug_event_renders_nested_payload_yaml_like(caplog) -> None:
    payload = {
        "game_spec": {"objective": "Test objective", "success_condition": "done"},
        "attempt_number": 2,
        "findings": ["a", "b"],
    }
    with caplog.at_level(logging.DEBUG, logger="baps.core.debug"):
        debug_event("blue.input", payload)
    assert "blue.input:" in caplog.text
    assert "game_spec:" in caplog.text
    assert "objective: Test objective" in caplog.text
    assert "attempt_number: 2" in caplog.text
    assert "- a" in caplog.text


def test_debug_event_emits_nothing_when_debug_disabled(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="baps.core.debug"):
        debug_event("blue.input", {"x": 1})
    assert "blue.input:" not in caplog.text
