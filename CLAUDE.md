# CLAUDE.md — baps (bounded-adversarial-production)

This file orients Claude Code on the `baps` project. Read it before suggesting any changes.

---

## What this project is

`baps` is a bounded, adapter-driven runtime for model-mediated project evolution. A lifecycle run
initializes authoritative `State`, renders model-facing `StateView` projections, derives a bounded
`GameSpec`, runs an adversarial Blue/Red/Referee evaluation loop, integrates accepted deltas through
`StateService`, and exports output files.

---

## Canonical execution spine

```
config/NorthStar -> State -> StateView -> CreateGame -> GameSpec ->
PlayGame -> DeltaState -> StateService.apply_delta -> export
```

This is the **only** active product path. Do not propose changes that bypass or fork this spine.

---

## Repository layout

```
src/baps/
  core/
    run.py                  # CLI argument parsing and main()
    lifecycle.py            # start_project, reset_project, StartRunSummary, IterationRunResult
    runtime.py              # RuntimeContext, build_runtime, prepare_workspace, run_project, create_state
    run_config.py           # RunConfig, RoleConfig, resolve_run_config, resolve_reset_targets
    workspace.py            # Workspace I/O: settings, state path, run result, wipe
    orchestration.py        # _solve_gap, _run_project_iterations, _RunContext — recursive gap solver
    prompts.py              # All prompt rendering functions
    parsers.py              # All model output parsing functions
    clients.py              # All client-building functions, SpecRole, backend resolution
    debug.py                # Debug print helpers
  game/                     # Game execution package (split from core/game.py)
    engine.py               # create_game, play_game — top-level orchestration entry points
    attempt.py              # _run_play_game_attempt, _apply_play_game_attempt_decision, PlayAttemptRecord
    play.py                 # _record_play_game_telemetry
    roles.py                # _PlayGameContext, _resolve_play_game_roles, _build_play_game_fallbacks, role schemas
    telemetry.py            # Blackboard helpers, _VERIFICATION_SUMMARY_CAP, sanitize utilities
  adapters/
    project_adapter.py      # ProjectTypeAdapter protocol, registry, sanitizers, Blue prompt core
    document_adapter.py     # DocumentProjectAdapter — all document mechanics
    coding_adapter.py       # CodingProjectAdapter facade — delegates to coding/ subpackage
    audit_adapter.py        # AuditProjectAdapter — all audit mechanics, source fingerprinting
    coding/                 # CodingAdapter internals split by responsibility
      common.py             # Shared utilities: _validate_file_path, _plugin_for, _config_language, coding_artifact_from_state
      delta_apply.py        # _apply_delta_to_files, _normalize_coding_export_content
      parsing.py            # parse_coding_delta_json, validation, malformed-JSON recovery
      prompting.py          # render_coding_blue_prompt, _render_coding_evaluation_supplement
      views.py              # build_coding_create_game_state_view, build_coding_state_view
  state/
    state.py                # Authoritative schemas, mutation, artifact registry
    state_service.py        # StateService — the only mutation boundary
    state_store.py          # JsonStateStore — JSON persistence
  models/
    models.py               # AnthropicClient, OpenAIClient, OllamaClient, FakeModelClient, Role
    model_output.py         # Single model output parsing pipeline: fence-strip, JSON parse, key-strip, retry/fallback
  plugins/
    language_plugin.py      # LanguagePlugin protocol + get_language_plugin registry lookup
    language_python.py      # PythonLanguagePlugin — Python/pytest specifics
    language_zig.py         # ZigLanguagePlugin — Zig/build.zig specifics
  scheduler/
    scheduler.py            # Adaptive multi-model scheduler with policy learning
    scheduler_policy.py     # ModelPolicy, EMA scoring, softmax selection
  tools/
    tools.py                # fetch_url, web_search, ToolExecutor — research phase tools
    sandbox.py              # run_sandboxed — Docker/bare execution, SANDBOX_NONE_WARNING
  northstar/
    northstar_projection.py # StateView, ProjectionType, projection utilities
    northstar_apply.py      # baps-apply-northstar CLI — review and apply approved NorthStar proposals
  __init__.py

tests/
  conftest.py
  test_audit_adapter.py
  test_blackboard_game.py
  test_clients.py
  test_config.py
  test_create_game.py
  test_debug.py
  test_integration.py
  test_integration_adapters.py
  test_integration_candidate_verification.py
  test_integration_export.py
  test_integration_play_game.py
  test_integration_run.py
  test_integration_runtime.py
  test_language_plugin.py
  test_lifecycle.py
  test_model_output.py
  test_models.py
  test_northstar_apply.py
  test_northstar_projection.py
  test_orchestration.py
  test_parsers.py
  test_play_game.py
  test_play_game_attempts.py
  test_prompts.py
  test_run.py
  test_runconfig_migration_guard.py
  test_sandbox.py
  test_scheduler.py
  test_scheduler_policy.py
  test_state_delta.py
  test_state_mutation.py
  test_state_schema.py
  test_state_service.py
  test_state_store.py
  test_state_view.py
  test_tools.py

docs/
  SYSTEM.md       # Normative system contract
  ARCHITECTURE.md # Implementation description
```

