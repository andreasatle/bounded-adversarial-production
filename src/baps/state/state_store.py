"""Defines the StateStore protocol and the JsonStateStore implementation for State persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from baps.state.state import State


class StateStore(Protocol):
    """Protocol defining the persistence interface for State objects."""

    def load(self) -> State:
        """Load and return the persisted State."""
        ...

    def save(self, state: State) -> None:
        """Persist the given State."""
        ...


class JsonStateStore:
    """Stores State as JSON at a fixed file path."""

    def __init__(self, path: Path):
        """Initialize with the file path where State JSON will be read and written."""
        self.path = path

    def load(self) -> State:
        """Read and deserialize State from the JSON file, raising FileNotFoundError if absent."""
        if not self.path.exists():
            raise FileNotFoundError(f"state file not found: {self.path}")
        raw = self.path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return State.model_validate(data)

    def save(self, state: State) -> None:
        """Serialize State to JSON and write it to the configured file path."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(state.model_dump(mode="json")),
            encoding="utf-8",
        )
