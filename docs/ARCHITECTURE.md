# ARCHITECTURE.md

This document records the **actual implemented architecture** of `bounded-adversarial-production` (`baps`), aligned with [SYSTEM.md](SYSTEM.md).

Canonical runtime spine:

```
config/NorthStar → State → StateView → CreateGame
                                           ↓
                                    DecomposeSpec? ──→ recursive sub-gaps
                                           ↓
                                   GameSpec (context_chain)
                                           ↓
                                       PlayGame
                                           ↓
                               DeltaState → StateUpdateProposal → StateService → export
```

---

## 1. Project Overview

`baps` is an adapter-driven, multiscale runtime for bounded, iterative project evolution over authoritative `State`. NorthStar defines the target; CreateGame identifies gaps; recursive decomposition breaks large gaps into coherent sub-games; PlayGame closes leaf gaps through adversarial evaluation.

Current execution behavior:

1. Read config (NorthStar content, runtime controls, model config).
2. Create or load authoritative `State`.
3. Loop until stop condition:
   a. Call `_solve_gap(context_chain=(), depth=0)` which:
      - Builds adapter-owned `StateView`
      - Calls `CreateGame` (gap analysis against NorthStar)
      - If `DecomposeSpec`: recurse into each sub-gap with extended `context_chain`
      - If `GameSpec`: inject `context_chain`, run `PlayGame`, integrate delta, export
   b. Stop when `iterations_remaining == 0` or a stop condition is raised
4. Write run result JSON to workspace.

Current implementation philosophy:

- `State` is authority; `StateView` is model-facing projection.
- CreateGame is gap analysis, not step derivation.
- Decomposition is recursive and multiscale; context flows down the full chain.
- Core orchestration is generic; project-specific behavior is adapter-owned.
- Runtime is bounded by `max_iterations` (leaf games) and `max_depth` (decomposition levels).

---

## 2. System Capabilities

### Schemas (`src/baps/state.py`)

**Core state:**

- `State`, `NorthStar`, `StateArtifact`
- `DocumentArtifact` (sections), `CodingArtifact` (files)
- `Section`, `CodeFile`

**Game contracts:**

- `GameSpec` — `objective`, `target_artifact_id`, `allowed_delta_type`, `success_condition`, `context_chain`
- `SubGapSpec` — `description` (a gap to be recursively planned)
- `DecomposeSpec` — `rationale`, `sub_gaps` (CreateGame decomposition response)

**Document deltas:**

- `DeltaDocumentState` (`append_section`) — add a new section
- `DeltaModifyDocumentState` (`modify_section`) — rewrite an existing section
- `DeltaDeleteDocumentState` (`delete_section`) — remove a section

**Coding deltas:**

- `DeltaCodingState` (`write_file`) — write a single file
- `DeltaCodingBatchState` (`write_files`) — write multiple files in one game
- `DeltaDeleteCodingState` (`delete_file`) — remove a file

**Adversarial evaluation:**

- `RedFinding` — adversarial reviewer output
- `RefereeDecision` — adjudication output
- `PlayGameRuntime` — attempt tracking

**Integration:**

- `StateUpdateProposal`, `StateUpdateTarget`

---

### Runtime (`src/baps/run.py`)

**Lifecycle commands:** `init`, `run`, `init_and_run`

**Key functions:**

- `create_game(...)` — gap-analysis prompt, parsing (`GameSpec | DecomposeSpec`), validation, adapter normalization
- `play_game(...)` — Blue/Red/Referee orchestration with bounded retries
- `_solve_gap(context_chain, ctx, ..., depth)` — recursive gap solver; accumulates context chain; counts only leaf executions against `max_iterations`
- `_run_project_iterations(...)` — outer loop calling `_solve_gap` at depth 0 until stop

**`_RunContext`:** Mutable dataclass threaded through recursion tracking current state, remaining iterations, verification result, and stop reason.

**Per-role model selection:**

Each role can use a different model backend/model:

```bash
BAPS_{ROLE}_BACKEND=anthropic|openai|ollama
BAPS_{ROLE}_MODEL=<model-id>
```

Roles: `BLUE`, `RED`, `REFEREE`, `CREATE_GAME`. Falls back to global `BAPS_BACKEND` / `BAPS_*_MODEL`.

**Stop conditions:**

