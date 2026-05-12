from pathlib import Path

from baps.blackboard import Blackboard
from baps.ollama_adversarial_demo import main, run_ollama_adversarial_demo


class FakeOllamaClient:
    last_model = None
    last_base_url = None

    def __init__(self, model: str, base_url: str):
        FakeOllamaClient.last_model = model
        FakeOllamaClient.last_base_url = base_url
        self._responses = [
            "Candidate: run uv sync then uv run baps-demo.",
            "Critique: candidate does not mention expected output fields.",
            "Rationale: criticism is not blocking, so accept with follow-up edits.",
        ]
        self._idx = 0

    def generate(self, prompt: str) -> str:
        if self._idx >= len(self._responses):
            raise RuntimeError("no more fake responses")
        value = self._responses[self._idx]
        self._idx += 1
        return value


def test_run_ollama_demo_records_expected_event_sequence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("baps.ollama_adversarial_demo.OllamaClient", FakeOllamaClient)
    path = tmp_path / "ollama-events.jsonl"

    state = run_ollama_adversarial_demo(path)

    events = Blackboard(path).read_all()
    assert state.game_id == "ollama-adversarial-demo-001"
    assert [event.type for event in events] == [
        "game_started",
        "blue_move_recorded",
        "red_finding_recorded",
        "referee_decision_recorded",
        "game_completed",
    ]


def test_ollama_demo_uses_env_configuration(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("baps.ollama_adversarial_demo.OllamaClient", FakeOllamaClient)
    monkeypatch.setenv("BAPS_OLLAMA_MODEL", "custom-model")
    monkeypatch.setenv("BAPS_OLLAMA_BASE_URL", "http://example.test:11434")

    run_ollama_adversarial_demo(tmp_path / "events.jsonl")

    assert FakeOllamaClient.last_model == "custom-model"
    assert FakeOllamaClient.last_base_url == "http://example.test:11434"


def test_ollama_demo_uses_default_configuration_when_env_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("baps.ollama_adversarial_demo.OllamaClient", FakeOllamaClient)
    monkeypatch.delenv("BAPS_OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("BAPS_OLLAMA_BASE_URL", raising=False)

    run_ollama_adversarial_demo(tmp_path / "events.jsonl")

    assert FakeOllamaClient.last_model == "gemma3"
    assert FakeOllamaClient.last_base_url == "http://localhost:11434"


def test_ollama_demo_main_prints_expected_fields(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr("baps.ollama_adversarial_demo.OllamaClient", FakeOllamaClient)
    monkeypatch.chdir(tmp_path)

    main()

    output = capsys.readouterr().out
    assert "game_id=ollama-adversarial-demo-001" in output
    assert "run_id=run-" in output
    assert "blue_summary=" in output
    assert "red_claim=" in output
    assert "red_block_integration=False" in output
    assert "referee_decision=revise" in output
    assert "referee_rationale=" in output
    assert "blackboard_path=blackboard/ollama-adversarial-events.jsonl" in output
