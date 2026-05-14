import pytest

from baps.example_roles import (
    blue_role,
    make_prompt_blue_role,
    make_prompt_red_role,
    make_prompt_referee_role,
    red_role,
    referee_role,
)
from baps.models import FakeModelClient
from baps.schemas import Finding, GameContract, Move, Target


def _contract() -> GameContract:
    return GameContract(
        id="game-1",
        subject="auth",
        goal="find flaws",
        target=Target(kind="repo"),
        active_roles=["blue", "red", "referee"],
    )


def test_blue_role_returns_valid_move() -> None:
    contract = _contract()
    move = blue_role(contract)

    assert isinstance(move, Move)
    assert move.game_id == contract.id
    assert move.role == "blue"
    assert move.payload["goal"] == contract.goal


def test_red_role_returns_valid_finding_and_references_blue_summary() -> None:
    contract = _contract()
    move = blue_role(contract)
    finding = red_role(contract, move)

    assert isinstance(finding, Finding)
    assert finding.game_id == contract.id
    assert move.summary in finding.claim
    assert len(finding.evidence) >= 1
    assert finding.block_integration is False


def test_referee_role_references_blue_summary_and_red_claim() -> None:
    contract = _contract()
    move = blue_role(contract)
    finding = red_role(contract, move)
    decision = referee_role(contract, move, finding)

    assert decision.game_id == contract.id
    assert move.summary in decision.rationale
    assert finding.claim in decision.rationale


def test_example_roles_are_deterministic_for_same_input() -> None:
    contract = _contract()
    move1 = blue_role(contract)
    move2 = blue_role(contract)
    assert move1.model_dump(mode="json") == move2.model_dump(mode="json")

    finding1 = red_role(contract, move1)
    finding2 = red_role(contract, move1)
    assert finding1.model_dump(mode="json") == finding2.model_dump(mode="json")

    decision1 = referee_role(contract, move1, finding1)
    decision2 = referee_role(contract, move1, finding1)
    assert decision1.model_dump(mode="json") == decision2.model_dump(mode="json")


def test_prompt_driven_blue_role_renders_and_calls_model_client() -> None:
    contract = _contract()
    model = FakeModelClient(responses=["generated summary"])
    role = make_prompt_blue_role(model, template="Game {game_id} goal {goal}")

    move = role(contract)

    assert move.summary == "generated summary"
    assert model.prompts == [f"Game {contract.id} goal {contract.goal}"]


def test_prompt_driven_blue_role_is_deterministic_with_fake_model() -> None:
    contract = _contract()
    model = FakeModelClient(responses=["same summary", "same summary"])
    role = make_prompt_blue_role(model, template="Static prompt for {game_id}")

    move1 = role(contract)
    move2 = role(contract)

    assert move1.model_dump(mode="json") == move2.model_dump(mode="json")


def test_prompt_driven_blue_role_missing_template_variable_fails_clearly() -> None:
    contract = _contract()
    model = FakeModelClient(responses=["unused"])
    role = make_prompt_blue_role(model, template="Missing {unknown_key}")

    with pytest.raises(KeyError):
        role(contract)


def test_prompt_driven_blue_role_rejects_whitespace_rendered_prompt() -> None:
    contract = _contract()
    model = FakeModelClient(responses=["unused"])
    role = make_prompt_blue_role(model, template="{blank}", extra_context={"blank": "   "})

    with pytest.raises(ValueError):
        role(contract)


def test_prompt_driven_blue_role_accepts_revision_context() -> None:
    contract = _contract()
    model = FakeModelClient(responses=["revised summary"])
    role = make_prompt_blue_role(model)

    move = role(
        contract,
        revision_context={
            "previous_blue_summary": "old blue",
            "previous_red_claim": "old red",
            "previous_referee_rationale": "old referee rationale",
        },
    )

    assert move.summary == "revised summary"
    prompt = model.prompts[0]
    assert "Previous blue summary: old blue." in prompt
    assert "Previous red claim: old red." in prompt
    assert "Previous referee rationale: old referee rationale." in prompt


def test_prompt_driven_blue_role_no_revision_path_still_works() -> None:
    contract = _contract()
    model = FakeModelClient(responses=["first round summary"])
    role = make_prompt_blue_role(model)

    move = role(contract)
    assert move.summary == "first round summary"


def test_prompt_driven_red_role_renders_and_calls_model_client() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={"k": "v"})
    model = FakeModelClient(responses=["generated red claim"])
    role = make_prompt_red_role(model, template="Red sees {blue_summary} for {goal}")

    finding = role(contract, blue)

    assert finding.claim == "generated red claim"
    assert model.prompts == [f"Red sees {blue.summary} for {contract.goal}"]


def test_prompt_driven_red_generated_text_becomes_claim() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    model = FakeModelClient(responses=["specific critique text"])
    role = make_prompt_red_role(model)

    finding = role(contract, blue)

    assert finding.claim == "specific critique text"
    assert finding.severity == "medium"
    assert finding.confidence == "medium"
    assert finding.block_integration is False
    assert finding.payload["material"] is True
    assert blue.summary in finding.evidence[0]
    assert blue.summary in model.prompts[0]
    assert "critique only this Blue move/change from the current game" in model.prompts[0]
    assert "Do not perform a general audit of the whole system." in model.prompts[0]