| Stop reason | Trigger |
|---|---|
| `iteration_limit_reached` | `max_iterations` leaf games consumed |
| `create_game_no_new_game` | No gap at depth 0 |
| `play_game_no_delta` | PlayGame returned no accepted delta |
| `no_state_change` | Delta produced no state change |
| `northstar_update_proposed` | CreateGame signalled trajectory drift |
| `max_depth_reached` | Decomposition exceeded `max_depth` |

---

### Adapters

#### Document (`src/baps/document_adapter.py`)

- Section-based document state
- CreateGame StateView: renders NorthStar + current sections
- Delta operations: `append_section`, `modify_section`, `delete_section`
- Export: markdown file
- Verification: structural consistency check

#### Coding (`src/baps/coding_adapter.py`)

- File-based codebase state
- CreateGame StateView: renders NorthStar + existing file contents (first 30 lines, truncated with count)
- Delta operations: `write_file`, `write_files` (preferred), `delete_file`
- Export: file tree + root `conftest.py`
- Verification: `pytest` execution; result evidence feeds next CreateGame

Both adapters expose tools for Blue's tool-call interface in addition to JSON output.

---

### StateView (`src/baps/northstar_projection.py`)

- `StateView`: `id`, `projection_type`, `content`, `input_fingerprint`, `metadata`
- Content uses explicit delimiters (`=== StateView Start/End ===`)
- Built by adapters for CreateGame and PlayGame contexts
- Never passed as raw JSON to prompts

---

### Model Layer (`src/baps/models.py`)

Active backends:

- `AnthropicClient` — Anthropic API (Claude models)
- `OpenAIClient` — OpenAI API (GPT models)
- `OllamaClient` — local Ollama server
- `FakeModelClient` — deterministic test double with queued responses and prompt capture

`Role` wraps a client with name, output schema, and constrained-decoding flag.

---

### Adaptive Scheduler (`src/baps/scheduler.py`)

Runs specs repeatedly across a model ladder with policy-guided selection:

- EMA reward scoring: `score = 0.7 * score + 0.3 * reward`
- Softmax model selection with temperature decay
- Automatic escalation to stronger model on low reward
- Underperformer dropping: models below score floor after min runs are removed
- Multi-round support with ladder reload between rounds
- Configurable via `BAPS_MODEL_LADDER` (comma-separated model names)

---

### NorthStar Apply CLI (`src/baps/northstar_apply.py`)

Reviews and applies approved NorthStar proposals from the blackboard:

```bash
baps-apply-northstar <workspace> [--index N] [--dry-run]
```

Reads `<workspace>/blackboard/northstar_proposals.jsonl`, lists proposals interactively, writes accepted `proposed_northstar` to `baps-config.json`.

---

## 3. Repository Structure

```
src/baps/
  run.py                  # Generic lifecycle orchestration, recursive gap solver
  project_adapter.py      # ProjectTypeAdapter protocol, registry, Blue prompt core
  document_adapter.py     # DocumentProjectAdapter — all document mechanics
  coding_adapter.py       # CodingProjectAdapter — all coding mechanics
  state.py                # Authoritative schemas, mutation, delta application
  state_service.py        # StateService — the only mutation boundary
  state_store.py          # JsonStateStore — JSON persistence
  models.py               # ModelClient, backends, FakeModelClient, Role
  northstar_projection.py # StateView, ProjectionType, projection utilities
  scheduler.py            # Adaptive multi-model scheduler with policy learning
  scheduler_policy.py     # ModelPolicy, EMA scoring, softmax selection
  northstar_apply.py      # baps-apply-northstar CLI

tests/
  test_state.py
  test_state_service.py
  test_state_store.py
  test_northstar_projection.py
  test_models.py
  test_run.py

docs/
  SYSTEM.md               # Normative system contract
  ARCHITECTURE.md         # Implementation description (this file)
```

---

## 4. Canonical Runtime Flow

### Lifecycle commands

- `init` — resolve config, validate workspace, create initial State, persist
- `run` — load persisted state, run bounded iterations
- `init_and_run` — initialize then immediately run

### Iteration flow (inside `_solve_gap`)

1. **CreateGame** — gap analysis
   - Adapter builds CreateGame `StateView` (includes file contents for coding)
   - Core renders gap-analysis prompt with optional `context_chain` from parent levels
   - Model returns `GameSpec`, `DecomposeSpec`, `no_new_game`, or `northstar_update_needed`
   - If `DecomposeSpec`: recurse for each sub-gap with extended context chain

