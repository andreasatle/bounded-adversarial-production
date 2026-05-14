from __future__ import annotations

from baps.game_types import (
    GameTypePromptSections,
    make_documentation_refinement_game_definition,
)
from baps.models import ModelClient
from baps.prompt_assembly import PromptSection, PromptSpec, assemble_prompt
from baps.prompts import PromptRenderer
from baps.role_output_parsing import get_dict, get_non_empty_string, parse_json_object
from baps.schemas import Decision, Finding, GameContract, Move


def _parse_red_output(generated_text: str, default_material: bool) -> tuple[bool, str]:
    material = default_material
    claim: str | None = None

    for raw_line in generated_text.splitlines():
        line = raw_line.strip()
        upper = line.upper()
        if upper.startswith("MATERIAL:"):
            value = line.split(":", 1)[1].strip().lower()
            if value == "yes":
                material = True
            elif value == "no":
                material = False
        elif upper.startswith("CLAIM:"):
            claim = line.split(":", 1)[1].strip()

    if claim is None or not claim:
        claim = generated_text
    return material, claim


def _parse_red_output_json(generated_text: str) -> dict | None:
    return parse_json_object(generated_text)


def _parse_referee_output(generated_text: str) -> str:
    parsed = parse_json_object(generated_text)
    if parsed is None:
        return generated_text
    rationale = get_non_empty_string(parsed, "rationale")
    return rationale if rationale is not None else generated_text


def _parse_blue_output(generated_text: str) -> tuple[str, dict]:
    parsed = parse_json_object(generated_text)
    if parsed is None:
        return generated_text, {}

    summary = get_non_empty_string(parsed, "summary")
    if summary is None:
        return generated_text, {}

    payload = get_dict(parsed, "payload") or {}
    return summary, payload


def blue_role(contract: GameContract) -> Move:
    return Move(
        game_id=contract.id,
        role="blue",
        summary="Propose a minimal safe implementation update.",
        payload={"goal": contract.goal},
    )


def red_role(contract: GameContract, blue_move: Move) -> Finding:
    return Finding(
        game_id=contract.id,
        severity="low",
        confidence="high",
        claim=f"Potential risk identified in blue move: {blue_move.summary}",
        evidence=["Manual review suggests low-impact edge-case exposure."],
        block_integration=False,
    )


def referee_role(contract: GameContract, blue_move: Move, red_finding: Finding) -> Decision:
    return Decision(
        game_id=contract.id,
        decision="accept",
        rationale=f"Accepted move '{blue_move.summary}' after reviewing finding '{red_finding.claim}'.",
    )


def _resolve_prompt_sections(
    game_type_prompt_sections: GameTypePromptSections | None,
) -> GameTypePromptSections:
    if game_type_prompt_sections is not None:
        return game_type_prompt_sections
    return make_documentation_refinement_game_definition().prompt_sections


def _default_blue_template(game_type_prompt_sections: GameTypePromptSections | None) -> str:
    sections = _resolve_prompt_sections(game_type_prompt_sections)
    return assemble_prompt(
        PromptSpec(
            sections=(
                [
                    PromptSection(
                        name="Role",
                        content=(
                            "Blue role for game {game_id}: {goal}. "
                            "If revision context is present, use it to improve the proposed change."
                        ),
                    ),
                    PromptSection(
                        name="Revision Context",
                        content=(
                            "Previous blue summary: {previous_blue_summary}. "
                            "Previous red claim: {previous_red_claim}. "
                            "Previous referee rationale: {previous_referee_rationale}."
                        ),
                    ),
                ]
                + sections.blue_sections
            )
        )
    )


def _default_red_template(game_type_prompt_sections: GameTypePromptSections | None) -> str:
    sections = _resolve_prompt_sections(game_type_prompt_sections)
    return assemble_prompt(
        PromptSpec(
            sections=(
                [
                    PromptSection(
                        name="Scope",
                        content=(
                            "Red role for game {game_id}: critique only this Blue move/change from the current game: "
                            "`{blue_summary}`. "
                            "Do not perform a general audit of the whole system. "
                            "Use surrounding context only as supporting evidence for the critique."
                        ),
                    ),
                    PromptSection(
                        name="Materiality",
                        content=(
                            "Classify materiality: material finding = actionable issue that should cause revision; "
                            "non-material finding = minor note, praise, or no required change."
                        ),
                    ),
                    PromptSection(
                        name="Output Format",
                        content="MATERIAL: yes|no\nCLAIM: concise critique/assessment",
                    ),
                ]
                + sections.red_sections
            )
        )
    )


def _default_referee_template(game_type_prompt_sections: GameTypePromptSections | None) -> str:
    sections = _resolve_prompt_sections(game_type_prompt_sections)
    return assemble_prompt(
        PromptSpec(
            sections=(
                [
                    PromptSection(
                        name="Decision",
                        content=(
                            "Referee for game {game_id}. Structured decision is already fixed to `{decision}`. "
                            "Decision policy: reject = blocking issue, revise = useful non-blocking criticism, "
                            "accept = no material issue."
                        ),
                    ),
                    PromptSection(
                        name="Rationale Rule",
                        content="{decision_rationale_goal}",
                    ),
                    PromptSection(
                        name="Inputs",
                        content=(
                            "Blue move: `{blue_summary}`. "
                            "Red finding: `{red_claim}` (severity={red_severity}, confidence={red_confidence}, "
                            "block_integration={red_block_integration})."
                        ),
                    ),
                ]
                + sections.referee_sections
            )
        )
    )