def test_prompt_driven_red_missing_template_variable_raises_key_error() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    model = FakeModelClient(responses=["unused"])
    role = make_prompt_red_role(model, template="Missing {unknown_key}")

    with pytest.raises(KeyError):
        role(contract, blue)


def test_prompt_driven_red_whitespace_rendered_prompt_raises_value_error() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    model = FakeModelClient(responses=["unused"])
    role = make_prompt_red_role(model, template="{blank}", extra_context={"blank": "   "})

    with pytest.raises(ValueError):
        role(contract, blue)


def test_prompt_driven_referee_renders_and_calls_model_client() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    red = Finding(
        game_id=contract.id,
        severity="high",
        confidence="high",
        claim="critical issue",
        evidence=["e1"],
        block_integration=True,
    )
    model = FakeModelClient(responses=["generated rationale"])
    role = make_prompt_referee_role(model, template="Ref checks {red_claim} for {blue_summary}")

    decision = role(contract, blue, red)

    assert decision.rationale == "generated rationale"
    assert model.prompts == [f"Ref checks {red.claim} for {blue.summary}"]


def test_prompt_driven_referee_generated_text_becomes_rationale() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    red = Finding(
        game_id=contract.id,
        severity="low",
        confidence="low",
        claim="minor issue",
        evidence=["e1"],
        block_integration=False,
    )
    model = FakeModelClient(responses=["rationale text"])
    role = make_prompt_referee_role(model)

    decision = role(contract, blue, red)
    assert decision.rationale == "rationale text"


def test_prompt_driven_referee_rejects_when_block_integration_true() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    red = Finding(
        game_id=contract.id,
        severity="high",
        confidence="high",
        claim="major issue",
        evidence=["e1"],
        block_integration=True,
    )
    model = FakeModelClient(responses=["rationale"])
    role = make_prompt_referee_role(model)

    decision = role(contract, blue, red)
    assert decision.decision == "reject"
    assert "decision is already fixed to `reject`" in model.prompts[0]
    assert "reject = blocking issue, revise = useful non-blocking criticism, accept = no material issue" in model.prompts[0]
    assert "Do not choose a different decision and do not contradict it." in model.prompts[0]


def test_prompt_driven_referee_revises_when_block_integration_false() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    red = Finding(
        game_id=contract.id,
        severity="low",
        confidence="high",
        claim="minor issue",
        evidence=["e1"],
        block_integration=False,
    )
    model = FakeModelClient(responses=["rationale"])
    role = make_prompt_referee_role(model)

    decision = role(contract, blue, red)
    assert decision.decision == "revise"
    assert "decision is already fixed to `revise`" in model.prompts[0]
    assert "reject = blocking issue, revise = useful non-blocking criticism, accept = no material issue" in model.prompts[0]
    assert "Do not choose a different decision and do not contradict it." in model.prompts[0]


def test_prompt_driven_referee_accepts_for_non_material_non_blocking_finding() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    red = Finding(
        game_id=contract.id,
        severity="low",
        confidence="high",
        claim="minor note",
        evidence=["e1"],
        block_integration=False,
        payload={"material": False},
    )
    model = FakeModelClient(responses=["rationale"])
    role = make_prompt_referee_role(model)

    decision = role(contract, blue, red)
    assert decision.decision == "accept"


def test_prompt_driven_red_material_defaults_can_be_configured() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    model = FakeModelClient(responses=["generated red claim"])
    role = make_prompt_red_role(model, default_material=False)

    finding = role(contract, blue)
    assert finding.payload["material"] is False


def test_prompt_driven_red_parses_material_yes() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    model = FakeModelClient(responses=["MATERIAL: yes\nCLAIM: actionable issue"])
    role = make_prompt_red_role(model, default_material=False)

    finding = role(contract, blue)
    assert finding.payload["material"] is True
    assert finding.claim == "actionable issue"


def test_prompt_driven_red_parses_material_no() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    model = FakeModelClient(responses=["MATERIAL: no\nCLAIM: no changes needed"])
    role = make_prompt_red_role(model, default_material=True)

    finding = role(contract, blue)
    assert finding.payload["material"] is False
    assert finding.claim == "no changes needed"


def test_prompt_driven_red_material_fallback_to_default_when_missing() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    model = FakeModelClient(responses=["CLAIM: assessment without explicit material flag"])
    role = make_prompt_red_role(model, default_material=False)

    finding = role(contract, blue)
    assert finding.payload["material"] is False
    assert finding.claim == "assessment without explicit material flag"


def test_prompt_driven_red_claim_falls_back_to_full_output_when_missing() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    generated = "MATERIAL: no\nNo claim label, just plain assessment text."
    model = FakeModelClient(responses=[generated])
    role = make_prompt_red_role(model)

    finding = role(contract, blue)
    assert finding.claim == generated


