from __future__ import annotations

from baps.state import (
    State,
    StateArtifactRegistry,
    StateUpdateProposal,
    apply_state_update,
    validate_state_artifacts,
    validate_update_base_state,
)
from baps.state_store import StateStore


class StateService:
    def __init__(self, store: StateStore, registry: StateArtifactRegistry):
        self.store = store
        self.registry = registry

    def load_state(self) -> State:
        return self.store.load()

    def validate_state(self) -> State:
        state = self.store.load()
        return validate_state_artifacts(state, self.registry)

    def apply_update(self, proposal: StateUpdateProposal) -> State:
        current = self.store.load()
        validated_current = validate_state_artifacts(current, self.registry)
        if not validate_update_base_state(validated_current, proposal):
            raise ValueError("base_state_fingerprint does not match current state")
        updated = apply_state_update(validated_current, proposal)
        validated_updated = validate_state_artifacts(updated, self.registry)
        self.store.save(validated_updated)
        return validated_updated