---

## Core invariants — always preserve

1. **`State` is authoritative.** Persisted JSON via `JsonStateStore`. Never bypass `StateService`.
2. **`StateView` is a prompt-only projection.** It is not authority. It is never the same as `State`.
3. **JSON is storage/transport format.** Do not pass raw `State` JSON to model prompts as `StateView`.
4. **`NorthStar` is never mutated by the automated pipeline.** For document/coding adapters it lives as `northstar_markdown` in `baps-config.json`, outside `State` entirely. For the audit adapter it is stored inside `State` as a read-only meta artifact (`audit:meta:*`), but the pipeline is constrained to only target the configured findings artifact and never touches the meta artifact.
5. **`run.py` is generic.** All project-type mechanics belong in adapters.
6. **`ProjectTypeAdapter` owns:** initial state creation, CreateGame and PlayGame `StateView` rendering, full Blue prompt rendering (including delta-shape instructions), Red/Referee prompt supplements, Blue tool interface, delta parsing, export.
7. **`StateService` is the only mutation boundary.** The runtime integration path calls `StateService.apply_delta(delta_state)` directly.
8. **Export is one-way.** Exported files are derived materialization; they do not feed back as authority.
9. **Model prompts consume `StateView` only** — never raw `State` internals.
10. **Runtime loops are bounded** — `max_iterations` (outer), `max_attempts` (PlayGame, default 3).

---

## Forbidden patterns — do not suggest these

| Pattern | Why forbidden |
|---|---|
| Passing raw `State` JSON to a prompt | Violates State/StateView boundary |
| `run.py` inspecting `DocumentArtifact` or `CodingArtifact` | Project-specific leakage into core |
| `run.py` reading `sections` or `files` directly | Same — adapter-owned fields |
| `run.py` constructing project-specific `StateView`s | Must go through adapters |
| Bypassing `StateService` for state mutation | Breaks the mutation boundary |
| Output files feeding back as canonical state | Export is one-way |
| A new parallel execution engine alongside `run.py` | Forbidden dual-engine drift |
| Treating English-semantic parser output as authority | Validation must be contract-based |

### Active model output parsing pipeline

All model text output goes through `model_output.py:parse_model_output`. The pipeline:
1. Fence-strip and size-check (`_extract_json_candidate`, 64 KB cap)
2. Extract JSON from prose (first `{` to last `}`)
3. Parse JSON; detect and rescue ReAct/tool-calling wrappers
4. Strip keys not in the expected set; log and record unexpected keys
5. Retry with correction prompt on parse failure (via `retry_fn`)
6. Escalate to fallback model chain on retry exhaustion (via `fallback_fn`)

Do not add a second JSON parsing pipeline. All parsing must go through this path.

---

## Adapter contract

When working on adapters, they must implement:

1. `create_initial_state(...)` — initial `State`
2. `build_create_game_state_view(...)` — `StateView` for CreateGame
3. `render_create_game_prompt_supplement(...)` — project-specific CreateGame prompt rules
4. `normalize_game_spec(...)` — post-process `GameSpec` after CreateGame (e.g. fix artifact_id)
5. `build_state_view(...)` — `StateView` for PlayGame
6. `render_blue_prompt(...)` — full Blue prompt including delta-shape instructions
7. `render_red_prompt_supplement(...)` — project-specific Red prompt guidance
8. `render_referee_prompt_supplement(...)` — project-specific Referee prompt guidance
9. `build_blue_output_format()` — JSON schema or `None` for Blue's constrained output
10. `build_blue_tools()` — tool definitions for Blue's tool-call interface
11. `build_research_tools(role)` — tool definitions for research phases by role
12. `tool_call_to_delta(tool_call)` — convert Blue tool call to `DeltaState`
13. `parse_blue_delta(text)` — parse Blue JSON output into typed `DeltaState`
14. `export_state(...)` — write output files

Optional: `verify_export(...)`, `verify_candidate(...)`, `commit_export(...)`.

---

## Active delta operations

- `document`: `append_section`, `modify_section`, `delete_section`
- `coding`: `write_file`, `write_files` (preferred), `delete_file`
- `audit`: `append_section` (finding), `modify_section` (revise finding), `no_finding` (confirmed clean)

Do not add new delta operation types without updating both the schema (`state.py`) and the
relevant adapter's parse/map logic.

---

## Testing

Run all tests:
```bash
uv run pytest
```

### Testing philosophy

- Use `FakeModelClient` for deterministic sequences — never couple tests to live model output.
- Assert exact prompts, validation failures, stop reasons, and summary fields.
- Test adapter boundaries explicitly: core orchestration must not receive project-specific output.
- State schema tests in `test_state_schema.py`, mutation tests in `test_state_mutation.py`, delta tests in `test_state_delta.py`; orchestration contracts in `test_orchestration.py`; game phase tests in `test_create_game.py`, `test_play_game.py`, and `test_play_game_attempts.py`.
- Integration tests are split by domain: `test_integration_run.py`, `test_integration_runtime.py`, `test_integration_play_game.py`, `test_integration_export.py`, `test_integration_candidate_verification.py`, `test_integration_adapters.py`.

---

## Stop conditions

Implemented stop conditions to be aware of:
- `create_game_no_new_game` — only valid when no verification has run or last verification passed; rejected (retried) when verification is failing
- `play_game_no_delta` — escalates to `northstar_update_proposed` at depth 0
- `no_state_change` — escalates to `northstar_update_proposed` at depth 0
- `iteration_limit_reached`
- `max_depth_reached` — decomposition exceeded `max_depth` (default 3)
- `northstar_update_proposed` — CreateGame signalled trajectory drift, or gap identified but not closable; see NorthStar proposal flow below.

---

## NorthStar proposal flow (human-approval gate)

NorthStar is intentionally immutable through the automated pipeline. Updates require human approval.

### How proposals are generated

When CreateGame detects that the current project trajectory does not align with NorthStar intent, it
returns a third response shape instead of a `GameSpec` or `no_new_game`:

```json
{"northstar_update_needed": true, "rationale": "...", "proposed_northstar": "..."}
```

`orchestration.py` catches the resulting `NorthStarUpdateNeededError`, appends a JSONL event to
`<workspace>/blackboard/northstar_proposals.jsonl`, sets `stop_reason=northstar_update_proposed`,
and stops the iteration loop without touching `State`.

### Blackboard event schema

```json
{
  "event": "northstar_update_proposal",
  "rationale": "<why the model believes NorthStar should change>",
  "proposed_northstar": "<full replacement NorthStar content as a plain string>",
  "created_at": "<ISO 8601 UTC timestamp>"
}
```

The file is append-only. Multiple proposals accumulate across runs.

### Human approval