def test_prompt_driven_red_parses_valid_json_output() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    model = FakeModelClient(
        responses=[
            '{"claim":"json claim","material":false,"block_integration":true,"severity":"high","confidence":"low"}'
        ]
    )
    role = make_prompt_red_role(model, default_material=True)

    finding = role(contract, blue)
    assert finding.claim == "json claim"
    assert finding.payload["material"] is False
    assert finding.block_integration is True
    assert finding.severity == "high"
    assert finding.confidence == "low"


def test_prompt_driven_red_malformed_json_falls_back_safely() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    generated = '{"claim": "broken", "material": true'
    model = FakeModelClient(responses=[generated])
    role = make_prompt_red_role(model, default_material=False)

    finding = role(contract, blue)
    assert finding.claim == generated
    assert finding.payload["material"] is False
    assert finding.block_integration is False
    assert finding.severity == "medium"
    assert finding.confidence == "medium"


def test_prompt_driven_red_non_object_json_falls_back_safely() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    model = FakeModelClient(responses=['["not", "an", "object"]'])
    role = make_prompt_red_role(model, default_material=True)

    finding = role(contract, blue)
    assert finding.claim == '["not", "an", "object"]'
    assert finding.payload["material"] is True
    assert finding.severity == "medium"
    assert finding.confidence == "medium"


def test_prompt_driven_referee_accepts_with_non_material_generated_red_finding() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    red_model = FakeModelClient(responses=["MATERIAL: no\nCLAIM: looks good overall"])
    red_role_generated = make_prompt_red_role(red_model, default_material=True)
    red_finding = red_role_generated(contract, blue)

    referee_model = FakeModelClient(responses=["rationale"])
    ref_role = make_prompt_referee_role(referee_model)
    decision = ref_role(contract, blue, red_finding)
    assert decision.decision == "accept"


def test_default_assembled_role_prompts_include_expected_guidance() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    model_blue = FakeModelClient(responses=["blue summary"])
    model_red = FakeModelClient(responses=["MATERIAL: yes\nCLAIM: red claim"])
    model_ref = FakeModelClient(responses=["rationale"])

    blue_role_prompted = make_prompt_blue_role(model_blue)
    red_role_prompted = make_prompt_red_role(model_red)
    ref_role_prompted = make_prompt_referee_role(model_ref)

    blue_move = blue_role_prompted(contract)
    red_finding = red_role_prompted(contract, blue)
    ref_role_prompted(contract, blue_move, red_finding)

    assert "critique only this Blue move/change from the current game" in model_red.prompts[0]
    assert "Classify materiality" in model_red.prompts[0]
    assert "## Output Format" in model_red.prompts[0]
    assert "Structured decision is already fixed to" in model_ref.prompts[0]
    assert "Decision policy:" in model_ref.prompts[0]


def test_default_prompts_include_game_type_sections_in_order() -> None:
    contract = _contract()
    model_blue = FakeModelClient(responses=["blue summary"])
    model_red = FakeModelClient(responses=["MATERIAL: yes\nCLAIM: red claim"])
    model_ref = FakeModelClient(responses=["rationale"])

    blue_role_prompted = make_prompt_blue_role(model_blue)
    red_role_prompted = make_prompt_red_role(model_red)
    ref_role_prompted = make_prompt_referee_role(model_ref)

    blue_move = blue_role_prompted(contract)
    red_finding = red_role_prompted(contract, Move(game_id=contract.id, role="blue", summary="draft", payload={}))
    ref_role_prompted(contract, blue_move, red_finding)

    blue_prompt = model_blue.prompts[0]
    red_prompt = model_red.prompts[0]
    ref_prompt = model_ref.prompts[0]

    assert "## Role" in blue_prompt
    assert "## Game Type" in blue_prompt
    assert blue_prompt.index("## Role") < blue_prompt.index("## Game Type")

    assert "## Scope" in red_prompt
    assert "## Game Type Scope" in red_prompt
    assert red_prompt.index("## Scope") < red_prompt.index("## Game Type Scope")

    assert "## Decision" in ref_prompt
    assert "## Game Type Convergence" in ref_prompt
    assert ref_prompt.index("## Decision") < ref_prompt.index("## Game Type Convergence")


def test_prompt_driven_referee_missing_template_variable_raises_key_error() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    red = Finding(
        game_id=contract.id,
        severity="low",
        confidence="low",
        claim="minor issue",
        evidence=["e1"],
        block_integration=False,
    )
    model = FakeModelClient(responses=["unused"])
    role = make_prompt_referee_role(model, template="Missing {unknown_key}")

    with pytest.raises(KeyError):
        role(contract, blue, red)


def test_prompt_driven_referee_whitespace_rendered_prompt_raises_value_error() -> None:
    contract = _contract()
    blue = Move(game_id=contract.id, role="blue", summary="draft", payload={})
    red = Finding(
        game_id=contract.id,
        severity="low",
        confidence="low",
        claim="minor issue",
        evidence=["e1"],
        block_integration=False,
    )
    model = FakeModelClient(responses=["unused"])
    role = make_prompt_referee_role(model, template="{blank}", extra_context={"blank": "   "})

    with pytest.raises(ValueError):
        role(contract, blue, red)
