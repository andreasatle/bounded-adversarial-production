from __future__ import annotations

from baps.blackboard import Blackboard
from baps.schemas import (
    AcceptedAccomplishment,
    AcceptedArchitectureItem,
    AcceptedCapability,
    ActiveGameSummary,
    Event,
    ProjectedState,
    UnresolvedDiscrepancy,
)


def build_projected_state(events: list[Event]) -> ProjectedState:
    active_by_run: dict[str, ActiveGameSummary] = {}
    active_run_order: list[str] = []
    accomplishments_by_decision_id: dict[str, AcceptedAccomplishment] = {}
    accomplishment_order: list[str] = []
    architecture_by_decision_id: dict[str, AcceptedArchitectureItem] = {}
    architecture_order: list[str] = []
    capabilities_by_decision_id: dict[str, AcceptedCapability] = {}
    capability_order: list[str] = []
    discrepancies_by_run: dict[str, UnresolvedDiscrepancy] = {}
    discrepancy_order: list[str] = []

    for event in events:
        payload = event.payload
        if event.type == "integration_decision_recorded":
            integration_decision = payload.get("integration_decision")
            if not isinstance(integration_decision, dict):
                continue
            decision_id = integration_decision.get("id")
            run_id = integration_decision.get("run_id")
            outcome = integration_decision.get("outcome")
            target_kind = integration_decision.get("target_kind")
            summary = integration_decision.get("summary")
            if not isinstance(decision_id, str) or not decision_id.strip():
                continue
            if (
                decision_id in accomplishments_by_decision_id
                or decision_id in architecture_by_decision_id
                or decision_id in capabilities_by_decision_id
            ):
                continue
            if outcome != "accepted":
                continue
            if not isinstance(run_id, str) or not run_id.strip():
                continue
            if not isinstance(summary, str) or not summary.strip():
                continue

            metadata = {
                "source_event_id": event.id,
                "integration_decision_id": decision_id,
                "integration_outcome": outcome,
                "integration_target_kind": target_kind,
            }
            if target_kind == "accomplishment":
                accomplishments_by_decision_id[decision_id] = AcceptedAccomplishment(
                    id=decision_id,
                    summary=summary,
                    source_run_id=run_id,
                    metadata=metadata,
                )
                accomplishment_order.append(decision_id)
            elif target_kind == "architecture":
                architecture_by_decision_id[decision_id] = AcceptedArchitectureItem(
                    id=decision_id,
                    title=summary,
                    source_event_id=run_id,
                    metadata=metadata,
                )
                architecture_order.append(decision_id)
            elif target_kind == "capability":
                capabilities_by_decision_id[decision_id] = AcceptedCapability(
                    id=decision_id,
                    name=summary,
                    source_run_id=run_id,
                    metadata=metadata,
                )
                capability_order.append(decision_id)
            continue
        if event.type == "discrepancy_resolution_recorded":
            resolution = payload.get("discrepancy_resolution")
            if not isinstance(resolution, dict):
                continue
            discrepancy_id = resolution.get("discrepancy_id")
            if not isinstance(discrepancy_id, str) or not discrepancy_id.strip():
                continue
            discrepancy = discrepancies_by_run.get(discrepancy_id)
            if discrepancy is None:
                continue
            discrepancy.status = "resolved"
            continue
        if event.type == "discrepancy_supersession_recorded":
            supersession = payload.get("discrepancy_supersession")
            if not isinstance(supersession, dict):
                continue
            superseded_discrepancy_id = supersession.get("superseded_discrepancy_id")
            superseding_discrepancy_id = supersession.get("superseding_discrepancy_id")
            if (
                not isinstance(superseded_discrepancy_id, str)
                or not superseded_discrepancy_id.strip()
            ):
                continue
            if (
                not isinstance(superseding_discrepancy_id, str)
                or not superseding_discrepancy_id.strip()
            ):
                continue
            discrepancy = discrepancies_by_run.get(superseded_discrepancy_id)
            if discrepancy is None:
                continue
            discrepancy.status = "superseded"
            discrepancy.metadata["superseding_discrepancy_id"] = superseding_discrepancy_id
            continue
        if event.type == "accepted_state_supersession_recorded":
            supersession = payload.get("accepted_state_supersession")
            if not isinstance(supersession, dict):
                continue
            superseded_item_id = supersession.get("superseded_item_id")
            superseding_item_id = supersession.get("superseding_item_id")
            target_kind = supersession.get("target_kind")
            if not isinstance(superseded_item_id, str) or not superseded_item_id.strip():
                continue
            if not isinstance(superseding_item_id, str) or not superseding_item_id.strip():
                continue

            if target_kind == "accomplishment":
                item = accomplishments_by_decision_id.get(superseded_item_id)
            elif target_kind == "architecture":
                item = architecture_by_decision_id.get(superseded_item_id)
            elif target_kind == "capability":
                item = capabilities_by_decision_id.get(superseded_item_id)
            else:
                item = None

            if item is None:
                continue
            item.metadata["superseded"] = True
            item.metadata["superseding_item_id"] = superseding_item_id
            continue
        if event.type == "accepted_state_revocation_recorded":
            revocation = payload.get("accepted_state_revocation")
            if not isinstance(revocation, dict):
                continue
            revoked_item_id = revocation.get("revoked_item_id")
            target_kind = revocation.get("target_kind")
            revocation_id = revocation.get("id")
            if not isinstance(revoked_item_id, str) or not revoked_item_id.strip():
                continue
            if not isinstance(revocation_id, str) or not revocation_id.strip():
                continue

            if target_kind == "accomplishment":
                item = accomplishments_by_decision_id.get(revoked_item_id)
            elif target_kind == "architecture":
                item = architecture_by_decision_id.get(revoked_item_id)
            elif target_kind == "capability":
                item = capabilities_by_decision_id.get(revoked_item_id)
            else:
                item = None

            if item is None:
                continue
            item.metadata["revoked"] = True
            item.metadata["revocation_id"] = revocation_id
            continue

        game_id = payload.get("game_id")
        run_id = payload.get("run_id")
        if not isinstance(game_id, str) or not game_id.strip():
            continue
        if not isinstance(run_id, str) or not run_id.strip():
            continue

        if event.type == "game_started":
            if run_id in active_by_run:
                continue
            active_by_run[run_id] = ActiveGameSummary(
                id=run_id,
                title=game_id,
                source_run_id=run_id,
                metadata={"game_id": game_id},
            )
            active_run_order.append(run_id)
        elif event.type == "game_completed":
            if (
                payload.get("terminal_outcome") in {"rejected_locally", "revision_budget_exhausted"}
                and run_id not in discrepancies_by_run
            ):
                discrepancies_by_run[run_id] = UnresolvedDiscrepancy(
                    id=run_id,
                    summary=_derive_discrepancy_summary(payload),
                    kind="unresolved_finding",
                    severity="medium",
                    status="open",
                    source_event_id=event.id,
                    metadata={
                        "source_run_id": run_id,
                        "game_id": game_id,
                        "terminal_outcome": payload.get("terminal_outcome"),
                        "integration_recommendation": payload.get("integration_recommendation"),
                    },
                )
                discrepancy_order.append(run_id)
            if run_id not in active_by_run:
                continue
            del active_by_run[run_id]
            active_run_order = [existing_run_id for existing_run_id in active_run_order if existing_run_id != run_id]

    accepted_accomplishments = [
        accomplishments_by_decision_id[decision_id]
        for decision_id in accomplishment_order
        if decision_id in accomplishments_by_decision_id
    ]
    accepted_architecture = [
        architecture_by_decision_id[decision_id]
        for decision_id in architecture_order
        if decision_id in architecture_by_decision_id
    ]
    accepted_capabilities = [
        capabilities_by_decision_id[decision_id]
        for decision_id in capability_order
        if decision_id in capabilities_by_decision_id
    ]
    unresolved_discrepancies = [
        discrepancies_by_run[run_id]
        for run_id in discrepancy_order
        if run_id in discrepancies_by_run
    ]
    active_games = [active_by_run[run_id] for run_id in active_run_order if run_id in active_by_run]

    return ProjectedState(
        accepted_accomplishments=accepted_accomplishments,
        accepted_architecture=accepted_architecture,
        accepted_capabilities=accepted_capabilities,
        unresolved_discrepancies=unresolved_discrepancies,
        active_games=active_games,
        metadata={
            "event_count": len(events),
            "active_game_count": len(active_games),
            "accepted_accomplishment_count": len(accepted_accomplishments),
            "accepted_architecture_count": len(accepted_architecture),
            "accepted_capability_count": len(accepted_capabilities),
            "unresolved_discrepancy_count": len(unresolved_discrepancies),
        },
    )


