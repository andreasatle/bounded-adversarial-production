# SYSTEM.md

## Purpose
This document defines the normative system contract for the current canonical `baps-run` architecture.

`ARCHITECTURE.md` describes implementation details and evidence.

`SYSTEM.md` defines the required operational semantics and boundaries the implementation must preserve.

---

## 1. Canonical Spine
The canonical execution spine is:

`config/NorthStar -> State -> StateView -> CreateGame -> GameSpec -> PlayGame -> DeltaState -> StateUpdateProposal -> StateService -> export`

This spine is the only active product path for lifecycle execution (`init`, `run`, `init_and_run`).

---

## 2. Core Invariants

1. `State` is authoritative project condition and is persisted as JSON.
2. `StateView` is model-facing rendered text.
3. JSON is storage/transport format, not `StateView.content`.
4. `NorthStar` is part of authoritative `State`.
5. Project-specific behavior lives behind `ProjectTypeAdapter`.
6. Core orchestration must not special-case `document` or `coding`.
7. `CreateGame` is `State`/`NorthStar`-aware.
8. `PlayGame` is `GameSpec`-bound.
9. `StateService` is the state mutation boundary.
10. Export is one-way from `State` to output files.
11. Model prompts consume `StateView` only, not authoritative `State` internals.

---

## 3. Adapter Contract
`ProjectTypeAdapter` owns project-type mechanics:

1. initial state creation
2. CreateGame `StateView` rendering
3. PlayGame `StateView` rendering
4. project-specific Blue prompt supplement
5. delta parsing
6. delta -> `StateUpdateProposal` mapping
7. export

Core orchestration calls adapter interfaces and remains project-type generic.

---

## 4. Active Project Types
Current active project types:

- `document`
- `coding`

These are equal participants in adapter registration and dispatch.

---

## 5. Blackboard Status
Blackboard/event history is not currently active in canonical `baps-run` flow.

If reintroduced into the canonical spine, blackboard data must be:

1. append-only run history/meta
2. non-authoritative relative to `State`

`State` remains the only authoritative project condition.

---

## 6. Anti-Invariants (Forbidden Drift)

1. Do not pass raw `State` JSON to model prompts as `StateView`.
2. Do not place document/coding-specific logic in `run.py` core orchestration.
3. Do not treat English-semantic parsing in validators as authority.
4. Do not let output files become canonical state.
5. Do not introduce parallel competing execution engines.
6. Do not bypass `ProjectTypeAdapter` boundaries from core orchestration.

Examples of forbidden drift:

- `run.py` inspecting `DocumentArtifact`
- `run.py` inspecting `CodingArtifact`
- `run.py` reading `sections`/`files` directly
- `run.py` constructing project-specific `StateView`s

7. Do not pass authoritative `State` internals directly to prompts.

Prompts consume `StateView` only.

These anti-invariants exist because previous architectural drift occurred around:

- `State` vs `StateView` confusion
- document-specific leakage into core orchestration
- prompt access to raw state structures

---

## 7. Authority and Boundaries

1. Model outputs are proposals/evidence until integrated.
2. Accepted state mutation happens only through `StateService`.
3. Export materializes state; it does not define state.

This boundary set is mandatory for preserving deterministic contracts, project-type generality, and ontology clarity.
