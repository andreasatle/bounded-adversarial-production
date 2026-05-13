from pathlib import Path

import pytest

from baps.blackboard import Blackboard
from baps.play_game import build_parser, load_context_files, main, run_play_game


class FakeOllamaClient:
    last_model = None
    last_base_url = None
    prompts = []

    def __init__(self, model: str, base_url: str):
        FakeOllamaClient.last_model = model
        FakeOllamaClient.last_base_url = base_url
        FakeOllamaClient.prompts = []
        self._responses = [
            "Candidate answer",
            "Concrete critique of candidate",
            "Concise rationale for fixed decision",
            "Candidate answer revised",
            "Concrete critique of revised candidate",
            "Concise rationale for fixed decision round 2",
        ]
        self._index = 0

    def generate(self, prompt: str) -> str:
        if self._index >= len(self._responses):
            raise RuntimeError("no more fake responses")
        FakeOllamaClient.prompts.append(prompt)
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
    assert args.max_rounds == 1


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


def test_build_parser_explicit_max_rounds_overrides_default() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["--subject", "s", "--goal", "g", "--target-kind", "repo", "--max-rounds", "3"]
    )
    assert args.max_rounds == 3


def test_build_parser_rejects_max_rounds_less_than_one() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["--subject", "s", "--goal", "g", "--target-kind", "repo", "--max-rounds", "0"]
        )


def test_build_parser_red_material_defaults_true_and_can_be_disabled() -> None:
    parser = build_parser()
    args_default = parser.parse_args(["--subject", "s", "--goal", "g", "--target-kind", "repo"])
    assert args_default.red_material is True

    args_non_material = parser.parse_args(
        ["--subject", "s", "--goal", "g", "--target-kind", "repo", "--red-non-material"]
    )
    assert args_non_material.red_material is False


def test_build_parser_repeated_context_file_args(monkeypatch) -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "--subject",
            "s",
            "--goal",
            "g",
            "--target-kind",
            "repo",
            "--context-file",
            "a.txt",
            "--context-file",
            "b.txt",
        ]
    )
    assert args.context_file == ["a.txt", "b.txt"]


def test_load_context_files_concatenates_with_separators(tmp_path: Path) -> None:
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")

    context = load_context_files([str(first), str(second)])
    assert f"===== FILE: {first} =====" in context
    assert "alpha" in context
    assert f"===== FILE: {second} =====" in context
    assert "beta" in context


def test_load_context_files_missing_file_raises(tmp_path: Path) -> None:
    missing = tmp_path / "missing.txt"
    with pytest.raises(FileNotFoundError):
        load_context_files([str(missing)])


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


def test_run_play_game_respects_max_rounds_override(tmp_path: Path, monkeypatch) -> None:
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
        max_rounds=2,
    )

    assert len(state.rounds) == 2


def test_run_play_game_red_non_material_can_lead_to_accept(tmp_path: Path, monkeypatch) -> None:
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
        red_material=False,
    )
    assert state.final_decision is not None
    assert state.final_decision.decision == "accept"


def test_run_play_game_injects_shared_context_into_prompts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("baps.play_game.OllamaClient", FakeOllamaClient)
    path = tmp_path / "play-events.jsonl"
    shared = "Repository context snippet"

    run_play_game(
        subject="subject",
        goal="goal",
        target_kind="repo",
        target_ref="main",
        model="model-x",
        base_url="http://url-x",
        blackboard_path=path,
        shared_context=shared,
    )

    assert len(FakeOllamaClient.prompts) == 3
    assert all(shared in prompt for prompt in FakeOllamaClient.prompts)


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
    assert "rounds_played=1" in output
    assert "max_rounds=1" in output
    assert "terminal_reason=round_budget_exhausted" in output
    assert "blue_summary=Candidate answer" in output
    assert "red_claim=Concrete critique of candidate" in output
    assert "red_block_integration=False" in output
    assert "referee_decision=revise" in output
    assert "referee_rationale=Concise rationale for fixed decision" in output
    assert "round_1_decision=revise" in output
    assert "round_1_blue_summary=Candidate answer" in output
    assert "round_1_red_claim=Concrete critique of candidate" in output
    assert "round_1_referee_rationale=Concise rationale for fixed decision" in output
    assert "blackboard_path=" in output


def test_main_prints_multiple_round_summaries_for_revise_loop(monkeypatch, capsys, tmp_path: Path) -> None:
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
            "--max-rounds",
            "2",
            "--blackboard-path",
            str(tmp_path / "events.jsonl"),
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "round_1_decision=revise" in output
    assert "round_2_decision=revise" in output
    assert "round_2_blue_summary=Candidate answer revised" in output
