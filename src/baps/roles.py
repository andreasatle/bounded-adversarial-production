from __future__ import annotations

from pydantic import BaseModel, ValidationError


class RoleInvocationError(Exception):
    pass


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

        for _ in range(self.max_attempts):
            try:
                raw_output = role_callable(*args)
                validated_output = output_model.model_validate(raw_output)
                if semantic_validator is not None:
                    semantic_validator(validated_output)
                return validated_output
            except (ValidationError, ValueError) as exc:
                last_error = exc

        if last_error is None:
            raise RoleInvocationError(
                f"Role invocation failed after {self.max_attempts} attempts: unknown error"
            )

        raise RoleInvocationError(
            f"Role invocation failed after {self.max_attempts} attempts: {last_error}"
        ) from last_error
