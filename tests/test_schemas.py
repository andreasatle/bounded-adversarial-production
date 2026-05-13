import pytest
from pydantic import ValidationError

from baps.schemas import (
    Artifact,
    ArtifactAdapterResult,
    ArtifactChange,
    ArtifactVersion,
    Decision,
    Finding,
    GameContract,
    GameRecord,
    GameResponse,
    GameRound,
    RoundSummary,
    GameRequest,
    GameState,
    Move,
    Target,
)


def test_game_request_state_source_ids_default_and_isolated() -> None:
    a = GameRequest(
        game_type="documentation-refinement",
        subject="s",
        goal="g",
        target_kind="documentation",
    )
    b = GameRequest(
        game_type="documentation-refinement",
        subject="s",
        goal="g",
        target_kind="documentation",
    )
    assert a.state_source_ids == []
    a.state_source_ids.append("architecture")
    assert b.state_source_ids == []


def test_game_request_rejects_blank_state_source_ids() -> None:
    with pytest.raises(ValidationError):
        GameRequest(
            game_type="documentation-refinement",
            subject="s",
            goal="g",
            target_kind="documentation",
            state_source_ids=["architecture", " "],
        )


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


def test_artifact_version_constructs_successfully() -> None:
    version = ArtifactVersion(
        artifact_id="art-1",
        version_id="v1",
        path="artifacts/report.md",
        metadata={"author": "a"},
    )
    assert version.path == "artifacts/report.md"


def test_artifact_change_constructs_successfully() -> None:
    change = ArtifactChange(
        artifact_id="art-1",
        change_id="chg-1",
        base_version="v1",
        description="clarify section",
        diff="@@ -1 +1 @@",
        metadata={"source": "review"},
    )
    assert change.change_id == "chg-1"


def test_artifact_adapter_result_constructs_successfully() -> None:
    result = ArtifactAdapterResult(
        artifact_id="art-1",
        version_id="v2",
        change_id="chg-1",
        message="ok",
    )
    assert result.message == "ok"


def test_game_record_constructs_successfully() -> None:
    record = GameRecord(
        game_id="game-1",
        contract=GameContract(
            id="gc-1",
            subject="auth",
            goal="find flaws",
            target=Target(kind="repo"),
            active_roles=["red-team"],
        ),
        status="pending",
        created_at="2026-05-11T10:00:00Z",
        updated_at="2026-05-11T10:00:00Z",
        metadata={"owner": "qa"},
    )
    assert record.status == "pending"


def test_game_round_constructs_successfully() -> None:
    round_ = GameRound(
        round_number=1,
        moves=[Move(game_id="game-1", role="red", summary="s")],
        findings=[Finding(game_id="game-1", severity="high", confidence="high", claim="c")],
        decision=Decision(game_id="game-1", decision="integrate", rationale="r"),
    )
    assert round_.round_number == 1


def test_game_state_constructs_successfully() -> None:
    state = GameState(
        game_id="game-1",
        run_id="run-0001",
        current_round=1,
        rounds=[GameRound(round_number=1)],
        final_decision=Decision(game_id="game-1", decision="integrate", rationale="r"),
    )
    assert state.game_id == "game-1"


def test_game_result_constructs_successfully() -> None:
    result = GameResponse(
        game_id="game-1",
        run_id="run-20260513-100000-deadbeef",
        rounds_played=1,
        max_rounds=2,
        final_decision=Decision(game_id="game-1", decision="accept", rationale="ok"),
        terminal_reason="accepted",
        final_blue_summary="blue summary",
        final_red_claim="red claim",
        trace_event_ids=["e1"],
    )
    assert result.terminal_reason == "accepted"