A human reviews `blackboard/northstar_proposals.jsonl`, decides whether to accept a proposal, and
manually updates the NorthStar source (e.g. the spec YAML's `northstar_markdown` field).
`baps-apply-northstar <workspace> [--index N] [--dry-run]` assists with applying an approved
proposal to `baps-config.json`.

### Why NorthStar cannot be mutated by the pipeline

For document/coding adapters, NorthStar is `northstar_markdown` in `baps-config.json` — completely
outside `State`. `StateService` only mutates `State`, so it structurally cannot reach it.

For the audit adapter, NorthStar is stored inside `State` as a `DocumentArtifact` with ID prefix
`audit:meta:`. The pipeline cannot mutate it in practice because `create_game` is constrained to
produce deltas that target only the configured findings artifact, not the meta artifact.

In both cases `baps-apply-northstar` is the only tool that updates NorthStar content, after human
review of a proposal.

---

## Blackboard status

Two blackboard files are active under `<workspace>/blackboard/`. Both are **append-only and non-authoritative** — they never feed back into `State`. Do not read blackboard files as input to model prompts or state mutations.

- **`northstar_proposals.jsonl`** — written when CreateGame signals trajectory drift or when the outer loop cannot close an identified gap; contains `northstar_update_proposal` events.
- **`games.jsonl`** — written by every `create_game`, `play_game`, and integration step; contains `create_game`, `play_game`, and `integration` events forming a complete audit trail of each run.

---

## Contributor discipline

- Make changes within the existing boundary: `run.py` = generic orchestration, adapters = project mechanics.
- Schema-driven changes belong in `state.py` and adapter mapping logic.
- Prefer additive changes. Avoid bypassing `StateService` or adapter dispatch.
- Do not introduce a new execution engine alongside `run.py`.
- When adding a new project type: register a new adapter — do not add conditionals to `run.py`.

---

## Coding rules — enforce in every session

**No string literals as identifiers.** Roles, backends, stop reasons, event types, projection types, and blackboard events must use the defined enums or named constants (`SpecRole`, `Backend`, `StopReason`, `BlackboardEvent`, `ProjectionType`, `STATE_VIEW_START`/`STATE_VIEW_END`). If a new identifier is needed, add it to the appropriate enum first, then use the enum member.

**No silent defaults.** Required configuration must be explicit. Never fall back to a hardcoded model, backend, or path without raising a clear error. If something is unconfigured, raise `ValueError`.

**One parsing pipeline.** All model output goes through `model_output.py:parse_model_output`. Never add an ad-hoc JSON parser elsewhere.

**One mutation boundary.** All state changes go through `StateService`. Never mutate `State` directly.

**Adapters own project-specific logic.** Never add document-, coding-, or audit-specific logic to `run.py`. If it touches artifact fields or delta types, it belongs in an adapter.

**Tests must verify content.** Assertions like `isinstance(result, State)` or `len(calls) == 2` without content verification are not acceptable. Assert specific field values.

**Do not add logic to `run.py`.** `run.py` contains only CLI argument parsing and `main()`. Lifecycle orchestration belongs in `lifecycle.py`. Runtime assembly (workspace init, adapter resolution, state service wiring) belongs in `runtime.py`. Config resolution belongs in `run_config.py`. Workspace I/O belongs in `workspace.py`. Orchestration logic belongs in `orchestration.py`. Prompt rendering belongs in `prompts.py`. Output parsing belongs in `parsers.py`. Client-building belongs in `clients.py`.

**Game execution logic belongs in `game/`.** `create_game` and `play_game` entry points live in `game/engine.py`. Attempt logic → `game/attempt.py`. Role wiring → `game/roles.py`. Telemetry and blackboard writes → `game/telemetry.py`. Do not add game-execution logic to `core/`.

---

## Suggested next milestones (from ARCHITECTURE.md)

These are additive and preserve the canonical spine:

1. ~~Blackboard reintegration as append-only run metadata (non-authoritative)~~ — done
2. ~~Human-facing `baps-apply-northstar <workspace>` command~~ — done
3. ~~Formal tool boundary for controlled execution beyond prompt-only roles~~ — done (`build_blue_tools`, `tool_call_to_delta` on `ProjectTypeAdapter`; coding adapter exposes `write_files`, `write_file`, `delete_file` tools)
4. Adapter-level verification hook expansion (beyond coding pytest)
5. Stronger contract tests around role outputs vs `success_condition` semantics
6. Optional structured role envelopes for richer machine-checkable rationale
