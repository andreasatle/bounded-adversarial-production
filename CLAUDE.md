# CLAUDE.md — baps (bounded-adversarial-production)

This file orients Claude Code on the `baps` project. Read it before suggesting any changes.

---

## Session Setup

At the start of every session and after every /clear, run:

    uv run python scripts/index_codebase.py

This regenerates `CODEBASE_API_INDEX.md` and `CODEBASE_TEST_INDEX.md`.
Read `CODEBASE_API_INDEX.md` before doing anything else.
Use it as the primary architectural reference for the current codebase.
Consult source files only after locating the relevant entities in the index.
Read `CODEBASE_TEST_INDEX.md` when working on tests, verification, coverage, regressions, or test architecture.

---

## What this project is

`baps` is a bounded, adapter-driven runtime for model-mediated project evolution. A lifecycle run initializes authoritative `State`, renders model-facing `StateView` projections, derives a bounded `GameSpec`, runs an adversarial Blue/Red/Referee evaluation loop, integrates accepted deltas through `StateService`, and exports output files.

---

## Canonical execution spine

```
config/NorthStar -> State -> StateView -> CreateGame -> GameSpec ->
PlayGame -> DeltaState -> StateService.apply_delta -> export
```

This is the **only** active product path. Do not propose changes that bypass or fork this spine.

---

## Core invariants — always preserve

1. **`State` is authoritative.** Persisted JSON via `JsonStateStore`. Never bypass `StateService`.
2. **`StateView` is a prompt-only projection.** It is not authority. It is never the same as `State`.
3. **JSON is storage/transport format.** Do not pass raw `State` JSON to model prompts as `StateView`.
4. **`NorthStar` is never mutated by the automated pipeline.** For document/coding adapters it lives as `northstar_markdown` in `baps-config.json`, outside `State` entirely. For the audit adapter it is stored inside `State` as a read-only meta artifact (`audit:meta:*`).
5. **`run.py` is generic.** All project-type mechanics belong in adapters.
6. **`ProjectTypeAdapter` owns:** initial state creation, CreateGame and PlayGame `StateView` rendering, full Blue prompt rendering, Red/Referee prompt supplements, Blue tool interface, delta parsing, export.
7. **`StateService` is the only mutation boundary.** Runtime integration calls `StateService.apply_delta(delta_state)` directly.
8. **Export is one-way.** Exported files are derived materialization; they do not feed back as authority.
9. **Model prompts consume `StateView` only** — never raw `State` internals.
10. **Runtime loops are bounded** — `max_iterations` (outer), `max_attempts` (PlayGame, default 3).

---

## Forbidden patterns

| Pattern | Why forbidden |
|---|---|
| Passing raw `State` JSON to a prompt | Violates State/StateView boundary |
| `run.py` inspecting `DocumentArtifact` or `CodingArtifact` | Project-specific leakage into core |
| `run.py` constructing project-specific `StateView`s | Must go through adapters |
| Bypassing `StateService` for state mutation | Breaks the mutation boundary |
| Output files feeding back as canonical state | Export is one-way |
| A new parallel execution engine alongside `run.py` | Forbidden dual-engine drift |
| Treating English-semantic parser output as authority | Validation must be contract-based |
| Ad-hoc JSON parsing outside `model_output.py` | One parsing pipeline only |

---

## Model output parsing pipeline

All model text output goes through `model_output.py:parse_model_output`:

1. Fence-strip and size-check (64 KB cap)
2. Extract JSON from prose
3. Parse JSON; rescue ReAct/tool-calling wrappers
4. Strip unexpected keys; log and record them
5. Retry with correction prompt on parse failure
6. Escalate to fallback model chain on retry exhaustion

Do not add a second JSON parsing pipeline.

---

## Adapter contract

Adapters must implement:

- `create_initial_state(...)` — initial `State`
- `build_create_game_state_view(...)` — `StateView` for CreateGame
- `render_create_game_prompt_supplement(...)` — project-specific CreateGame prompt rules
- `normalize_game_spec(...)` — post-process `GameSpec` after CreateGame
- `build_state_view(...)` — `StateView` for PlayGame
- `render_blue_prompt(...)` — full Blue prompt including delta-shape instructions
- `render_red_prompt_supplement(...)` — project-specific Red prompt guidance
- `render_referee_prompt_supplement(...)` — project-specific Referee prompt guidance
- `build_blue_output_format()` — JSON schema or `None`
- `build_blue_tools()` — tool definitions for Blue's tool-call interface
- `build_research_tools(role)` — tool definitions for research phases
- `tool_call_to_delta(tool_call)` — convert Blue tool call to `DeltaState`
- `parse_blue_delta(text)` — parse Blue JSON output into typed `DeltaState`
- `export_state(...)` — write output files

