# Purpose

`ARCHITECTURE.md` records implementation evidence.

`SYSTEM.md` defines the normative contract: required operational semantics, boundaries, invariants, and forbidden drift for the active runtime.

This document is prescriptive about what must remain true.

## 1. Canonical Spine

```
config/NorthStar → State → StateView → CreateGame
                                           ↓
                                    DecomposeSpec? ──→ recursive sub-gaps (up to max_depth)
                                           ↓
                                   GameSpec (context_chain)
                                           ↓
                                       PlayGame
                                     [research phase]
                                           ↓
                               DeltaState → StateUpdateProposal → StateService → export
```

This is the only active lifecycle execution path for `start`. No other lifecycle is canonical.

`reset` is not a lifecycle path — it wipes workspace state and output then exits immediately. No model calls, no game loop.

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
9. CreateGame is `State`/`NorthStar`-aware through `StateView`. It performs gap analysis, not step derivation.
10. PlayGame is `GameSpec`-bound. It has no access to `NorthStar` directly.
11. `GameSpec.context_chain` carries all ancestor gap descriptions from the coarsest decomposition to the immediate task. Blue sees the full chain.
12. `StateService` is the mutation boundary for durable state changes.
13. `StateService` rejects proposals targeting NorthStar artifacts.
14. Export is one-way materialization from `State` to output files.
15. Prompts consume `StateView` context, not raw authoritative `State` internals.
16. Model-generated content is sanitized (NFKC-normalized, injection patterns removed) before embedding in any subsequent prompt.
17. Delta payload models reject extra fields (`extra="forbid"`); unexpected model output fields cause validation failure rather than silent discard.
18. Model response size is bounded before JSON deserialization (64 KB cap enforced by `_extract_json_candidate` in `model_output.py`).
19. Decomposition branching is bounded by `max_sub_gaps` (config key, default 5); a `DecomposeSpec` with more sub-gaps is truncated to the first `max_sub_gaps` entries before execution.
20. Model-generated code executes inside a Docker container during verification via `sandbox.run_sandboxed(cwd, mode, test_command, docker_image)`; the container image and test command are owned by the language plugin; `sandbox=none` is an explicit opt-in that emits a runtime warning and must not be used in production.

## 3. Adapter Contract

`ProjectTypeAdapter` owns project-specific mechanics:

1. Initial state creation
2. CreateGame `StateView` rendering
3. PlayGame `StateView` rendering
4. Project prompt supplements (CreateGame, Blue, Red, Referee)
5. Blue delta parsing
6. Delta → `StateUpdateProposal` mapping
7. Export
8. Optional export verification
9. Language plugin resolution (coding adapter only): the `language` spec key selects a `LanguagePlugin` at state-creation time; the plugin owns `docker_image`, `test_command`, `initialize`, `run_tests`, `has_tests`, and `parse_test_failures`; unknown language names raise immediately with the list of available languages; adding a new language requires implementing `LanguagePlugin` and registering it — `sandbox.py` requires no changes

Core orchestration must call adapter interfaces and remain generic.

## 4. Active Project Types

Active registered project types in canonical runtime:

- `document` — section-based document evolution (`append_section`, `modify_section`, `delete_section`)
- `coding` — file-based codebase evolution (`write_file`, `write_files`, `delete_file`); language-agnostic via plugin registry
- `audit` — adversarial source code audit producing a structured findings report (`append_section`, `no_finding`)

All three participate through the same adapter contract and orchestration path.

### Coding language plugins

The coding adapter delegates language-specific behavior to a `LanguagePlugin`. The `language` key is required in every coding spec; omitting it raises an error listing available languages. Built-in plugins:

- `python` — `python:3.12-slim` image, `pip install pytest -q && python -m pytest`; scaffolds `conftest.py` + `.gitignore`
- `zig` — `baps-zig:latest` image (build locally: `docker build -t baps-zig:latest docker/zig/`), `zig build test`; scaffolds `build.zig` + `src/main.zig` + `.gitignore`

The language is stored on `CodingArtifact.language` at creation time and persists in authoritative state. All subsequent operations (verification, candidate testing) read language from the artifact, not from config.

### Audit-specific invariants

- Each audit section stores a `source_hash` (SHA-256 of source files at write time).
- On subsequent runs, sections whose `source_hash` differs from the current source are marked `[STALE — source changed]` in the CreateGame `StateView`.
- `source_hash` is audit-only; document and coding adapters never set it.

## 5. Multiscale Decomposition Contract

When CreateGame returns a `DecomposeSpec`:

- `_solve_gap` recursively solves each `SubGapSpec` at `depth + 1`
- The current gap's description is prepended to `context_chain` before each recursive call
- Recursion is bounded by `max_depth` (config key, default 3)
- Sub-gaps are executed sequentially; each leaf applies its delta to state before the next sub-gap begins
- A `play_game_no_delta` result at a leaf clears between sibling sub-gaps and does not abort them; only real stop conditions propagate up
- `NoNewGameError` at depth > 0 means the sub-gap is satisfied; only at depth 0 does it stop the run
- Only leaf `PlayGame` executions count against `max_iterations`
- `max_depth_reached` is a valid stop reason when decomposition exceeds the depth limit
- The outer iteration loop re-invokes CreateGame at depth 0 after all sub-gaps complete; the project is not assumed complete after one decomposition pass

## 6. Role Model

PlayGame involves three roles, each optionally preceded by a research phase:

