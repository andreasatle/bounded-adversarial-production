from __future__ import annotations

import json
from pathlib import Path

from baps.schemas import (
    AcceptedStateSupersession,
    DiscrepancyResolution,
    DiscrepancySupersession,
    Event,
    IntegrationDecision,
)


class Blackboard:
    def __init__(self, path: Path):
        self.path = path

    def append(self, event: Event) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.model_dump(mode="json")))
            f.write("\n")

    def read_all(self) -> list[Event]:
        if not self.path.exists():
            return []

        events: list[Event] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                raw = json.loads(line)
                events.append(Event.model_validate(raw))
        return events

    def query(self, event_type: str) -> list[Event]:
        if not event_type.strip():
            raise ValueError("event_type must be a non-empty string")
        return [event for event in self.read_all() if event.type == event_type]

    def query_by_run(self, run_id: str) -> list[Event]:
        if not run_id.strip():
            raise ValueError("run_id must be a non-empty string")
        return [event for event in self.read_all() if event.payload.get("run_id") == run_id]

    def query_completed_runs(self) -> list[Event]:
        return self.query("game_completed")

    def append_integration_decision(self, decision: IntegrationDecision) -> None:
        self.append(
            Event(
                id=f"integration:{decision.id}",
                type="integration_decision_recorded",
                payload={"integration_decision": decision.model_dump(mode="json")},
            )
        )

    def append_discrepancy_resolution(self, resolution: DiscrepancyResolution) -> None:
        self.append(
            Event(
                id=f"discrepancy_resolution:{resolution.id}",
                type="discrepancy_resolution_recorded",
                payload={"discrepancy_resolution": resolution.model_dump(mode="json")},
            )
        )

    def append_discrepancy_supersession(self, supersession: DiscrepancySupersession) -> None:
        self.append(
            Event(
                id=f"discrepancy_supersession:{supersession.id}",
                type="discrepancy_supersession_recorded",
                payload={"discrepancy_supersession": supersession.model_dump(mode="json")},
            )
        )

    def append_accepted_state_supersession(self, supersession: AcceptedStateSupersession) -> None:
        self.append(
            Event(
                id=f"accepted_state_supersession:{supersession.id}",
                type="accepted_state_supersession_recorded",
                payload={"accepted_state_supersession": supersession.model_dump(mode="json")},
            )
        )
