# Purpose

`ARCHITECTURE.md` records implementation evidence.

`SYSTEM.md` defines the normative contract: required operational semantics, boundaries, invariants, and forbidden drift for the active runtime.

This document is prescriptive about what must remain true.

## 1. Canonical Spine

Canonical runtime:

`config/NorthStar -> State -> StateView -> CreateGame -> GameSpec -> PlayGame -> DeltaState -> StateUpdateProposal -> StateService -> export`

This is the only active lifecycle execution path for:

- `init`
- `run`
- `init_and_run`

No other lifecycle is canonical.

## 2. Core Invariants

1. `State` is the authoritative project condition.
2. `State` persists as JSON via the state store/service path.
3. `StateView` is model-facing text projection, not authority.
4. JSON is storage/transport format; it is not `StateView.content`.
5. `NorthStar` belongs to `State`.
6. Project behavior is adapter-owned behind `ProjectTypeAdapter`.
7. Core orchestration remains project-type generic.
8. `CreateGame` is `State`/`NorthStar`-aware through `StateView`.
9. `PlayGame` is `GameSpec`-bound.
10. `StateService` is the mutation boundary for durable state changes.
11. Export is one-way materialization from `State` to output files.
12. Prompts consume `StateView` context, not raw authoritative `State` internals.

## 3. Adapter Contract

`ProjectTypeAdapter` owns project-specific mechanics:

1. initial state creation
2. CreateGame `StateView` rendering
3. PlayGame `StateView` rendering
4. project prompt supplements
5. Blue delta parsing
6. delta -> `StateUpdateProposal` mapping
7. export
8. optional export verification through adapter interface

Core orchestration must call adapter interfaces and remain generic.

## 4. Active Project Types

Active registered project types in canonical runtime:

- `document`
- `coding`

Both participate through the same adapter contract and orchestration path.

## 5. Blackboard Status

Blackboard is not canonical runtime authority.

Current status:

- blackboard is not part of the canonical spine
- authoritative project condition remains `State`
- any blackboard usage is auxiliary history/meta, not mutation authority

If blackboard is reintroduced to canonical flow, it must remain append-only history/meta and never authoritative state.

## 6. Anti-Invariants (Forbidden Drift)

The following are forbidden:

1. Passing raw `State` JSON as `StateView` prompt context.
2. Embedding project-specific document/coding logic in core orchestration.
3. Bypassing `ProjectTypeAdapter` for project-type behavior.
4. Treating English narrative semantics as validator authority.
5. Treating exported files as canonical state.
6. Introducing competing runtime spines.
7. Exposing authoritative state internals directly to prompts outside `StateView` contract.

Concrete forbidden examples include core code that directly inspects `DocumentArtifact`/`CodingArtifact` internals to construct project-specific prompt views.

## 7. Authority and Boundaries

Authority hierarchy:

1. Model outputs are proposals, not authoritative state.
2. Accepted integration is required before durable mutation.
3. Durable mutation occurs only through `StateService`.
4. Export materializes state to filesystem artifacts.
5. Export never defines authoritative state.

## 8. System Alignment Rules

Required alignment:

1. `State != StateView`
2. `core orchestration != adapter mechanics`
3. `export != authoritative state`
4. `prompt context == StateView` (bounded model-facing view)
5. `blackboard != authority`

Current observation: code contains auxiliary blackboard proposal logging paths, but canonical authority remains `State` and canonical lifecycle remains the spine above.