2. **PlayGame** — adversarial execution (leaf games only)
   - Adapter builds PlayGame `StateView`
   - Blue prompt includes full `context_chain` from all ancestor levels
   - Blue produces candidate `DeltaState` (JSON or tool call)
   - Red evaluates against `GameSpec`
   - Referee decides accept/revise/reject
   - Bounded retries with feedback on rejected attempts

3. **Integration**
   - Accepted delta mapped to `StateUpdateProposal` by adapter
   - `StateService.apply_update` applies as durable mutation
   - NorthStar artifact IDs are protected — proposals targeting them are rejected

4. **Export**
   - Adapter exports state-derived artifacts to output path
   - Adapter verification may execute (coding: pytest; document: consistency check)
   - Verification result fed into next CreateGame call

### Multiscale decomposition

```
_solve_gap((), ctx, depth=0)
  → CreateGame returns DecomposeSpec(sub_gaps=[A, B, C])
  → _solve_gap(("A",), ctx, depth=1)
      → CreateGame returns GameSpec for A
      → PlayGame → integrate → export
  → _solve_gap(("B",), ctx, depth=1)
      → CreateGame returns DecomposeSpec(sub_gaps=[B1, B2])
      → _solve_gap(("B", "B1"), ctx, depth=2)
          → CreateGame returns GameSpec for B1
          → PlayGame → integrate → export
      → _solve_gap(("B", "B2"), ctx, depth=2)
          → ...
  → _solve_gap(("C",), ctx, depth=1)
      → ...
→ _solve_gap((), ctx, depth=0)  [outer loop re-assesses from NorthStar]
```

Only leaf PlayGame executions count against `max_iterations`. Decomposition is free.

### Persistence

- Authoritative state: `<workspace>/state/state.json`
- Blackboard (non-authoritative): `<workspace>/blackboard/northstar_proposals.jsonl`
- Workspace config: `<workspace>/baps-config.json`
- Run result: `<workspace>/run-result.json`

---

## 5. Schema Documentation

### `GameSpec`

- Fields: `objective`, `target_artifact_id`, `allowed_delta_type`, `success_condition`, `context_chain`
- `context_chain`: tuple of gap descriptions from coarsest ancestor to immediate parent
- Invariants: objective, target, delta type, success condition all non-empty
- Purpose: binding contract for one PlayGame cycle, with full planning context

### `DecomposeSpec`

- Fields: `rationale`, `sub_gaps`
- `sub_gaps`: ordered tuple of `SubGapSpec` — each closes a coherent portion of the parent gap
- Invariants: rationale non-empty, at least one sub-gap
- Purpose: CreateGame response when the gap is too large for one game

### `SubGapSpec`

- Fields: `description`
- Purpose: a gap description passed as context to the next decomposition level

### `DeltaDocumentState` / `DeltaModifyDocumentState` / `DeltaDeleteDocumentState`

- Operations: `append_section`, `modify_section`, `delete_section`
- Payloads: `AppendSectionDelta`, `ModifySectionDelta`, `DeleteSectionDelta`

### `DeltaCodingState` / `DeltaCodingBatchState` / `DeltaDeleteCodingState`

- Operations: `write_file`, `write_files`, `delete_file`
- Payloads: `WriteFileDelta`, `WriteFilesDelta`, `DeleteFileDelta`

### `RedFinding`

- Fields: `disposition` (accept|revise|reject), `rationale`, `success_condition_met`, `findings`
- Purpose: adversarial review output

### `RefereeDecision`

- Fields: `disposition` (accept|revise|reject), `rationale`, `red_override`, `improvement_hints`
- Purpose: game-local adjudication output

### `StateUpdateProposal`

- Fields: `id`, `target`, `summary`, `payload`
- Purpose: mutation request envelope consumed by `StateService`

---

## 6. Prompt System

### CreateGame prompt

Four-step gap-analysis process:

1. **GAP ANALYSIS** — compare StateView against NorthStar; enumerate missing pieces
2. **PRIORITIZE** — select highest-impact gap
3. **DECIDE** — produce `GameSpec` (direct) or `DecomposeSpec` (decompose)
4. **SELF-CONTAIN** — fold intent into objective/success_condition or sub_gap descriptions

