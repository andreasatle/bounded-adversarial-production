from pathlib import Path

import pytest

from baps.blackboard import Blackboard
from baps.play_game import build_parser, main, run_play_game


class FakeOllamaClient:
    last_model = None
    last_base_url = None

    def __init__(self, model: str, base_url: str):
        FakeOllamaClient.last_model = model
        FakeOllamaClient.last_base_url = base_url
        self._responses = [
            "Candidate answer",
            "Concrete critique of candidate",
            "Concise rationale for fixed decision",
        ]
        self._index = 0

    def generate(self, prompt: str) -> str:
        if self._index >= len(self._responses):
            raise RuntimeError("no more fake responses")
        value = self._responses[self._index]
        self._index += 1
        return value


def test_build_parser_requires_subject_goal_and_target_kind() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_build_parser_uses_env_defaults(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_OLLAMA_MODEL", "env-model")
    monkeypatch.setenv("BAPS_OLLAMA_BASE_URL", "http://env-url:11434")
    parser = build_parser()

    args = parser.parse_args(["--subject", "s", "--goal", "g", "--target-kind", "repo"])
    assert args.model == "env-model"
    assert args.base_url == "http://env-url:11434"


def test_build_parser_explicit_args_override_env(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_OLLAMA_MODEL", "env-model")
    monkeypatch.setenv("BAPS_OLLAMA_BASE_URL", "http://env-url:11434")
    parser = build_parser()

    args = parser.parse_args(
        [
            "--subject",
            "s",
            "--goal",
            "g",
            "--target-kind",
            "repo",
            "--model",
            "cli-model",
            "--base-url",
            "http://cli-url:11434",
        ]
    )
    assert args.model == "cli-model"
    assert args.base_url == "http://cli-url:11434"


def test_run_play_game_records_expected_event_sequence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("baps.play_game.OllamaClient", FakeOllamaClient)
    path = tmp_path / "play-events.jsonl"

    state = run_play_game(
        subject="subject",
        goal="goal",
        target_kind="repo",
        target_ref="main",
        model="model-x",
        base_url="http://url-x",
        blackboard_path=path,
    )

    events = Blackboard(path).read_all()
    assert state.game_id == "play-game-001"
    assert [event.type for event in events] == [
        "game_started",
        "blue_move_recorded",
        "red_finding_recorded",
        "referee_decision_recorded",
        "game_completed",
    ]


def test_main_prints_expected_fields_and_uses_fake_client(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr("baps.play_game.OllamaClient", FakeOllamaClient)
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-play-game",
            "--subject",
            "README demo",
            "--goal",
            "Explain run command",
            "--target-kind",
            "document",
            "--target-ref",
            "README.md",
            "--blackboard-path",
            str(tmp_path / "events.jsonl"),
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "game_id=play-game-001" in output
    assert "run_id=run-" in output
    assert "subject=README demo" in output
    assert "goal=Explain run command" in output
    assert "target_kind=document" in output
    assert "target_ref=README.md" in output
    assert "blue_summary=Candidate answer" in output
    assert "red_claim=Concrete critique of candidate" in output
    assert "red_block_integration=False" in output
    assert "referee_decision=revise" in output
    assert "referee_rationale=Concise rationale for fixed decision" in output
    assert "blackboard_path=" in output