def test_round_summary_constructs_successfully() -> None:
    summary = RoundSummary(
        round_number=1,
        blue_summary="blue",
        red_claim="red",
        referee_decision="revise",
        referee_rationale="rationale",
    )
    assert summary.round_number == 1


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
        (
            GameRecord,
            "game_id",
            {
                "game_id": "game-1",
                "contract": {
                    "id": "gc-1",
                    "subject": "auth",
                    "goal": "find flaws",
                    "target": {"kind": "repo"},
                    "active_roles": ["red-team"],
                },
                "status": "pending",
                "created_at": "2026-05-11T10:00:00Z",
                "updated_at": "2026-05-11T10:00:00Z",
            },
        ),
        (
            GameRecord,
            "status",
            {
                "game_id": "game-1",
                "contract": {
                    "id": "gc-1",
                    "subject": "auth",
                    "goal": "find flaws",
                    "target": {"kind": "repo"},
                    "active_roles": ["red-team"],
                },
                "status": "pending",
                "created_at": "2026-05-11T10:00:00Z",
                "updated_at": "2026-05-11T10:00:00Z",
            },
        ),
        (
            GameRecord,
            "created_at",
            {
                "game_id": "game-1",
                "contract": {
                    "id": "gc-1",
                    "subject": "auth",
                    "goal": "find flaws",
                    "target": {"kind": "repo"},
                    "active_roles": ["red-team"],
                },
                "status": "pending",
                "created_at": "2026-05-11T10:00:00Z",
                "updated_at": "2026-05-11T10:00:00Z",
            },
        ),
        (
            GameRecord,
            "updated_at",
            {
                "game_id": "game-1",
                "contract": {
                    "id": "gc-1",
                    "subject": "auth",
                    "goal": "find flaws",
                    "target": {"kind": "repo"},
                    "active_roles": ["red-team"],
                },
                "status": "pending",
                "created_at": "2026-05-11T10:00:00Z",
                "updated_at": "2026-05-11T10:00:00Z",
            },
        ),
        (GameState, "game_id", {"game_id": "game-1", "run_id": "run-0001"}),
        (GameState, "run_id", {"game_id": "game-1", "run_id": "run-0001"}),
        (
            GameResponse,
            "game_id",
            {
                "game_id": "game-1",
                "run_id": "run-20260513-100000-deadbeef",
                "rounds_played": 1,
                "max_rounds": 2,
                "final_decision": {"game_id": "game-1", "decision": "accept", "rationale": "ok"},
                "terminal_reason": "accepted",
                "final_blue_summary": "blue summary",
                "final_red_claim": "red claim",
            },
        ),
        (
            GameResponse,
            "run_id",
            {
                "game_id": "game-1",
                "run_id": "run-20260513-100000-deadbeef",
                "rounds_played": 1,
                "max_rounds": 2,
                "final_decision": {"game_id": "game-1", "decision": "accept", "rationale": "ok"},
                "terminal_reason": "accepted",
                "final_blue_summary": "blue summary",
                "final_red_claim": "red claim",
            },
        ),
        (
            GameResponse,
            "terminal_reason",
            {
                "game_id": "game-1",
                "run_id": "run-20260513-100000-deadbeef",
                "rounds_played": 1,
                "max_rounds": 2,
                "final_decision": {"game_id": "game-1", "decision": "accept", "rationale": "ok"},
                "terminal_reason": "accepted",
                "final_blue_summary": "blue summary",
                "final_red_claim": "red claim",
            },
        ),
        (
            GameResponse,
            "final_blue_summary",
            {
                "game_id": "game-1",
                "run_id": "run-20260513-100000-deadbeef",
                "rounds_played": 1,
                "max_rounds": 2,
                "final_decision": {"game_id": "game-1", "decision": "accept", "rationale": "ok"},
                "terminal_reason": "accepted",
                "final_blue_summary": "blue summary",
                "final_red_claim": "red claim",
            },
        ),
        (
            GameResponse,
            "final_red_claim",
            {
                "game_id": "game-1",
                "run_id": "run-20260513-100000-deadbeef",
                "rounds_played": 1,
                "max_rounds": 2,
                "final_decision": {"game_id": "game-1", "decision": "accept", "rationale": "ok"},
                "terminal_reason": "accepted",
                "final_blue_summary": "blue summary",
                "final_red_claim": "red claim",
            },
        ),
        (
            RoundSummary,
            "blue_summary",
            {
                "round_number": 1,
                "blue_summary": "blue",
                "red_claim": "red",
                "referee_decision": "revise",
                "referee_rationale": "rationale",
            },
        ),
        (
            RoundSummary,
            "red_claim",
            {
                "round_number": 1,
                "blue_summary": "blue",
                "red_claim": "red",
                "referee_decision": "revise",
                "referee_rationale": "rationale",
            },
        ),
        (
            RoundSummary,
            "referee_decision",
            {
                "round_number": 1,
                "blue_summary": "blue",
                "red_claim": "red",
                "referee_decision": "revise",
                "referee_rationale": "rationale",
            },
        ),
        (
            RoundSummary,
            "referee_rationale",
            {
                "round_number": 1,
                "blue_summary": "blue",
                "red_claim": "red",
                "referee_decision": "revise",
                "referee_rationale": "rationale",
            },
        ),
        (Artifact, "id", {"id": "art-1", "type": "report"}),
        (Artifact, "type", {"id": "art-1", "type": "report"}),
        (
            ArtifactVersion,
            "artifact_id",
            {"artifact_id": "art-1", "version_id": "v1", "path": "artifacts/report.md"},
        ),
        (
            ArtifactVersion,
            "version_id",
            {"artifact_id": "art-1", "version_id": "v1", "path": "artifacts/report.md"},
        ),
        (
            ArtifactVersion,
            "path",
            {"artifact_id": "art-1", "version_id": "v1", "path": "artifacts/report.md"},
        ),
        (
            ArtifactChange,
            "artifact_id",
            {
                "artifact_id": "art-1",
                "change_id": "chg-1",
                "base_version": "v1",
                "description": "desc",
            },
        ),
        (
            ArtifactChange,
            "change_id",
            {
                "artifact_id": "art-1",
                "change_id": "chg-1",
                "base_version": "v1",
                "description": "desc",
            },
        ),
        (
            ArtifactChange,
            "base_version",
            {
                "artifact_id": "art-1",
                "change_id": "chg-1",
                "base_version": "v1",
                "description": "desc",
            },
        ),
        (
            ArtifactChange,
            "description",
            {
                "artifact_id": "art-1",
                "change_id": "chg-1",
                "base_version": "v1",
                "description": "desc",
            },
        ),
        (
            ArtifactAdapterResult,
            "artifact_id",
            {"artifact_id": "art-1", "message": "ok"},
        ),
        (
            ArtifactAdapterResult,
            "message",
            {"artifact_id": "art-1", "message": "ok"},
        ),
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