def make_prompt_blue_role(
    model_client: ModelClient,
    template: str | None = None,
    extra_context: dict | None = None,
    game_type_prompt_sections: GameTypePromptSections | None = None,
):
    resolved_template = template if template is not None else _default_blue_template(game_type_prompt_sections)
    renderer = PromptRenderer(resolved_template)
    context_overrides = dict(extra_context) if extra_context is not None else {}

    def _role(contract: GameContract, revision_context: dict | None = None) -> Move:
        revision = revision_context if revision_context is not None else {}
        context = {
            "game_id": contract.id,
            "subject": contract.subject,
            "goal": contract.goal,
            "target_kind": contract.target.kind,
            "target_ref": contract.target.ref,
            "previous_blue_summary": revision.get("previous_blue_summary", ""),
            "previous_red_claim": revision.get("previous_red_claim", ""),
            "previous_referee_rationale": revision.get("previous_referee_rationale", ""),
        }
        context.update(context_overrides)
        prompt = renderer.render(context)
        generated = model_client.generate(prompt)
        summary, parsed_payload = _parse_blue_output(generated)
        payload = {"goal": contract.goal}
        payload.update(parsed_payload)
        return Move(
            game_id=contract.id,
            role="blue",
            summary=summary,
            payload=payload,
        )

    return _role


def make_prompt_red_role(
    model_client: ModelClient,
    template: str | None = None,
    extra_context: dict | None = None,
    default_block_integration: bool = False,
    default_material: bool = True,
    game_type_prompt_sections: GameTypePromptSections | None = None,
):
    resolved_template = template if template is not None else _default_red_template(game_type_prompt_sections)
    renderer = PromptRenderer(resolved_template)
    context_overrides = dict(extra_context) if extra_context is not None else {}

    def _role(contract: GameContract, blue_move: Move) -> Finding:
        context = {
            "game_id": contract.id,
            "subject": contract.subject,
            "goal": contract.goal,
            "target_kind": contract.target.kind,
            "target_ref": contract.target.ref,
            "blue_summary": blue_move.summary,
            "blue_payload": blue_move.payload,
        }
        context.update(context_overrides)
        prompt = renderer.render(context)
        generated = model_client.generate(prompt)
        parsed_json = _parse_red_output_json(generated)
        if parsed_json is not None:
            parsed_material = bool(parsed_json.get("material", default_material))
            claim = str(parsed_json.get("claim", generated)).strip() or generated
            severity = str(parsed_json.get("severity", "medium")).strip() or "medium"
            confidence = str(parsed_json.get("confidence", "medium")).strip() or "medium"
            block_integration = bool(
                parsed_json.get("block_integration", default_block_integration)
            )
        else:
            parsed_material, claim = _parse_red_output(generated, default_material=default_material)
            severity = "medium"
            confidence = "medium"
            block_integration = default_block_integration
        return Finding(
            game_id=contract.id,
            severity=severity,
            confidence=confidence,
            claim=claim,
            evidence=[f"Blue summary: {blue_move.summary}"],
            block_integration=block_integration,
            payload={"material": parsed_material},
        )

    return _role


def make_prompt_referee_role(
    model_client: ModelClient,
    template: str | None = None,
    extra_context: dict | None = None,
    game_type_prompt_sections: GameTypePromptSections | None = None,
):
    resolved_template = template if template is not None else _default_referee_template(
        game_type_prompt_sections
    )
    renderer = PromptRenderer(resolved_template)
    context_overrides = dict(extra_context) if extra_context is not None else {}

    def _role(contract: GameContract, blue_move: Move, red_finding: Finding) -> Decision:
        is_material = bool(red_finding.payload.get("material", True))
        if red_finding.block_integration:
            decision = "reject"
        elif is_material:
            decision = "revise"
        else:
            decision = "accept"
        context = {
            "game_id": contract.id,
            "subject": contract.subject,
            "goal": contract.goal,
            "target_kind": contract.target.kind,
            "target_ref": contract.target.ref,
            "blue_summary": blue_move.summary,
            "red_claim": red_finding.claim,
            "red_severity": red_finding.severity,
            "red_confidence": red_finding.confidence,
            "red_block_integration": red_finding.block_integration,
            "red_material": is_material,
            "decision": decision,
            "decision_rationale_goal": (
                "Provide one concise rationale that supports this fixed decision. "
                "Do not choose a different decision and do not contradict it."
            ),
        }
        context.update(context_overrides)
        prompt = renderer.render(context)
        generated = model_client.generate(prompt)
        rationale = _parse_referee_output(generated)
        return Decision(
            game_id=contract.id,
            decision=decision,
            rationale=rationale,
        )

    return _role
