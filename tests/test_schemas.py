import pytest
from pydantic import ValidationError

from baps.schemas import Artifact, Decision, Finding, GameContract, Move, Target


def test_target_constructs_successfully() -> None:
    target = Target(kind="repo", ref="main")
    assert target.kind == "repo"
    assert target.ref == "main"


def test_game_contract_constructs_successfully() -> None:
    game = GameContract(
        id="gc-1",
        subject="authentication",
        goal="find authorization flaws",
        target=Target(kind="repo", ref="main"),
        active_roles=["red-team", "blue-team"],
    )
    assert game.max_rounds == 3
    assert game.scope_allowed == []
    assert game.scope_forbidden == []


def test_move_constructs_successfully() -> None:
    move = Move(game_id="gc-1", role="red-team", summary="attack path", payload={"k": "v"})
    assert move.payload == {"k": "v"}


def test_finding_constructs_successfully() -> None:
    finding = Finding(
        game_id="gc-1",
        severity="high",
        confidence="medium",
        claim="token leak possible",
        evidence=["log line"],
    )
    assert finding.block_integration is False


def test_decision_constructs_successfully() -> None:
    decision = Decision(game_id="gc-1", decision="integrate", rationale="risk accepted")
    assert decision.decision == "integrate"


def test_artifact_constructs_successfully() -> None:
    artifact = Artifact(id="art-1", type="report", current_version="v1", metadata={"k": "v"})
    assert artifact.metadata == {"k": "v"}


@pytest.mark.parametrize(
    ("model_cls", "field_name", "base_payload"),
    [
        (Target, "kind", {"kind": "repo", "ref": "main"}),
        (
            GameContract,
            "id",
            {
                "id": "gc-1",
                "subject": "authentication",
                "goal": "find flaws",
                "target": {"kind": "repo", "ref": "main"},
                "active_roles": ["red-team"],
            },
        ),
        (
            GameContract,
            "subject",
            {
                "id": "gc-1",
                "subject": "authentication",
                "goal": "find flaws",
                "target": {"kind": "repo", "ref": "main"},
                "active_roles": ["red-team"],
            },
        ),
        (
            GameContract,
            "goal",
            {
                "id": "gc-1",
                "subject": "authentication",
                "goal": "find flaws",
                "target": {"kind": "repo", "ref": "main"},
                "active_roles": ["red-team"],
            },
        ),
        (Move, "game_id", {"game_id": "gc-1", "role": "red-team", "summary": "s"}),
        (Move, "role", {"game_id": "gc-1", "role": "red-team", "summary": "s"}),
        (Move, "summary", {"game_id": "gc-1", "role": "red-team", "summary": "s"}),
        (
            Finding,
            "game_id",
            {"game_id": "gc-1", "severity": "high", "confidence": "high", "claim": "c"},
        ),
        (
            Finding,
            "severity",
            {"game_id": "gc-1", "severity": "high", "confidence": "high", "claim": "c"},
        ),
        (
            Finding,
            "confidence",
            {"game_id": "gc-1", "severity": "high", "confidence": "high", "claim": "c"},
        ),
        (
            Finding,
            "claim",
            {"game_id": "gc-1", "severity": "high", "confidence": "high", "claim": "c"},
        ),
        (Decision, "game_id", {"game_id": "gc-1", "decision": "integrate", "rationale": "r"}),
        (Decision, "decision", {"game_id": "gc-1", "decision": "integrate", "rationale": "r"}),
        (Decision, "rationale", {"game_id": "gc-1", "decision": "integrate", "rationale": "r"}),
        (Artifact, "id", {"id": "art-1", "type": "report"}),
        (Artifact, "type", {"id": "art-1", "type": "report"}),
    ],
)
def test_empty_required_strings_fail(model_cls, field_name, base_payload) -> None:
    payload = dict(base_payload)
    payload[field_name] = "   "
    with pytest.raises(ValidationError):
        model_cls(**payload)


def test_game_contract_empty_active_roles_fails() -> None:
    with pytest.raises(ValidationError):
        GameContract(
            id="gc-1",
            subject="authentication",
            goal="find flaws",
            target=Target(kind="repo"),
            active_roles=[],
        )


def test_game_contract_max_rounds_must_be_at_least_one() -> None:
    with pytest.raises(ValidationError):
        GameContract(
            id="gc-1",
            subject="authentication",
            goal="find flaws",
            target=Target(kind="repo"),
            active_roles=["red-team"],
            max_rounds=0,
        )


def test_mutable_defaults_are_not_shared() -> None:
    game_a = GameContract(
        id="gc-1",
        subject="authentication",
        goal="find flaws",
        target=Target(kind="repo"),
        active_roles=["red-team"],
    )
    game_b = GameContract(
        id="gc-2",
        subject="payments",
        goal="find flaws",
        target=Target(kind="repo"),
        active_roles=["red-team"],
    )
    game_a.scope_allowed.append("src/")
    assert game_b.scope_allowed == []

    move_a = Move(game_id="gc-1", role="red-team", summary="s")
    move_b = Move(game_id="gc-2", role="blue-team", summary="s")
    move_a.payload["x"] = 1
    assert move_b.payload == {}

    finding_a = Finding(game_id="gc-1", severity="high", confidence="high", claim="c")
    finding_b = Finding(game_id="gc-2", severity="low", confidence="low", claim="c")
    finding_a.evidence.append("line 1")
    assert finding_b.evidence == []

    artifact_a = Artifact(id="a1", type="report")
    artifact_b = Artifact(id="a2", type="report")
    artifact_a.metadata["k"] = "v"
    assert artifact_b.metadata == {}
