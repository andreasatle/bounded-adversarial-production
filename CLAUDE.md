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
PlayGame -> DeltaState -> StateUpdateProposal -> StateService -> export
```

This is the **only** active product path. Do not propose changes that bypass or fork this spine.

---

## Repository layout

```
src/baps/
  run.py                  # Generic lifecycle orchestration ONLY — no project-specific logic
  project_adapter.py      # ProjectTypeAdapter protocol, registry, sanitizers, Blue prompt core
  document_adapter.py     # DocumentProjectAdapter — all document mechanics
  coding_adapter.py       # CodingProjectAdapter — all coding mechanics (language-agnostic)
  audit_adapter.py        # AuditProjectAdapter — all audit mechanics, source fingerprinting
  language_plugin.py      # LanguagePlugin protocol + get_language_plugin registry lookup
  language_python.py      # PythonLanguagePlugin — Python/pytest specifics
  language_zig.py         # ZigLanguagePlugin — Zig/build.zig specifics
  state.py                # Authoritative schemas, mutation, artifact registry
  state_service.py        # StateService — the only mutation boundary
  state_store.py          # JsonStateStore — JSON persistence
  model_output.py         # Single model output parsing pipeline: fence-strip, JSON parse, key-strip, retry/fallback
  models.py               # AnthropicClient, OpenAIClient, OllamaClient, FakeModelClient, Role
  northstar_projection.py # StateView, ProjectionType, projection utilities
  northstar_apply.py      # baps-apply-northstar CLI — review and apply approved NorthStar proposals
  sandbox.py              # run_sandboxed — Docker/bare execution, SANDBOX_NONE_WARNING
  tools.py                # fetch_url, web_search, ToolExecutor — research phase tools
  scheduler.py            # Adaptive multi-model scheduler with policy learning
  scheduler_policy.py     # ModelPolicy, EMA scoring, softmax selection

tests/
  test_state.py
  test_state_service.py
  test_state_store.py
  test_northstar_projection.py
  test_model_output.py
  test_models.py
  test_run.py
  test_audit_adapter.py
  test_language_plugin.py
  test_northstar_apply.py
  test_sandbox.py
  test_tools.py
  test_scheduler.py
  test_scheduler_policy.py

docs/
  SYSTEM.md       # Normative system contract
  ARCHITECTURE.md # Implementation description
```

---

## Core invariants — always preserve

1. **`State` is authoritative.** Persisted JSON via `JsonStateStore`. Never bypass `StateService`.
2. **`StateView` is a prompt-only projection.** It is not authority. It is never the same as `State`.
3. **JSON is storage/transport format.** Do not pass raw `State` JSON to model prompts as `StateView`.
4. **`NorthStar` is part of `State`.** Artifact IDs must remain disjoint from state artifact IDs.
5. **`run.py` is generic.** All project-type mechanics belong in adapters.
6. **`ProjectTypeAdapter` owns:** initial state creation, StateView rendering (CreateGame + PlayGame),
   Blue prompt supplement, delta parsing, delta→StateUpdateProposal mapping, export.
7. **`StateService` is the only mutation boundary.** Call `StateService.apply_update(...)`.
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
3. `build_play_game_state_view(...)` — `StateView` for PlayGame
4. `render_blue_prompt_supplement(...)` — project-specific Blue prompt rules
5. `parse_blue_delta(...)` — parse model output into typed `DeltaState`
6. `map_delta_to_proposal(...)` — `DeltaState` → `StateUpdateProposal`
7. `export_state(...)` — write output files

Optional: `verify_export(...)`, `normalize_game_spec(...)`, supplements for CreateGame/Red/Referee.

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
- Schema mutation tests live in `test_state.py`; orchestration contracts in `test_run.py`.

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

`run.py` catches the resulting `NorthStarUpdateNeededError`, appends a JSONL event to
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

### Enforcement in StateService

`StateService.apply_update` rejects any proposal whose `target.artifact_id` matches a NorthStar
artifact ID, raising `ValueError("... human approval is required to update NorthStar")`. This
guard is independent of the CreateGame signal and applies to all automated update paths.

---

## Blackboard status

`<workspace>/blackboard/northstar_proposals.jsonl` is active and written by the canonical spine
when CreateGame signals trajectory drift. It is **append-only and non-authoritative** — it does
not feed back into `State`. Do not read blackboard files as input to model prompts or state
mutations.

---

## Contributor discipline

- Make changes within the existing boundary: `run.py` = generic orchestration, adapters = project mechanics.
- Schema-driven changes belong in `state.py` and adapter mapping logic.
- Prefer additive changes. Avoid bypassing `StateService` or adapter dispatch.
- Do not introduce a new execution engine alongside `run.py`.
- When adding a new project type: register a new adapter — do not add conditionals to `run.py`.

---

## Suggested next milestones (from ARCHITECTURE.md)

These are additive and preserve the canonical spine:

1. ~~Blackboard reintegration as append-only run metadata (non-authoritative)~~ — done
2. ~~Human-facing `baps-apply-northstar <workspace>` command~~ — done
3. Formal tool boundary for controlled execution beyond prompt-only roles
4. Adapter-level verification hook expansion (beyond coding pytest)
5. Stronger contract tests around role outputs vs `success_condition` semantics
6. Optional structured role envelopes for richer machine-checkable rationale
