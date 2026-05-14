from pathlib import Path

import pytest

from baps.blackboard import Blackboard
from baps.game_service import GameService
from baps.game_types import GameDefinition, GameTypePromptSections, make_documentation_refinement_game_definition
from baps.models import FakeModelClient
from baps.prompt_assembly import PromptSection
from baps.schemas import GameRequest, GameResponse
from baps.state_sources import MarkdownFileStateSourceAdapter, StateManifest, StateSourceDeclaration


def _request() -> GameRequest:
    return GameRequest(
        game_type="documentation-refinement",
        subject="README quickstart",
        goal="Improve clarity and remove redundancy",
        target_kind="documentation",
        target_ref="README.md",
    )


def test_game_service_play_returns_game_response(tmp_path: Path) -> None:
    model = FakeModelClient(
        responses=[
            "candidate answer",
            "MATERIAL: yes\nCLAIM: concrete issue",
            "rationale",
        ]
    )
    service = GameService(
        model_client=model,
        blackboard=Blackboard(tmp_path / "events.jsonl"),
    )

    response = service.play(_request())
    assert isinstance(response, GameResponse)
    assert response.game_id == "play-game-001"


def test_game_service_uses_default_build_game_definition_when_none_provided(tmp_path: Path, monkeypatch) -> None:
    model = FakeModelClient(
        responses=[
            "candidate answer",
            "MATERIAL: yes\nCLAIM: concrete issue",
            "rationale",
        ]
    )
    called = {"value": False}

    def _stub_build_game_definition(_request: GameRequest) -> GameDefinition:
        called["value"] = True
        return make_documentation_refinement_game_definition()

    monkeypatch.setattr("baps.game_service.build_game_definition", _stub_build_game_definition)
    service = GameService(
        model_client=model,
        blackboard=Blackboard(tmp_path / "events.jsonl"),
    )

    service.play(_request())
    assert called["value"] is True


def test_game_service_uses_explicit_game_definition_when_provided(tmp_path: Path, monkeypatch) -> None:
    model = FakeModelClient(
        responses=[
            "candidate answer",
            "MATERIAL: yes\nCLAIM: concrete issue",
            "rationale",
        ]
    )
    explicit_definition = GameDefinition(
        id="custom-game",
        name="Custom Game",
        description="custom",
        prompt_sections=GameTypePromptSections(
            blue_sections=[PromptSection(name="Blue Custom", content="Blue custom guidance.")],
            red_sections=[PromptSection(name="Red Custom", content="Red custom guidance.")],
            referee_sections=[PromptSection(name="Ref Custom", content="Ref custom guidance.")],
        ),
    )

    def _should_not_call(_request: GameRequest) -> GameDefinition:
        raise AssertionError("build_game_definition should not be called when game_definition is provided")

    monkeypatch.setattr("baps.game_service.build_game_definition", _should_not_call)
    service = GameService(
        model_client=model,
        blackboard=Blackboard(tmp_path / "events.jsonl"),
        game_definition=explicit_definition,
    )

    service.play(_request())
    assert any("Blue custom guidance." in prompt for prompt in model.prompts)
    assert any("Red custom guidance." in prompt for prompt in model.prompts)
    assert any("Ref custom guidance." in prompt for prompt in model.prompts)


def test_game_service_propagates_max_rounds_into_response(tmp_path: Path) -> None:
    model = FakeModelClient(
        responses=[
            "candidate answer round 1",
            "MATERIAL: yes\nCLAIM: issue round 1",
            "rationale round 1",
            "candidate answer round 2",
            "MATERIAL: no\nCLAIM: no required changes",
            "rationale round 2",
        ]
    )
    service = GameService(
        model_client=model,
        blackboard=Blackboard(tmp_path / "events.jsonl"),
        max_rounds=2,
    )

    response = service.play(_request())
    assert response.max_rounds == 2


def test_game_service_propagates_shared_context_into_prompts(tmp_path: Path) -> None:
    model = FakeModelClient(
        responses=[
            "candidate answer",
            "MATERIAL: yes\nCLAIM: concrete issue",
            "rationale",
        ]
    )
    shared_context = "Context fragment for grounding"
    service = GameService(
        model_client=model,
        blackboard=Blackboard(tmp_path / "events.jsonl"),
        shared_context=shared_context,
    )

    service.play(_request())
    assert len(model.prompts) == 3
    assert all(shared_context in prompt for prompt in model.prompts)