Optional: `verify_export(...)`, `verify_candidate(...)`, `commit_export(...)`.

---

## Active delta operations

- `document`: `append_section`, `modify_section`, `delete_section`
- `coding`: `write_file`, `write_files` (preferred), `delete_file`
- `audit`: `append_section`, `modify_section`, `no_finding`

Do not add new delta operation types without updating `state.py` and the relevant adapter.

---

## Stop conditions

- `create_game_no_new_game` — only valid when no verification has run or last verification passed
- `play_game_no_delta` — escalates to `northstar_update_proposed` at depth 0
- `no_state_change` — escalates to `northstar_update_proposed` at depth 0
- `iteration_limit_reached`
- `max_depth_reached` — decomposition exceeded `max_depth` (default 3)
- `northstar_update_proposed` — trajectory drift detected; requires human approval via `baps-apply-northstar`

---

## NorthStar

NorthStar is immutable through the automated pipeline. When CreateGame detects trajectory drift it returns a proposal instead of a `GameSpec`. The proposal is written to `blackboard/northstar_proposals.jsonl` and the run stops. A human reviews and applies approved proposals using `baps-apply-northstar <workspace>`. See `SYSTEM.md` for the full proposal flow.

---

## Blackboard

Two append-only files under `<workspace>/blackboard/`. Never feed back into `State` or model prompts.

- `northstar_proposals.jsonl` — NorthStar update proposals
- `games.jsonl` — full audit trail: `create_game`, `play_game`, and integration events

---

## Testing

Run all tests: `uv run pytest`

- Use `FakeModelClient` for deterministic sequences — never couple tests to live model output.
- Assert exact prompts, validation failures, stop reasons, and summary fields.
- Test adapter boundaries explicitly: core orchestration must not receive project-specific output.

Test file ownership:

| File | Domain |
|---|---|
| `test_state_schema.py` | State schemas |
| `test_state_mutation.py` | State mutation |
| `test_state_delta.py` | Delta operations |
| `test_state_service.py` | StateService boundary |
| `test_orchestration.py` | Orchestration contracts |
| `test_create_game.py` | CreateGame phase |
| `test_play_game.py` | PlayGame phase |
| `test_play_game_attempts.py` | PlayGame attempt logic |
| `test_integration_run.py` | Full run integration |
| `test_integration_runtime.py` | Runtime assembly |
| `test_integration_play_game.py` | PlayGame integration |
| `test_integration_export.py` | Export integration |
| `test_integration_candidate_verification.py` | Candidate verification |
| `test_integration_adapters.py` | Adapter integration |

---

## Coding rules — enforce in every session

- **No string literals as identifiers.** Use defined enums: `SpecRole`, `Backend`, `StopReason`, `BlackboardEvent`, `ProjectionType`. Add to the enum first, then use the member.
- **No silent defaults.** Required configuration must be explicit. Raise `ValueError` if something is unconfigured.
- **One parsing pipeline.** All model output goes through `model_output.py:parse_model_output`.
- **One mutation boundary.** All state changes go through `StateService`.
- **Adapters own project-specific logic.** Never add document-, coding-, or audit-specific logic to `run.py`.
- **Tests must verify content.** Assert specific field values — not just `isinstance` or call counts.
- **Keep files small.** No file should exceed 300 lines. If a file is approaching this limit, split it into focused modules before adding more logic. The `game/` package split is the model to follow.
- **Module responsibilities are fixed:**

  | Module | Responsibility |
  |---|---|
  | `run.py` | CLI and `main()` only |
  | `lifecycle.py` | lifecycle orchestration |
  | `runtime.py` | runtime assembly |
  | `run_config.py` | config resolution |
  | `workspace.py` | workspace I/O |
  | `orchestration.py` | gap solving |
  | `prompts.py` | prompt rendering |
  | `parsers.py` | output parsing |
  | `clients.py` | client building |
  | `game/engine.py` | `create_game`, `play_game` entry points |
  | `game/attempt.py` | attempt logic |
  | `game/roles.py` | role wiring |
  | `game/telemetry.py` | blackboard writes |
