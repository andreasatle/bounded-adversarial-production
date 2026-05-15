from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from baps.state import State


class StateStore(Protocol):
    def load(self) -> State:
        ...

    def save(self, state: State) -> None:
        ...


class JsonStateStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> State:
        if not self.path.exists():
            raise FileNotFoundError(f"state file not found: {self.path}")
        raw = self.path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return State.model_validate(data)

    def save(self, state: State) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(state.model_dump(mode="json")),
            encoding="utf-8",
        )