def test_game_service_red_material_false_can_accept(tmp_path: Path) -> None:
    model = FakeModelClient(
        responses=[
            "candidate answer",
            "CLAIM: minor note only",
            "rationale",
        ]
    )
    service = GameService(
        model_client=model,
        blackboard=Blackboard(tmp_path / "events.jsonl"),
        red_material=False,
    )

    response = service.play(_request())
    assert response.final_decision.decision == "accept"


def test_game_service_rejects_max_rounds_less_than_one(tmp_path: Path) -> None:
    model = FakeModelClient(responses=["unused"])
    with pytest.raises(ValueError, match="max_rounds must be >= 1"):
        GameService(
            model_client=model,
            blackboard=Blackboard(tmp_path / "events.jsonl"),
            max_rounds=0,
        )


def test_game_service_resolves_request_state_source_ids_with_manifest_and_adapter(tmp_path: Path) -> None:
    model = FakeModelClient(
        responses=[
            "candidate answer",
            "MATERIAL: yes\nCLAIM: concrete issue",
            "rationale",
        ]
    )
    state_file = tmp_path / "state.md"
    state_file.write_text("state-fragment", encoding="utf-8")
    manifest = StateManifest(
        project_id="baps",
        sources=[
            StateSourceDeclaration(
                id="architecture",
                kind="markdown_doc",
                ref=str(state_file),
                authority="descriptive",
            )
        ],
    )
    service = GameService(
        model_client=model,
        blackboard=Blackboard(tmp_path / "events.jsonl"),
        state_manifest=manifest,
        state_adapter=MarkdownFileStateSourceAdapter(),
    )
    request = GameRequest(
        game_type="documentation-refinement",
        subject="README quickstart",
        goal="Improve clarity and remove redundancy",
        target_kind="documentation",
        target_ref="README.md",
        state_source_ids=["architecture"],
    )

    service.play(request)
    assert any("STATE SOURCE: architecture" in prompt for prompt in model.prompts)
    assert any("state-fragment" in prompt for prompt in model.prompts)


def test_game_service_appends_request_state_context_after_constructor_context(tmp_path: Path) -> None:
    model = FakeModelClient(
        responses=[
            "candidate answer",
            "MATERIAL: yes\nCLAIM: concrete issue",
            "rationale",
        ]
    )
    state_file = tmp_path / "state.md"
    state_file.write_text("state-fragment", encoding="utf-8")
    manifest = StateManifest(
        project_id="baps",
        sources=[
            StateSourceDeclaration(
                id="architecture",
                kind="markdown_doc",
                ref=str(state_file),
                authority="descriptive",
            )
        ],
    )
    service = GameService(
        model_client=model,
        blackboard=Blackboard(tmp_path / "events.jsonl"),
        shared_context="base-context",
        state_manifest=manifest,
        state_adapter=MarkdownFileStateSourceAdapter(),
    )
    request = GameRequest(
        game_type="documentation-refinement",
        subject="README quickstart",
        goal="Improve clarity and remove redundancy",
        target_kind="documentation",
        target_ref="README.md",
        state_source_ids=["architecture"],
    )

    service.play(request)
    prompt = model.prompts[0]
    assert "base-context" in prompt
    assert "STATE SOURCE: architecture" in prompt
    assert prompt.index("base-context") < prompt.index("STATE SOURCE: architecture")