- **Blue** — proposes a candidate `DeltaState`
- **Red** — adversarially reviews the candidate against `GameSpec`
- **Referee** — adjudicates and decides accept/revise/reject

Each role may use a different model backend/model via environment variables (`BAPS_{ROLE}_BACKEND`, `BAPS_{ROLE}_MODEL`). The **DECOMPOSE** role handles CreateGame calls at decomposition nodes (`depth > 0`) and may be assigned a lighter model than the leaf-execution roles.

Each role may optionally declare a `fallback` block in the spec. Fallback chains can be arbitrarily deep: a `fallback` block may itself contain a `fallback`, and so on. The chain is traversed in order after the primary model exhausts all JSON-correction retries — each link is tried exactly once. Escalation occurs only for roles with an explicit fallback declared in the spec; no implicit escalation. A WARNING is logged at each escalation step with the source and target model names. If the entire chain is exhausted without producing valid output, the run raises `RuntimeError("<role>: all models in fallback chain exhausted")`.

Research phases (agentic tool use before role output) are optional and adapter-controlled. Tool call logs are passed between roles for transparency.

## 7. NorthStar Proposal Flow

When CreateGame signals trajectory drift:

- Returns `{"northstar_update_needed": true, "rationale": "...", "proposed_northstar": "..."}`
- Runtime sanitizes and appends a JSONL event to `<workspace>/blackboard/northstar_proposals.jsonl`
- Stop reason is set to `northstar_update_proposed`
- No state is mutated
- Human reviews proposals and manually updates the NorthStar source
- `baps-apply-northstar <workspace>` assists with applying an approved proposal

Blackboard is append-only and non-authoritative. It never feeds back into `State`.

## 8. Stop Conditions

| Stop reason | Meaning |
|---|---|
| `iteration_limit_reached` | `max_iterations` leaf games executed |
| `create_game_no_new_game` | No gap remains at depth 0; only valid when no verification has run or last verification passed |
| `play_game_no_delta` | PlayGame produced no accepted delta; at depth 0, escalates to `northstar_update_proposed` |
| `no_state_change` | Accepted delta produced no state change; at depth 0, escalates to `northstar_update_proposed` |
| `northstar_update_proposed` | Trajectory drift, or gap was identified but could not be closed; human approval needed |
| `max_depth_reached` | Decomposition exceeded `max_depth` |

`play_game_no_delta` and `no_state_change` are internal conditions. At depth 0, `_run_project_iterations` converts them to `northstar_update_proposed` and appends a blackboard proposal explaining the stuck condition so the human is alerted through the standard NorthStar approval channel rather than receiving a silent stop.

`create_game_no_new_game` is only a valid terminal stop when verification has not run (non-coding project) or the last verification passed (`verification_passed=True`). If the last verification failed, `no_new_game` is treated as a model error — the runtime refuses to stop, passes the failing verification as context to the next CreateGame call, and retries. If the retry also returns `no_new_game` with failing verification, the runtime escalates to `northstar_update_proposed` so the human is alerted.

## 9. Anti-Invariants (Forbidden Drift)

1. Passing raw `State` JSON as `StateView` prompt context.
2. Embedding project-specific document/coding/audit logic in core orchestration.
3. Bypassing `ProjectTypeAdapter` for project-type behavior.
4. Treating English narrative semantics as validator authority.
5. Treating exported files as canonical state.
6. Introducing competing runtime spines.
7. Exposing authoritative state internals directly to prompts outside `StateView` contract.
8. Framing CreateGame as "what should I do next?" rather than "what gap to NorthStar must I close?".
9. Mutating NorthStar through the automated pipeline without human approval.
10. Allowing decomposition to continue past `max_depth`.
11. Allowing a single `DecomposeSpec` to contain more than `max_sub_gaps` sub-gaps (default 5); excess entries are silently truncated before execution.
12. Embedding model-generated content in prompts without sanitization.
13. Treating a completed decomposition pass as project completion without re-running CreateGame.
14. Running model-generated code unsandboxed without explicit `sandbox=none` opt-in and warning.
15. Silently halting when a gap was identified but could not be closed (`play_game_no_delta` or `no_state_change` at depth 0); the runtime must escalate to `northstar_update_proposed` and write a blackboard proposal.
16. Resolving the language plugin from config at verification time; the language is set once at `create_initial_state` and persists in `CodingArtifact.language` — all operations read it from the artifact.
17. Accepting `create_game_no_new_game` as a stop condition when the last verification failed; failing tests are evidence of an open gap and must not be silently ignored.

## 10. Authority and Boundaries

1. Model outputs are proposals, not authoritative state.
2. Accepted integration is required before durable mutation.
3. Durable mutation occurs only through `StateService`.
4. Export materializes state to filesystem artifacts.
5. Export never defines authoritative state.
6. NorthStar proposals on the blackboard are not authority — they are proposals awaiting human review.

## 11. System Alignment Rules

1. `State != StateView`
2. `core orchestration != adapter mechanics`
3. `export != authoritative state`
4. `prompt context == StateView` (bounded, sanitized, model-facing view)
5. `blackboard != authority`
6. `CreateGame == gap analysis toward NorthStar` (not step derivation)
7. `context_chain == full ancestor scope chain flowing into every leaf game`
8. `one decomposition pass != project complete` (outer loop re-assesses)
9. `artifact.language == source of truth for plugin selection` (not runtime config)