def test_game_record_status_must_be_allowed() -> None:
    with pytest.raises(ValidationError):
        GameRecord(
            game_id="game-1",
            contract=GameContract(
                id="gc-1",
                subject="auth",
                goal="find flaws",
                target=Target(kind="repo"),
                active_roles=["red-team"],
            ),
            status="paused",
            created_at="2026-05-11T10:00:00Z",
            updated_at="2026-05-11T10:00:00Z",
        )


def test_game_round_round_number_must_be_at_least_one() -> None:
    with pytest.raises(ValidationError):
        GameRound(round_number=0)


def test_game_state_current_round_must_be_at_least_one() -> None:
    with pytest.raises(ValidationError):
        GameState(game_id="game-1", run_id="run-0001", current_round=0)


def test_game_result_round_and_max_round_constraints() -> None:
    with pytest.raises(ValidationError):
        GameResponse(
            game_id="game-1",
            run_id="run-20260513-100000-deadbeef",
            rounds_played=0,
            max_rounds=2,
            final_decision=Decision(game_id="game-1", decision="accept", rationale="ok"),
            terminal_reason="accepted",
            final_blue_summary="blue summary",
            final_red_claim="red claim",
        )
    with pytest.raises(ValidationError):
        RoundSummary(
            round_number=0,
            blue_summary="blue",
            red_claim="red",
            referee_decision="revise",
            referee_rationale="rationale",
        )
    with pytest.raises(ValidationError):
        GameResponse(
            game_id="game-1",
            run_id="run-20260513-100000-deadbeef",
            rounds_played=1,
            max_rounds=0,
            final_decision=Decision(game_id="game-1", decision="accept", rationale="ok"),
            terminal_reason="accepted",
            final_blue_summary="blue summary",
            final_red_claim="red claim",
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

    artifact_version_a = ArtifactVersion(artifact_id="art-1", version_id="v1", path="p1")
    artifact_version_b = ArtifactVersion(artifact_id="art-2", version_id="v2", path="p2")
    artifact_version_a.metadata["k"] = "v"
    assert artifact_version_b.metadata == {}

    artifact_change_a = ArtifactChange(
        artifact_id="art-1",
        change_id="chg-1",
        base_version="v1",
        description="d1",
    )
    artifact_change_b = ArtifactChange(
        artifact_id="art-2",
        change_id="chg-2",
        base_version="v2",
        description="d2",
    )
    artifact_change_a.metadata["k"] = "v"
    assert artifact_change_b.metadata == {}

    record_a = GameRecord(
        game_id="game-1",
        contract=GameContract(
            id="gc-1",
            subject="auth",
            goal="find flaws",
            target=Target(kind="repo"),
            active_roles=["red-team"],
        ),
        status="pending",
        created_at="2026-05-11T10:00:00Z",
        updated_at="2026-05-11T10:00:00Z",
    )
    record_b = GameRecord(
        game_id="game-2",
        contract=GameContract(
            id="gc-2",
            subject="payments",
            goal="find flaws",
            target=Target(kind="repo"),
            active_roles=["red-team"],
        ),
        status="running",
        created_at="2026-05-11T10:00:00Z",
        updated_at="2026-05-11T10:00:00Z",
    )
    record_a.metadata["k"] = "v"
    assert record_b.metadata == {}

    round_a = GameRound(round_number=1)
    round_b = GameRound(round_number=2)
    round_a.moves.append(Move(game_id="game-1", role="red-team", summary="s"))
    round_a.findings.append(Finding(game_id="game-1", severity="high", confidence="high", claim="c"))
    assert round_b.moves == []
    assert round_b.findings == []

    state_a = GameState(game_id="game-1", run_id="run-0001")
    state_b = GameState(game_id="game-2", run_id="run-0002")
    state_a.rounds.append(GameRound(round_number=1))
    assert state_b.rounds == []

    result_a = GameResponse(
        game_id="game-1",
        run_id="run-20260513-100000-deadbeef",
        rounds_played=1,
        max_rounds=1,
        final_decision=Decision(game_id="game-1", decision="accept", rationale="ok"),
        terminal_reason="accepted",
        final_blue_summary="blue summary",
        final_red_claim="red claim",
    )
    result_b = GameResponse(
        game_id="game-2",
        run_id="run-20260513-100001-feedbeef",
        rounds_played=1,
        max_rounds=1,
        final_decision=Decision(game_id="game-2", decision="reject", rationale="no"),
        terminal_reason="rejected",
        final_blue_summary="blue summary 2",
        final_red_claim="red claim 2",
    )
    result_a.trace_event_ids.append("e1")
    assert result_b.trace_event_ids == []
    result_a.round_summaries.append(
        RoundSummary(
            round_number=1,
            blue_summary="blue",
            red_claim="red",
            referee_decision="revise",
            referee_rationale="rationale",
        )
    )
    assert result_b.round_summaries == []
