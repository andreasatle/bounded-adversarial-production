# RENAME-PLAN

## Purpose
This document defines a narrow, documentation-only rename/consolidation plan derived from:

- `docs/ONTOLOGY-MAPPING.md`
- `docs/INTEGRATION-ONTOLOGY.md`
- `docs/ARCHITECTURE.md`
- `docs/SYSTEM.md`
- `docs/NORTH-STAR.md`

Scope:

- no code changes,
- no import changes,
- no behavior changes,
- no architectural redesign.

The intent is to prepare future small rename tasks, not to execute them.

## Authority Layers Used in This Plan

- **Runtime execution**: transient game/loop execution artifacts and decisions.
- **Process/history**: append-only event governance, replay, and provenance records.
- **State mutation**: authoritative decisions and proposals that may mutate `State` via explicit service boundaries.

## Rename/Consolidation Table

| current name | owner module | authority layer | problem | classification | candidate target name | rationale |
|---|---|---|---|---|---|---|
| `Decision` (runtime referee output model) | `src/baps/schemas.py` (used by runtime roles) | runtime execution | Name is generic and easily confused with integration decisions. | DEFER | `RefereeDecision` | Improves disambiguation, but touches broad runtime and test surface; defer to avoid churn. |
| `schemas.IntegrationDecision` | `src/baps/schemas.py` (runtime governance path) | process/history | Shares name with `integration.IntegrationDecision` but represents different semantics/shape. | ADAPTER | `RuntimeIntegrationDecision` (doc target) | Preserve existing runtime behavior; add mapping/alias layer first, then rename if needed. |
| `integration.IntegrationDecision` | `src/baps/integration.py` | state mutation | Same class name as runtime model creates ambiguity. | KEEP | `IntegrationDecision` | Current ontology conclusion: this is authoritative for state mutation. Keep as canonical mutation decision name. |
| `runtime_integration.py` | `src/baps/runtime_integration.py` | process/history | Module name conflicts semantically with `integration.py`; both concern “integration” but different layers. | RENAME | `runtime_integration.py` | Clarifies runtime-policy + blackboard governance role without changing behavior. |
| `integration.py` | `src/baps/integration.py` | state mutation | Name competes with runtime `runtime_integration.py`. | KEEP | `integration.py` | Already holds mutation-authoritative decision semantics and update derivation bridges. |
| `ProjectedState` | `src/baps/schemas.py` + `src/baps/projections.py` | process/history | “Projection” term overlaps with state-view projection (`StateView`). | MERGE | `ReplayStateView` (doc target) | Candidate terminology unifies under “view” while preserving replay-specific identity. |
| `StateView` | `src/baps/northstar_projection.py` | runtime execution (LLM input view), derived from state/process sources | Generic name can collide with replay concepts and future views. | DEFER | `ProjectedStateView` | Rename is plausible but broad; defer until replay/view naming policy is finalized. |
| `NorthStarView` | `src/baps/northstar_projection.py` | runtime execution (LLM input view) | Alias to `StateView`; clear in purpose but tied to broader “view” ambiguity. | KEEP | `NorthStarView` | Name is specific and useful; keep while higher-level projection/view naming converges. |
| `ProjectionPolicy` | `src/baps/northstar_projection.py` | runtime execution (view rendering policy declaration) | Policy enum currently mostly declarative; term “projection” overlaps with replay projection. | DEFER | `ViewPolicy` | Rename may improve clarity but should follow projection/replay naming merge decision. |
| `ProjectionType` | `src/baps/northstar_projection.py` | runtime execution (view type tagging) | Same overlap issue as above. | DEFER | `ViewType` | Hold until terminology convergence to avoid piecemeal renames. |
| `Artifact` | `src/baps/schemas.py` / `src/baps/artifacts.py` | process/history + filesystem lifecycle | Collides conceptually with `StateArtifact` identity records. | ADAPTER | `FilesystemArtifact` (doc target) | Introduce bridge vocabulary first; code rename can be narrow later if needed. |
| `StateArtifact` | `src/baps/state.py` | state mutation | Distinct from filesystem artifact but easy to confuse with generic `Artifact`. | KEEP | `StateArtifact` | Name already encodes authoritative-state identity semantics. |
| `ArtifactAdapter` | `src/baps/artifacts.py` | process/history + filesystem lifecycle | Collides with state-side adapter language (`StateArtifactAdapter`). | RENAME | `FilesystemArtifactAdapter` | Clarifies ownership and side-effect boundary of filesystem lifecycle adapters. |
| `StateArtifactRegistry` | `src/baps/state.py` | state mutation | Name is explicit and currently clear. | KEEP | `StateArtifactRegistry` | Already precise and aligned with state-authoritative adapter boundary. |

## Additional Narrow Candidates (Optional)

| current name | owner module | authority layer | problem | classification | candidate target name | rationale |
|---|---|---|---|---|---|---|
| `Integrator` (runtime policy wrapper) | `src/baps/runtime_integration.py` | process/history | Name overlaps with state-centric `Integrator` protocol. | RENAME | `RuntimeIntegrator` | Clarifies role without changing policy logic. |
| `Integrator` (state-centric protocol) | `src/baps/integration.py` | state mutation | Name overlaps with runtime wrapper. | KEEP | `Integrator` | Keep as canonical mutation integration protocol if runtime side is prefixed. |

## Sequencing Guidance (Documentation-Only)

1. **Adapter-first phase**
- Add explicit compatibility documentation and mapping tables between runtime and state-centric decision models.
- Avoid immediate broad rename PRs.

2. **Runtime-prefix phase**
- Prefer narrow renames around runtime integration identifiers (`runtime_integration.py`, runtime `Integrator`, runtime `IntegrationDecision`) first.
- Keep state-centric `integration.py` terminology stable during this phase.

3. **Projection/view convergence phase**
- Decide one umbrella terminology (`projection` vs `view`) for replay and LLM-facing artifacts.
- Apply only after a single glossary update is approved.

4. **Artifact boundary phase**
- Rename filesystem adapter terms only where ambiguity is high (`ArtifactAdapter` family).
- Keep `StateArtifact`/`StateArtifactRegistry` unchanged.

## Constraints Preserved

- No proposal in this document requires behavior changes.
- No proposal in this document changes authority conclusions.
- State-centric `integration.IntegrationDecision` remains the authoritative integration decision for **state mutation**.
- Runtime integration remains a compatibility/governance path until explicit merge work is performed.
