from __future__ import annotations

from typing import Protocol

from baps.projections import current_open_discrepancies
from baps.schemas import GameRequest, ProjectedState, UnresolvedDiscrepancy


class Planner(Protocol):
    def plan_next_game(
        self,
        projected_state: ProjectedState,
        north_star: str,
    ) -> GameRequest: ...


class DefaultPlanner:
    def plan_next_game(
        self,
        projected_state: ProjectedState,
        north_star: str,
    ) -> GameRequest:
        open_discrepancies = current_open_discrepancies(projected_state)
        selected = self._select_discrepancy(open_discrepancies)
        if selected is None:
            return GameRequest(
                game_type="documentation-refinement",
                subject="Routine bounded maintenance",
                goal=f"Identify one bounded improvement aligned with north star: {north_star}",
                target_kind="maintenance",
                target_ref="project-maintenance",
            )
        return self._build_discrepancy_request(selected, north_star)

    def _select_discrepancy(
        self,
        open_discrepancies: list[UnresolvedDiscrepancy],
    ) -> UnresolvedDiscrepancy | None:
        for discrepancy in open_discrepancies:
            if discrepancy.severity == "high":
                return discrepancy
        if not open_discrepancies:
            return None
        return open_discrepancies[0]

    def _build_discrepancy_request(
        self,
        discrepancy: UnresolvedDiscrepancy,
        north_star: str,
    ) -> GameRequest:
        target_ref_parts = [f"discrepancy_id={discrepancy.id}"]
        if discrepancy.related_artifact_id:
            target_ref_parts.append(f"artifact_id={discrepancy.related_artifact_id}")
        if discrepancy.related_artifact_version:
            target_ref_parts.append(f"artifact_version={discrepancy.related_artifact_version}")

        return GameRequest(
            game_type="documentation-refinement",
            subject=f"Resolve discrepancy {discrepancy.id}: {discrepancy.summary}",
            goal=(
                f"Investigate and propose a bounded fix for discrepancy {discrepancy.id} "
                f"aligned with north star: {north_star}"
            ),
            target_kind="discrepancy",
            target_ref=";".join(target_ref_parts),
        )