def test_game_service_raises_when_request_state_sources_missing_manifest_or_adapter(tmp_path: Path) -> None:
    request = GameRequest(
        game_type="documentation-refinement",
        subject="README quickstart",
        goal="Improve clarity and remove redundancy",
        target_kind="documentation",
        target_ref="README.md",
        state_source_ids=["architecture"],
    )
    model = FakeModelClient(
        responses=[
            "candidate answer",
            "MATERIAL: yes\nCLAIM: concrete issue",
            "rationale",
        ]
    )

    service_no_manifest = GameService(
        model_client=model,
        blackboard=Blackboard(tmp_path / "events-1.jsonl"),
        state_adapter=MarkdownFileStateSourceAdapter(),
    )
    with pytest.raises(
        ValueError, match="request.state_source_ids requires both state_manifest and state_adapter"
    ):
        service_no_manifest.play(request)

    service_no_adapter = GameService(
        model_client=model,
        blackboard=Blackboard(tmp_path / "events-2.jsonl"),
        state_manifest=StateManifest(
            project_id="baps",
            sources=[
                StateSourceDeclaration(
                    id="architecture",
                    kind="markdown_doc",
                    ref=str(tmp_path / "state.md"),
                    authority="descriptive",
                )
            ],
        ),
    )
    with pytest.raises(
        ValueError, match="request.state_source_ids requires both state_manifest and state_adapter"
    ):
        service_no_adapter.play(request)


def test_game_service_appends_integration_decision_event_for_accepted_local_response(
    tmp_path: Path,
) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    model = FakeModelClient(
        responses=[
            "candidate answer",
            "CLAIM: minor note only",
            "rationale",
        ]
    )
    service = GameService(
        model_client=model,
        blackboard=board,
        red_material=False,
    )

    response = service.play(_request())
    integration_events = board.query("integration_decision_recorded")
    assert len(integration_events) == 1
    decision = integration_events[0].payload["integration_decision"]
    assert response.final_decision.decision == "accept"
    assert decision["outcome"] == "accepted"


def test_game_service_appends_deferred_integration_decision_for_rejected_local_response(
    tmp_path: Path,
) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    model = FakeModelClient(
        responses=[
            "candidate answer",
            '{"claim":"blocking issue","material":true,"block_integration":true,"severity":"high","confidence":"high"}',
            "rationale",
        ]
    )
    service = GameService(
        model_client=model,
        blackboard=board,
    )

    response = service.play(_request())
    integration_events = board.query("integration_decision_recorded")
    assert len(integration_events) == 1
    decision = integration_events[0].payload["integration_decision"]
    assert response.final_decision.decision == "reject"
    assert decision["outcome"] == "deferred"


def test_game_service_appends_deferred_integration_decision_for_budget_exhausted_revise(
    tmp_path: Path,
) -> None:
    board = Blackboard(tmp_path / "events.jsonl")
    model = FakeModelClient(
        responses=[
            "candidate answer",
            "MATERIAL: yes\nCLAIM: still needs revision",
            "rationale",
        ]
    )
    service = GameService(
        model_client=model,
        blackboard=board,
        max_rounds=1,
    )

    response = service.play(_request())
    integration_events = board.query("integration_decision_recorded")
    assert len(integration_events) == 1
    decision = integration_events[0].payload["integration_decision"]
    assert response.final_decision.decision == "revise"
    assert decision["outcome"] == "deferred"


def test_game_service_default_behavior_does_not_inject_builtin_profiles(tmp_path: Path) -> None:
    model = FakeModelClient(
        responses=[
            "candidate answer",
            "MATERIAL: no\nCLAIM: looks good",
            "rationale",
        ]
    )
    service = GameService(
        model_client=model,
        blackboard=Blackboard(tmp_path / "events.jsonl"),
        red_material=False,
    )

    service.play(_request())
    assert len(model.prompts) == 3
    assert all("Built-in Blue" not in prompt for prompt in model.prompts)
    assert all("Built-in Red" not in prompt for prompt in model.prompts)
    assert all("Built-in Referee" not in prompt for prompt in model.prompts)


def test_game_service_can_inject_default_agent_profiles_when_enabled(tmp_path: Path) -> None:
    model = FakeModelClient(
        responses=[
            "candidate answer",
            "MATERIAL: no\nCLAIM: looks good",
            "rationale",
        ]
    )
    board = Blackboard(tmp_path / "events.jsonl")
    service = GameService(
        model_client=model,
        blackboard=board,
        red_material=False,
        use_default_agent_profiles=True,
    )

    response = service.play(_request())
    assert response.final_decision.decision == "accept"
    assert len(model.prompts) == 3
    assert "Built-in Blue" in model.prompts[0]
    assert "Built-in Red" in model.prompts[1]
    assert "Built-in Referee" in model.prompts[2]
    integration_events = board.query("integration_decision_recorded")
    assert len(integration_events) == 1
