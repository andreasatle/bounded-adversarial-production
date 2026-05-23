# Purpose

`ARCHITECTURE.md` records implementation evidence.

`SYSTEM.md` defines the normative contract: required operational semantics, boundaries, invariants, and forbidden drift for the active runtime.

This document is prescriptive about what must remain true.

## 1. Canonical Spine

Canonical runtime:

```
config/NorthStar → State → StateView → CreateGame
                                           ↓
                                    DecomposeSpec? ──→ recursive sub-gaps (up to max_depth)
                                           ↓
                                   GameSpec (context_chain)
                                           ↓
                                       PlayGame
                                           ↓
                               DeltaState → StateUpdateProposal → StateService → export
```

This is the only active lifecycle execution path for `init`, `run`, and `init_and_run`. No other lifecycle is canonical.

CreateGame is a **gap-analysis operation**, not a step-forward operation. It compares current state against NorthStar intent and either produces a `GameSpec` to close the highest-priority gap directly, or a `DecomposeSpec` to split the gap into coherent sub-gaps solved recursively.

## 2. Core Invariants

1. `State` is the authoritative project condition.
2. `State` persists as JSON via the state store/service path.
3. `StateView` is model-facing text projection, not authority.
4. JSON is storage/transport format; it is not `StateView.content`.
5. `NorthStar` belongs to `State` and is the target all gap analysis measures against.
6. `NorthStar` is immutable through the automated pipeline; updates require human approval.
7. Project behavior is adapter-owned behind `ProjectTypeAdapter`.
8. Core orchestration remains project-type generic.
9. `CreateGame` is `State`/`NorthStar`-aware through `StateView`. It performs gap analysis, not step derivation.
10. `PlayGame` is `GameSpec`-bound. It has no access to `NorthStar` directly.
11. `GameSpec.context_chain` carries all ancestor gap descriptions from the coarsest decomposition to the immediate task. Blue sees the full chain.
12. `StateService` is the mutation boundary for durable state changes.
13. `StateService` rejects proposals targeting NorthStar artifacts.
14. Export is one-way materialization from `State` to output files.
15. Prompts consume `StateView` context, not raw authoritative `State` internals.

## 3. Adapter Contract

`ProjectTypeAdapter` owns project-specific mechanics:

1. initial state creation
2. CreateGame `StateView` rendering
3. PlayGame `StateView` rendering
4. project prompt supplements (CreateGame, Blue, Red, Referee)
5. Blue delta parsing
6. delta → `StateUpdateProposal` mapping
7. export
8. optional export verification

Core orchestration must call adapter interfaces and remain generic.

## 4. Active Project Types

Active registered project types in canonical runtime:

- `document` — section-based document evolution (`append_section`, `modify_section`, `delete_section`)
- `coding` — file-based codebase evolution (`write_file`, `write_files`, `delete_file`)

Both participate through the same adapter contract and orchestration path.

## 5. Multiscale Decomposition Contract

When CreateGame returns a `DecomposeSpec`:

- `_solve_gap` recursively solves each `SubGapSpec` at `depth + 1`
- The current gap's description is prepended to `context_chain` before each recursive call
- Recursion is bounded by `max_depth` (config key, default 3)
- `NoNewGameError` at depth > 0 means the sub-gap is satisfied; only at depth 0 does it stop the run
- Only leaf `PlayGame` executions count against `max_iterations`
- `max_depth_reached` is a valid stop reason when decomposition exceeds the depth limit

## 6. NorthStar Proposal Flow

When CreateGame signals trajectory drift:

- Returns `{"northstar_update_needed": true, "rationale": "...", "proposed_northstar": "..."}`
- Runtime appends a JSONL event to `<workspace>/blackboard/northstar_proposals.jsonl`
- Stop reason is set to `northstar_update_proposed`
- No state is mutated
- Human reviews proposals and manually updates the NorthStar source
- `baps-apply-northstar <workspace>` assists with applying an approved proposal

Blackboard is append-only and non-authoritative. It never feeds back into `State`.

## 7. Stop Conditions

| Stop reason | Meaning |
|---|---|
| `iteration_limit_reached` | `max_iterations` leaf games executed |
| `create_game_no_new_game` | No gap remains at depth 0 |
| `play_game_no_delta` | PlayGame produced no accepted delta |
| `no_state_change` | Accepted delta produced no state change |
| `northstar_update_proposed` | Trajectory drift detected; human approval needed |
| `max_depth_reached` | Decomposition exceeded `max_depth` |

## 8. Anti-Invariants (Forbidden Drift)

The following are forbidden:

1. Passing raw `State` JSON as `StateView` prompt context.
2. Embedding project-specific document/coding logic in core orchestration.
3. Bypassing `ProjectTypeAdapter` for project-type behavior.
4. Treating English narrative semantics as validator authority.
5. Treating exported files as canonical state.
6. Introducing competing runtime spines.
7. Exposing authoritative state internals directly to prompts outside `StateView` contract.
8. Framing CreateGame as "what should I do next?" rather than "what gap to NorthStar must I close?"
9. Mutating NorthStar through the automated pipeline without human approval.
10. Allowing decomposition to continue past `max_depth`.

## 9. Authority and Boundaries

Authority hierarchy:

1. Model outputs are proposals, not authoritative state.
2. Accepted integration is required before durable mutation.
3. Durable mutation occurs only through `StateService`.
4. Export materializes state to filesystem artifacts.
5. Export never defines authoritative state.
6. NorthStar proposals on the blackboard are not authority — they are proposals awaiting human review.

## 10. System Alignment Rules

Required alignment:

1. `State != StateView`
2. `core orchestration != adapter mechanics`
3. `export != authoritative state`
4. `prompt context == StateView` (bounded model-facing view)
5. `blackboard != authority`
6. `CreateGame == gap analysis toward NorthStar` (not step derivation)
7. `context_chain == full ancestor scope chain flowing into every leaf game`