def build_projected_state_from_blackboard(blackboard: Blackboard) -> ProjectedState:
    return build_projected_state(blackboard.read_all())


def current_accepted_accomplishments(state: ProjectedState) -> list[AcceptedAccomplishment]:
    return [
        item
        for item in state.accepted_accomplishments
        if item.metadata.get("superseded") is not True and item.metadata.get("revoked") is not True
    ]


def current_accepted_architecture(state: ProjectedState) -> list[AcceptedArchitectureItem]:
    return [
        item
        for item in state.accepted_architecture
        if item.metadata.get("superseded") is not True and item.metadata.get("revoked") is not True
    ]


def current_accepted_capabilities(state: ProjectedState) -> list[AcceptedCapability]:
    return [
        item
        for item in state.accepted_capabilities
        if item.metadata.get("superseded") is not True and item.metadata.get("revoked") is not True
    ]


def _derive_discrepancy_summary(payload: dict) -> str:
    state = payload.get("state")
    if isinstance(state, dict):
        final_decision = state.get("final_decision")
        if isinstance(final_decision, dict):
            rationale = final_decision.get("rationale")
            if isinstance(rationale, str) and rationale.strip():
                return rationale

    run_id = payload.get("run_id")
    terminal_outcome = payload.get("terminal_outcome")
    if isinstance(run_id, str) and run_id.strip() and isinstance(terminal_outcome, str):
        return f"Run {run_id} unresolved: {terminal_outcome}"
    if isinstance(run_id, str) and run_id.strip():
        return f"Run {run_id} unresolved"
    return "Run unresolved"
