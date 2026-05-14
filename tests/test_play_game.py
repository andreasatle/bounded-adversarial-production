import json
from pathlib import Path

import pytest

from baps.blackboard import Blackboard
from baps.game_types import GameDefinition, GameTypePromptSections, load_game_definition
from baps.play_game import build_parser, load_context_files, main, run_play_game
from baps.prompt_assembly import PromptSection


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
    args = parser.parse_args([])
    assert args.subject is None
    assert args.goal is None
    assert args.target_kind is None


def test_build_parser_uses_env_defaults(monkeypatch) -> None:
    monkeypatch.setenv("BAPS_OLLAMA_MODEL", "env-model")
    monkeypatch.setenv("BAPS_OLLAMA_BASE_URL", "http://env-url:11434")
    parser = build_parser()

    args = parser.parse_args(["--subject", "s", "--goal", "g", "--target-kind", "repo"])
    assert args.model is None
    assert args.base_url is None
    assert args.game_type is None
    assert args.max_rounds is None


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


def test_build_parser_explicit_game_type_override() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "--subject",
            "s",
            "--goal",
            "g",
            "--target-kind",
            "repo",
            "--game-type",
            "documentation-refinement",
        ]
    )
    assert args.game_type == "documentation-refinement"


def test_build_parser_accepts_game_definition_file() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "--subject",
            "s",
            "--goal",
            "g",
            "--target-kind",
            "repo",
            "--game-definition-file",
            "game.json",
        ]
    )
    assert args.game_definition_file == "game.json"


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
    assert args_default.red_material is None

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


def test_build_parser_accepts_state_manifest_and_repeated_state_source_args() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "--subject",
            "s",
            "--goal",
            "g",
            "--target-kind",
            "repo",
            "--state-manifest",
            "manifest.json",
            "--state-source",
            "architecture",
            "--state-source",
            "roadmap",
        ]
    )
    assert args.state_manifest == "manifest.json"
    assert args.state_source == ["architecture", "roadmap"]


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


def test_run_play_game_uses_default_documentation_refinement_definition(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("baps.play_game.OllamaClient", FakeOllamaClient)
    path = tmp_path / "play-events.jsonl"

    run_play_game(
        subject="subject",
        goal="goal",
        target_kind="repo",
        target_ref="main",
        model="model-x",
        base_url="http://url-x",
        blackboard_path=path,
    )

    # Default documentation-refinement prompt sections should be present.
    assert any("Game type is documentation refinement." in prompt for prompt in FakeOllamaClient.prompts)
    assert any("Red critiques only the current Blue-produced delta from this game." in prompt for prompt in FakeOllamaClient.prompts)
    assert any("Referee converges toward correctness and clarity." in prompt for prompt in FakeOllamaClient.prompts)


def test_run_play_game_resolves_builtin_game_type(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("baps.play_game.OllamaClient", FakeOllamaClient)
    path = tmp_path / "play-events.jsonl"

    run_play_game(
        subject="subject",
        goal="goal",
        target_kind="repo",
        target_ref="main",
        model="model-x",
        base_url="http://url-x",
        blackboard_path=path,
        game_type="documentation-refinement",
    )

    assert any("Game type is documentation refinement." in prompt for prompt in FakeOllamaClient.prompts)


def test_run_play_game_supports_custom_game_definition_prompt_sections(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("baps.play_game.OllamaClient", FakeOllamaClient)
    path = tmp_path / "play-events.jsonl"
    custom_definition = GameDefinition(
        id="custom-game",
        name="Custom Game",
        description="custom",
        prompt_sections=GameTypePromptSections(
            blue_sections=[PromptSection(name="Blue Custom", content="Blue custom guidance.")],
            red_sections=[PromptSection(name="Red Custom", content="Red custom guidance.")],
            referee_sections=[PromptSection(name="Ref Custom", content="Ref custom guidance.")],
        ),
    )

    run_play_game(
        subject="subject",
        goal="goal",
        target_kind="repo",
        target_ref="main",
        model="model-x",
        base_url="http://url-x",
        blackboard_path=path,
        game_definition=custom_definition,
    )

    assert any("Blue custom guidance." in prompt for prompt in FakeOllamaClient.prompts)
    assert any("Red custom guidance." in prompt for prompt in FakeOllamaClient.prompts)
    assert any("Ref custom guidance." in prompt for prompt in FakeOllamaClient.prompts)


def test_run_play_game_accepts_loaded_example_game_definition(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("baps.play_game.OllamaClient", FakeOllamaClient)
    path = tmp_path / "play-events.jsonl"
    definition = load_game_definition(Path("examples/game_definitions/documentation_refinement.json"))

    state = run_play_game(
        subject="subject",
        goal="goal",
        target_kind="repo",
        target_ref="main",
        model="model-x",
        base_url="http://url-x",
        blackboard_path=path,
        game_definition=definition,
    )

    assert state.game_id == "play-game-001"
    assert len(FakeOllamaClient.prompts) == 3


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
    assert "game_type=documentation-refinement" in output
    assert "game_definition_id=documentation-refinement" in output
    assert "game_definition_name=Documentation Refinement" in output
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


def test_main_without_run_spec_preserves_required_argument_behavior(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("sys.argv", ["baps-play-game", "--subject", "only-subject"])
    with pytest.raises(SystemExit):
        main()


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


def test_main_rejects_state_source_without_manifest(monkeypatch, tmp_path: Path) -> None:
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
            "--state-source",
            "architecture",
            "--blackboard-path",
            str(tmp_path / "events.jsonl"),
        ],
    )
    with pytest.raises(SystemExit):
        main()


def test_main_rejects_manifest_without_state_source(monkeypatch, tmp_path: Path) -> None:
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
            "--state-manifest",
            "examples/state_manifests/baps_project_state.json",
            "--blackboard-path",
            str(tmp_path / "events.jsonl"),
        ],
    )
    with pytest.raises(SystemExit):
        main()


def test_main_injects_manual_and_manifest_context_into_prompts(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("baps.play_game.OllamaClient", FakeOllamaClient)
    context_file = tmp_path / "extra_context.txt"
    context_file.write_text("manual-context-fragment", encoding="utf-8")

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
            "--context-file",
            str(context_file),
            "--state-manifest",
            "examples/state_manifests/baps_project_state.json",
            "--state-source",
            "architecture",
            "--state-source",
            "roadmap",
            "--blackboard-path",
            str(tmp_path / "events.jsonl"),
        ],
    )

    main()
    assert len(FakeOllamaClient.prompts) >= 1
    prompt = FakeOllamaClient.prompts[0]
    assert "manual-context-fragment" in prompt
    assert "===== STATE SOURCE: architecture (markdown_doc, authority=descriptive) =====" in prompt
    assert "===== STATE SOURCE: roadmap (markdown_doc, authority=directional) =====" in prompt


