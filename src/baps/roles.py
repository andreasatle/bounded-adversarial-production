from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ValidationError


RoleInvocationFailureKind = Literal[
    "schema_validation_failed",
    "semantic_validation_failed",
    "max_attempts_exhausted",
]


class RoleInvocationError(Exception):
    def __init__(
        self,
        *,
        failure_kind: RoleInvocationFailureKind,
        max_attempts: int,
        detail: str,
    ):
        self.failure_kind = failure_kind
        self.max_attempts = max_attempts
        self.detail = detail
        super().__init__(
            f"Role invocation failed after {max_attempts} attempts "
            f"(failure_kind={failure_kind}): {detail}"
        )


class RoleInvocationGuard:
    def __init__(self, max_attempts: int = 2):
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.max_attempts = max_attempts

    def invoke(
        self,
        role_callable,
        args: tuple,
        output_model: type[BaseModel],
        semantic_validator=None,
    ) -> BaseModel:
        last_error: Exception | None = None
        last_failure_kind: RoleInvocationFailureKind | None = None

        for _ in range(self.max_attempts):
            try:
                raw_output = role_callable(*args)
                validated_output = output_model.model_validate(raw_output)
                if semantic_validator is not None:
                    semantic_validator(validated_output)
                return validated_output
            except ValidationError as exc:
                last_error = exc
                last_failure_kind = "schema_validation_failed"
            except ValueError as exc:
                last_error = exc
                last_failure_kind = "semantic_validation_failed"

        if last_error is None:
            raise RoleInvocationError(
                failure_kind="max_attempts_exhausted",
                max_attempts=self.max_attempts,
                detail="unknown error",
            )

        raise RoleInvocationError(
            failure_kind=(
                last_failure_kind if last_failure_kind is not None else "max_attempts_exhausted"
            ),
            max_attempts=self.max_attempts,
            detail=str(last_error),
        ) from last_error
