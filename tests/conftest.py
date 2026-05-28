"""Shared fixtures for the baps test suite.

This conftest provides the autouse _patch_create_game_model_client fixture used by all test files.
"""
from __future__ import annotations

import pytest

from baps.models.models import FakeModelClient, ToolCall


@pytest.fixture(autouse=True)
def _patch_create_game_model_client(monkeypatch):
    create_game_response = (
        '{"objective":"Advance goal","target_artifact_id":"main-document",'
        '"allowed_delta_type":"DeltaDocumentState",'
        '"success_condition":"PlayGame must return a valid DeltaDocumentState targeting main-document."}'
    )
    blue_tool_response = ToolCall(
        name="append_section",
        arguments={"artifact_id": "main-document", "title": "Introduction", "body": "Advance goal"},
    )
    red_response = '{"disposition":"accept","rationale":"deterministic test path"}'

    def _fake_create_game_builder():
        return FakeModelClient([create_game_response])

    # Each factory call returns a fresh client that works for any role:
    # generate_with_tools → blue_tool_response; generate → accept_response (red/referee share the same text).
    def _fake_model_client_builder():
        return FakeModelClient(
            responses=[red_response],
            tool_responses=[blue_tool_response],
        )

    # Primary patch: _build_client_for_role is the call site used by create_game, play_game,
    # and _solve_gap.  Route create_game/decompose/create_game_red to the planner fake and all
    # other roles (blue/red/referee) to the play-game fake.
    def _fake_build_client_for_role(role, config):
        if role in ("create_game", "decompose", "create_game_red"):
            return _fake_create_game_builder()
        return _fake_model_client_builder()

    monkeypatch.setattr("baps.game.engine._build_client_for_role", _fake_build_client_for_role)
    monkeypatch.setattr("baps.core.orchestration._build_client_for_role", _fake_build_client_for_role)
    monkeypatch.setattr("baps.game.engine._build_role_client", lambda _role: _fake_model_client_builder())
    # Fallback resolution returns no chain by default (no fallback configured in tests).
    monkeypatch.setattr("baps.game.engine._build_fallback_chain_for_role", lambda role, config: [])