def test_main_routes_state_source_ids_through_game_request(monkeypatch, tmp_path: Path) -> None:
    captured = {"state_source_ids": None}

    class _StubService:
        def __init__(self, **_kwargs):
            pass

        def play(self, request):
            captured["state_source_ids"] = list(request.state_source_ids)

            class _Result:
                game_id = "play-game-001"
                run_id = "run-20260513-100000-deadbeef"
                rounds_played = 1
                max_rounds = 1
                terminal_reason = "accepted"
                final_blue_summary = "blue"
                final_red_claim = "red"

                class _Decision:
                    decision = "accept"
                    rationale = "rationale"

                final_decision = _Decision()
                round_summaries = []

            return _Result()

    monkeypatch.setattr("baps.play_game.GameService", _StubService)
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
            "--state-manifest",
            "examples/state_manifests/baps_project_state.json",
            "--state-source",
            "architecture",
            "--state-source",
            "roadmap",
            "--blackboard-path",
            str(tmp_path / "events.jsonl"),
        ],
    )

    main()
    assert captured["state_source_ids"] == ["architecture", "roadmap"]


def test_main_with_run_spec_allows_omitting_subject_goal_target_kind(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("baps.play_game.OllamaClient", FakeOllamaClient)
    run_spec = tmp_path / "run.yaml"
    run_spec.write_text(
        "\n".join(
            [
                "model:",
                "  provider: ollama",
                "  name: spec-model",
                "  base_url: http://spec-url:11434",
                "game:",
                "  type: documentation-refinement",
                "  subject: Spec Subject",
                "  goal: Spec Goal",
                "  target_kind: documentation",
                "  target_ref: README.md",
                "  max_rounds: 1",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-play-game",
            "--run-spec",
            str(run_spec),
            "--blackboard-path",
            str(tmp_path / "events.jsonl"),
        ],
    )
    main()
    assert FakeOllamaClient.last_model == "spec-model"
    assert FakeOllamaClient.last_base_url == "http://spec-url:11434"


def test_main_cli_overrides_run_spec_scalars(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("baps.play_game.OllamaClient", FakeOllamaClient)
    run_spec = tmp_path / "run.yaml"
    run_spec.write_text(
        "\n".join(
            [
                "model:",
                "  provider: ollama",
                "  name: spec-model",
                "  base_url: http://spec-url:11434",
                "game:",
                "  type: documentation-refinement",
                "  subject: Spec Subject",
                "  goal: Spec Goal",
                "  target_kind: documentation",
                "  target_ref: README.md",
                "  max_rounds: 1",
                "  red_material: true",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-play-game",
            "--run-spec",
            str(run_spec),
            "--model",
            "cli-model",
            "--base-url",
            "http://cli-url:11434",
            "--subject",
            "CLI Subject",
            "--goal",
            "CLI Goal",
            "--target-kind",
            "repo",
            "--target-ref",
            "main",
            "--max-rounds",
            "2",
            "--red-non-material",
            "--blackboard-path",
            str(tmp_path / "events.jsonl"),
        ],
    )
    main()
    assert FakeOllamaClient.last_model == "cli-model"
    assert FakeOllamaClient.last_base_url == "http://cli-url:11434"


def test_main_context_files_append_run_spec_context_files(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("baps.play_game.OllamaClient", FakeOllamaClient)
    spec_ctx = tmp_path / "spec_ctx.md"
    cli_ctx = tmp_path / "cli_ctx.md"
    spec_ctx.write_text("spec-context", encoding="utf-8")
    cli_ctx.write_text("cli-context", encoding="utf-8")
    run_spec = tmp_path / "run.yaml"
    run_spec.write_text(
        "\n".join(
            [
                "model:",
                "  provider: ollama",
                "  name: spec-model",
                "game:",
                "  type: documentation-refinement",
                "  subject: Spec Subject",
                "  goal: Spec Goal",
                "  target_kind: documentation",
                "context_files:",
                f"  - {spec_ctx}",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-play-game",
            "--run-spec",
            str(run_spec),
            "--context-file",
            str(cli_ctx),
            "--blackboard-path",
            str(tmp_path / "events.jsonl"),
        ],
    )
    main()
    prompt = FakeOllamaClient.prompts[0]
    assert "spec-context" in prompt
    assert "cli-context" in prompt


def test_main_injects_typed_context_entries_with_labels(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("baps.play_game.OllamaClient", FakeOllamaClient)
    goals = tmp_path / "goals.md"
    state = tmp_path / "state.md"
    goals.write_text("goals-content", encoding="utf-8")
    state.write_text("state-content", encoding="utf-8")
    run_spec = tmp_path / "run.yaml"
    run_spec.write_text(
        "\n".join(
            [
                "model:",
                "  provider: ollama",
                "  name: spec-model",
                "game:",
                "  type: documentation-refinement",
                "  subject: Spec Subject",
                "  goal: Spec Goal",
                "  target_kind: documentation",
                "context:",
                "  - id: goals_doc",
                "    role: goals",
                f"    ref: {goals}",
                "    authority: context",
                "  - id: current_state_doc",
                "    role: current_state",
                f"    ref: {state}",
                "    authority: evidence",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-play-game",
            "--run-spec",
            str(run_spec),
            "--blackboard-path",
            str(tmp_path / "events.jsonl"),
        ],
    )
    main()
    prompt = FakeOllamaClient.prompts[0]
    assert "===== CONTEXT: goals_doc (role=goals, authority=context) =====" in prompt
    assert "goals-content" in prompt
    assert "===== CONTEXT: current_state_doc (role=current_state, authority=evidence) =====" in prompt
    assert "state-content" in prompt


def test_main_context_files_appear_before_typed_context(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("baps.play_game.OllamaClient", FakeOllamaClient)
    ctx_file = tmp_path / "ctx.md"
    typed_file = tmp_path / "typed.md"
    ctx_file.write_text("context-file-content", encoding="utf-8")
    typed_file.write_text("typed-context-content", encoding="utf-8")
    run_spec = tmp_path / "run.yaml"
    run_spec.write_text(
        "\n".join(
            [
                "model:",
                "  provider: ollama",
                "  name: spec-model",
                "game:",
                "  type: documentation-refinement",
                "  subject: Spec Subject",
                "  goal: Spec Goal",
                "  target_kind: documentation",
                "context_files:",
                f"  - {ctx_file}",
                "context:",
                "  - id: typed_doc",
                "    role: current_state",
                f"    ref: {typed_file}",
                "    authority: context",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-play-game",
            "--run-spec",
            str(run_spec),
            "--blackboard-path",
            str(tmp_path / "events.jsonl"),
        ],
    )
    main()
    prompt = FakeOllamaClient.prompts[0]
    assert "===== FILE: " in prompt
    assert "===== CONTEXT: typed_doc (role=current_state, authority=context) =====" in prompt
    assert prompt.index("===== FILE: ") < prompt.index(
        "===== CONTEXT: typed_doc (role=current_state, authority=context) ====="
    )


def test_main_state_sources_append_run_spec_state_sources(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("baps.play_game.OllamaClient", FakeOllamaClient)
    run_spec = tmp_path / "run.yaml"
    run_spec.write_text(
        "\n".join(
            [
                "model:",
                "  provider: ollama",
                "  name: spec-model",
                "game:",
                "  type: documentation-refinement",
                "  subject: Spec Subject",
                "  goal: Spec Goal",
                "  target_kind: documentation",
                "state:",
                "  manifest: examples/state_manifests/baps_project_state.json",
                "  sources:",
                "    - architecture",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "baps-play-game",
            "--run-spec",
            str(run_spec),
            "--state-source",
            "roadmap",
            "--blackboard-path",
            str(tmp_path / "events.jsonl"),
        ],
    )
    main()
    prompt = FakeOllamaClient.prompts[0]
    assert "STATE SOURCE: architecture" in prompt
    assert "STATE SOURCE: roadmap" in prompt


def test_main_resolves_mixed_state_source_kinds_into_prompts(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("baps.play_game.OllamaClient", FakeOllamaClient)
    markdown_file = tmp_path / "doc.md"
    markdown_file.write_text("markdown-content", encoding="utf-8")
    directory_root = tmp_path / "definitions"
    directory_root.mkdir()
    (directory_root / "a.json").write_text("{}", encoding="utf-8")
    jsonl_file = tmp_path / "events.jsonl"
    jsonl_file.write_text('{"id":"e1","type":"x","payload":{}}\n', encoding="utf-8")
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(
        json.dumps(
            {
                "project_id": "baps",
                "sources": [
                    {
                        "id": "md",
                        "kind": "markdown_doc",
                        "ref": str(markdown_file),
                        "authority": "descriptive",
                    },
                    {
                        "id": "dir",
                        "kind": "directory",
                        "ref": str(directory_root),
                        "authority": "configuration",
                    },
                    {
                        "id": "events",
                        "kind": "jsonl_event_log",
                        "ref": str(jsonl_file),
                        "authority": "evidence",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

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
            "--state-manifest",
            str(manifest_file),
            "--state-source",
            "md",
            "--state-source",
            "dir",
            "--state-source",
            "events",
            "--blackboard-path",
            str(tmp_path / "play-events.jsonl"),
        ],
    )

    main()
    prompt = FakeOllamaClient.prompts[0]
    assert "STATE SOURCE: md (markdown_doc, authority=descriptive)" in prompt
    assert "markdown-content" in prompt
    assert "STATE SOURCE: dir (directory, authority=configuration)" in prompt
    assert f"DIRECTORY: {directory_root}" in prompt
    assert "STATE SOURCE: events (jsonl_event_log, authority=evidence)" in prompt


def test_main_game_definition_file_overrides_game_type(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr("baps.play_game.OllamaClient", FakeOllamaClient)
    definition_path = tmp_path / "custom-game-definition.json"
    definition_path.write_text(
        json.dumps(
            {
                "id": "json-custom",
                "name": "JSON Custom Game",
                "description": "from file",
                "prompt_sections": {
                    "blue_sections": [{"name": "Blue", "content": "blue file guidance"}],
                    "red_sections": [{"name": "Red", "content": "red file guidance"}],
                    "referee_sections": [{"name": "Ref", "content": "ref file guidance"}],
                },
            }
        ),
        encoding="utf-8",
    )
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
            "--game-type",
            "unknown-type",
            "--game-definition-file",
            str(definition_path),
            "--blackboard-path",
            str(tmp_path / "events.jsonl"),
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "game_definition_id=json-custom" in output
    assert "game_definition_name=JSON Custom Game" in output
    assert any("blue file guidance" in prompt for prompt in FakeOllamaClient.prompts)
    assert any("red file guidance" in prompt for prompt in FakeOllamaClient.prompts)
    assert any("ref file guidance" in prompt for prompt in FakeOllamaClient.prompts)