If a `context_chain` is present, it is rendered before the steps as "Parent planning context."

### Blue prompt

`render_blue_prompt_core` renders:

- Full `context_chain` (if non-empty): "Planning context (coarsest → finest scope)"
- Current `StateView`
- `GameSpec` fields: objective, target, delta type, success condition
- Execution rules including feedback repair on retry

Adapter supplements inject delta-shape instructions and project-specific constraints.

### Red and Referee prompts

- Core Red evaluates candidate against `GameSpec.success_condition`
- Core Referee adjudicates Red finding + candidate + GameSpec
- Adapter supplements inject type-specific guidance
- Verification result (if available) is passed as evidence to both

---

## 7. Testing Strategy

Philosophy: contract-first deterministic testing of runtime boundaries and parser behavior.

- `FakeModelClient` provides queued responses and prompt capture
- Autouse fixture patches `_build_model_client` and `_build_role_client` to inject fakes
- Prompt content and parser validation tests
- Recursive solve behavior: decompose, context chain injection, max_depth enforcement
- Adapter boundary regression tests
- Schema validation and update semantics
- State persistence and service mutation
- Export and verification paths

---

## 8. Architectural Invariants

### Enforced / Implemented

1. `State` is authoritative and persisted JSON.
2. `StateView` is a text projection — never authority.
3. `NorthStar` is inside `State` and immutable through automated pipeline.
4. CreateGame performs gap analysis, not step derivation.
5. `context_chain` carries full ancestor context to every leaf game.
6. Adapter owns all project-specific mechanics.
7. `StateService` is the runtime mutation boundary; NorthStar artifacts are protected.
8. Core orchestration remains project-type generic.
9. Export is one-way from `State`.
10. Schema validation enforced via typed models and runtime checks.
11. Deterministic tests enforce boundary contracts.

---

## 9. Current Limitations

1. Decomposition branching factor is unconstrained — the model decides how many sub-gaps to produce (`max_sub_gaps` not yet enforced).
2. No separate model role for decomposition nodes vs. leaf execution nodes.
3. Sub-gap verification feedback does not propagate upward to re-trigger parent-level decomposition.
4. Role execution is prompt-only (no tool-execution subsystem in canonical runtime).
5. Only `document` and `coding` project types are active.

---

## 10. Suggested Next Milestones

1. **`max_sub_gaps` enforcement** — cap branching factor per decomposition to bound worst-case game count
2. **Decompose model role** — separate `BAPS_DECOMPOSE_BACKEND/MODEL` so planning nodes use a lighter model than leaf execution
3. **Residual feedback propagation** — failed leaf verifications signal back to parent level to trigger re-decomposition
4. **Adapter expansion** — new project types register adapters without touching core orchestration
5. **Stronger contract tests** — verify decomposition invariants and context chain integrity end-to-end

---

## 11. Glossary

- **State**: Authoritative project condition persisted as JSON.
- **NorthStar**: Intent artifact(s) embedded inside authoritative state; the target all gap analysis measures against.
- **StateView**: Bounded text projection for model-facing prompts.
- **GameSpec**: Bounded task contract for one PlayGame cycle; carries `context_chain`.
- **DecomposeSpec**: CreateGame response signalling the gap is too large; carries ordered sub-gaps.
- **SubGapSpec**: A gap description passed down to the next decomposition level.
- **context_chain**: Ordered tuple of ancestor gap descriptions flowing from coarsest to finest into every leaf game.
- **DeltaState**: Proposed project mutation from role execution.
- **artifact**: Typed state unit (document/coding) within `State`.
- **adapter**: `ProjectTypeAdapter` implementation owning all project-specific behavior.
- **RedFinding**: Adversarial reviewer decision output.
- **RefereeDecision**: Game-local adjudication output.
- **StateUpdateProposal**: Integration envelope for mutation through `StateService`.
- **runtime**: Lifecycle orchestration path (`init`, `run`, `init_and_run`).
- **ModelClient**: Generation interface for model backends and test doubles.
- **Role**: A named model client with schema and constrained-decoding flag.
- **export**: One-way materialization of state to filesystem outputs.
- **canonical spine**: The active execution path from NorthStar through recursive gap solving to export.
- **gap analysis**: CreateGame's process of comparing current state against NorthStar to identify what is missing.
- **multiscale**: The property that decomposition can recurse to arbitrary depth, with each level informed by all levels above.
