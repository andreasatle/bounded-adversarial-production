import pytest
from pydantic import BaseModel

from baps.roles import RoleInvocationError, RoleInvocationGuard


class ExampleOutput(BaseModel):
    game_id: str
    role: str


def test_successful_invocation_returns_validated_model() -> None:
    guard = RoleInvocationGuard()

    def role_callable():
        return ExampleOutput(game_id="g1", role="blue")

    result = guard.invoke(role_callable=role_callable, args=(), output_model=ExampleOutput)
    assert isinstance(result, ExampleOutput)
    assert result.game_id == "g1"


def test_raw_dict_output_is_accepted_if_valid() -> None:
    guard = RoleInvocationGuard()

    def role_callable():
        return {"game_id": "g1", "role": "blue"}

    result = guard.invoke(role_callable=role_callable, args=(), output_model=ExampleOutput)
    assert result.role == "blue"


def test_invalid_output_retried_then_succeeds() -> None:
    guard = RoleInvocationGuard(max_attempts=2)
    calls = {"count": 0}

    def role_callable():
        calls["count"] += 1
        if calls["count"] == 1:
            return {"game_id": "g1"}
        return {"game_id": "g1", "role": "blue"}

    result = guard.invoke(role_callable=role_callable, args=(), output_model=ExampleOutput)
    assert result.role == "blue"
    assert calls["count"] == 2


def test_invalid_output_fails_after_max_attempts() -> None:
    guard = RoleInvocationGuard(max_attempts=2)

    def role_callable():
        return {"game_id": "g1"}

    with pytest.raises(RoleInvocationError) as excinfo:
        guard.invoke(role_callable=role_callable, args=(), output_model=ExampleOutput)
    assert "2 attempts" in str(excinfo.value)
    assert excinfo.value.failure_kind == "schema_validation_failed"


def test_semantic_validator_failure_retried_then_succeeds() -> None:
    guard = RoleInvocationGuard(max_attempts=2)
    calls = {"count": 0}

    def role_callable():
        calls["count"] += 1
        if calls["count"] == 1:
            return {"game_id": "g1", "role": "red"}
        return {"game_id": "g1", "role": "blue"}

    def semantic_validator(output: ExampleOutput) -> None:
        if output.role != "blue":
            raise ValueError("role must be blue")

    result = guard.invoke(
        role_callable=role_callable,
        args=(),
        output_model=ExampleOutput,
        semantic_validator=semantic_validator,
    )
    assert result.role == "blue"
    assert calls["count"] == 2


def test_semantic_validator_failure_fails_after_max_attempts() -> None:
    guard = RoleInvocationGuard(max_attempts=2)

    def role_callable():
        return {"game_id": "g1", "role": "red"}

    def semantic_validator(output: ExampleOutput) -> None:
        if output.role != "blue":
            raise ValueError("role must be blue")

    with pytest.raises(RoleInvocationError) as excinfo:
        guard.invoke(
            role_callable=role_callable,
            args=(),
            output_model=ExampleOutput,
            semantic_validator=semantic_validator,
        )
    assert "2 attempts" in str(excinfo.value)
    assert "role must be blue" in str(excinfo.value)
    assert excinfo.value.failure_kind == "semantic_validation_failed"


def test_max_attempts_exhaustion_still_raised_after_configured_attempts() -> None:
    guard = RoleInvocationGuard(max_attempts=3)
    calls = {"count": 0}

    def role_callable():
        calls["count"] += 1
        return {"game_id": "g1"}

    with pytest.raises(RoleInvocationError):
        guard.invoke(role_callable=role_callable, args=(), output_model=ExampleOutput)
    assert calls["count"] == 3


def test_max_attempts_less_than_one_raises_value_error() -> None:
    with pytest.raises(ValueError):
        RoleInvocationGuard(max_attempts=0)


def test_role_callable_receives_provided_args() -> None:
    guard = RoleInvocationGuard()

    def role_callable(game_id: str, role: str):
        return {"game_id": game_id, "role": role}

    result = guard.invoke(
        role_callable=role_callable,
        args=("g1", "blue"),
        output_model=ExampleOutput,
    )
    assert result.game_id == "g1"
    assert result.role == "blue"
