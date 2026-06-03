"""StateService: the single authoritative mutation boundary for loading, validating, and updating State."""

from __future__ import annotations

from baps.state.state import (
    DeltaState,
    State,
    StateArtifactRegistry,
    apply_state_delta,
    fingerprint_state,
    validate_state_artifacts,
)
from baps.state.state_store import StateStore


class StateService:
    """Provides the single authoritative mutation boundary for State via load, validate, and apply_delta."""

    def __init__(self, store: StateStore, registry: StateArtifactRegistry):
        """Initialize with a backing store and an artifact registry for validation."""
        self.store = store
        self.registry = registry

    def load_state(self) -> State:
        """Load and return the current State from the backing store without validation."""
        return self.store.load()

    def validate_state(self) -> State:
        """Load the current State and validate all artifacts through the registry."""
        state = self.store.load()
        return validate_state_artifacts(state, self.registry)

    def apply_delta(self, delta: DeltaState) -> State:
        """Apply a typed DeltaState directly.

        This is the canonical runtime integration path used by orchestration.
        """
        current = self.store.load()
        validated_current = validate_state_artifacts(current, self.registry)
        updated = apply_state_delta(validated_current, delta)
        validated_updated = validate_state_artifacts(updated, self.registry)
        self.store.save(validated_updated)
        return validated_updated

    def states_differ(self, before: State, after: State) -> bool:
        """Return True if two States have different fingerprints."""
        return fingerprint_state(before) != fingerprint_state(after)
