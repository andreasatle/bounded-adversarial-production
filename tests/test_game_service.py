from pathlib import Path

import pytest

from baps.blackboard import Blackboard
from baps.game_service import GameService
from baps.game_types import GameDefinition, GameTypePromptSections, make_documentation_refinement_game_definition
from baps.models import FakeModelClient
from baps.prompt_assembly import PromptSection
from baps.schemas import GameRequest, GameResponse


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
