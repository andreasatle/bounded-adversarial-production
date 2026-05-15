from __future__ import annotations

import json
from typing import Protocol

from baps.models import ModelClient
from baps.projections import current_open_discrepancies
from baps.schemas import GameRequest, ProjectedState, UnresolvedDiscrepancy


def _require_non_empty_north_star(north_star: str) -> str:
    if not north_star.strip():
        raise ValueError("north_star must be a non-empty string")
    return north_star


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
        _require_non_empty_north_star(north_star)
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


class LLMPlanner:
    def __init__(
        self,
        model_client: ModelClient,
        fallback_planner: Planner | None = None,
    ):
        self.model_client = model_client
        self.fallback_planner = fallback_planner

    def plan_next_game(
        self,
        projected_state: ProjectedState,
        north_star: str,
    ) -> GameRequest:
        _require_non_empty_north_star(north_star)
        prompt = self._build_prompt(projected_state, north_star)
        model_output = self.model_client.generate(prompt)
        try:
            parsed = json.loads(model_output)
            if not isinstance(parsed, dict):
                raise ValueError("planner output must be a JSON object")
            return GameRequest.model_validate(parsed)
        except (json.JSONDecodeError, ValueError):
            if self.fallback_planner is not None:
                return self.fallback_planner.plan_next_game(projected_state, north_star)
            raise ValueError("failed to parse valid GameRequest JSON from planner model output")

    def _build_prompt(self, projected_state: ProjectedState, north_star: str) -> str:
        open_discrepancies = current_open_discrepancies(projected_state)
        lines = [
            "You are selecting the next bounded game request.",
            "Return JSON only with keys: game_type, subject, goal, target_kind, target_ref, state_source_ids.",
            "",
            f"NORTH_STAR: {north_star}",
            "",
            f"OPEN_DISCREPANCIES_COUNT: {len(open_discrepancies)}",
        ]
        for discrepancy in open_discrepancies[:5]:
            artifact_ref = ""
            if discrepancy.related_artifact_id:
                artifact_ref = f", artifact_id={discrepancy.related_artifact_id}"
            lines.append(
                f"- discrepancy id={discrepancy.id}, severity={discrepancy.severity}, "
                f"summary={discrepancy.summary}{artifact_ref}"
            )

        lines.extend(
            [
                f"ACCEPTED_ACCOMPLISHMENTS_COUNT: {len(projected_state.accepted_accomplishments)}",
                f"ACCEPTED_ARCHITECTURE_COUNT: {len(projected_state.accepted_architecture)}",
                f"ACCEPTED_CAPABILITIES_COUNT: {len(projected_state.accepted_capabilities)}",
                f"ACTIVE_GAMES_COUNT: {len(projected_state.active_games)}",
                "",
                "Select one bounded next game aligned to NORTH_STAR.",
            ]
        )
        return "\n".join(lines)
