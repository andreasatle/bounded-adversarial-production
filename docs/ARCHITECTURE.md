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
                                     [research phase]
                                           ↓
                               DeltaState → StateUpdateProposal → StateService → export
```

---

## 1. Project Overview

`baps` is an adapter-driven, multiscale runtime for bounded, iterative project evolution over authoritative `State`. NorthStar defines the target; CreateGame identifies gaps; recursive decomposition breaks large gaps into coherent sub-games; PlayGame closes leaf gaps through adversarial evaluation.

CLI commands:

- **`reset`** — wipe workspace state and output file, then exit. No model calls, no game loop. Run before `start` when a clean slate is needed.
- **`start`** — initialize (if workspace has no state) or resume (if state exists), then run the game loop.

`start` execution behavior:

1. Read config (NorthStar content, runtime controls, model config).
2. Create or load authoritative `State`.
3. Loop until stop condition:
   a. Call `_solve_gap(context_chain=(), depth=0)` which:
      - Builds adapter-owned `StateView`
      - Calls `CreateGame` (gap analysis against NorthStar)
      - If `DecomposeSpec`: recurse into each sub-gap with extended `context_chain`; each leaf applies its delta before the next sub-gap begins
      - If `GameSpec`: inject `context_chain`, run `PlayGame`, integrate delta, export
   b. Stop when `iterations_remaining == 0` or a stop condition is raised
4. Write run result JSON to workspace.

A completed decomposition pass is not assumed to complete the project. The outer loop re-invokes CreateGame at depth 0 after all sub-gaps complete, allowing gap re-assessment against the updated state.

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

- `State`, `StateArtifact`
- `DocumentArtifact` (sections), `CodingArtifact` (files, language)
- `Section` — `title`, `body`, `source_hash` (optional; set by audit adapter only)
- `CodeFile`

**Game contracts:**

- `GameSpec` — `objective`, `target_artifact_id`, `allowed_delta_type`, `success_condition`, `context_chain`
- `SubGapSpec` — `description` (a gap to be recursively planned)
- `DecomposeSpec` — `rationale`, `sub_gaps` (CreateGame decomposition response)

**Document deltas** (payload models use `extra="forbid"`):

- `DeltaDocumentState` (`append_section`) / `AppendSectionDelta`
- `DeltaModifyDocumentState` (`modify_section`) / `ModifySectionDelta`
- `DeltaDeleteDocumentState` (`delete_section`) / `DeleteSectionDelta`

**Coding deltas** (payload models use `extra="forbid"`):

- `DeltaCodingState` (`write_file`) / `WriteFileDelta`
- `DeltaCodingBatchState` (`write_files`) / `WriteFilesDelta`
- `DeltaDeleteCodingState` (`delete_file`) / `DeleteFileDelta`

**Adversarial evaluation:**

- `RedFinding` — adversarial reviewer output (`disposition`, `rationale`, `findings`)
- `RefereeDecision` — adjudication output (`disposition`, `rationale`, `improvement_hints`)
- `PlayGameRuntime` — attempt tracking

**Integration:**

- `StateUpdateProposal`, `StateUpdateTarget`

---

### Runtime (`src/baps/run.py`)

**Lifecycle commands:** `start`, `reset`

**Key functions:**

- `create_game(...)` — gap-analysis prompt, parsing (`GameSpec | DecomposeSpec`), validation, adapter normalization
- `play_game(...)` — Blue/Red/Referee orchestration with optional research phases and bounded retries
- `_solve_gap(context_chain, ctx, ..., depth)` — recursive gap solver; accumulates context chain; counts only leaf executions against `max_iterations`; clears `play_game_no_delta` between sibling sub-gaps
- `_run_project_iterations(...)` — outer loop calling `_solve_gap` at depth 0 until stop
- `_sanitize_feedback_dict(...)` — sanitizes model-generated strings in feedback dicts before re-embedding in subsequent prompts

**`_RunContext`:** Mutable dataclass threaded through recursion tracking current state, remaining iterations, verification result, and stop reason.

**`max_sub_gaps`:** Config key (default 5, spec-overridable) bounding decomposition branching factor. `_parse_create_game_output` truncates any `DecomposeSpec` whose `sub_gaps` length exceeds the limit and prints a notice. Validated >= 1 in `resolve_run_config`.

**Per-role model selection:**

Each role can use a different model backend/model:

```bash
BAPS_{ROLE}_BACKEND=anthropic|openai|ollama
BAPS_{ROLE}_MODEL=<model-id>
```

Roles: `BLUE`, `RED`, `REFEREE`, `CREATE_GAME`, `DECOMPOSE`. Falls back to global `BAPS_BACKEND` / `BAPS_*_MODEL`.

**`DECOMPOSE` role** — used for CreateGame calls at decomposition nodes (`depth > 0`). These are structural planning tasks that require less raw capability than leaf execution. A typical setup assigns a lighter model to `DECOMPOSE` and a stronger model to `BLUE`.

**Stop conditions:**

| Stop reason | Trigger |
|---|---|
| `iteration_limit_reached` | `max_iterations` leaf games consumed |
| `create_game_no_new_game` | No gap at depth 0 |
| `play_game_no_delta` | PlayGame returned no accepted delta; at depth 0, escalates to `northstar_update_proposed` |
| `no_state_change` | Delta produced no state change; at depth 0, escalates to `northstar_update_proposed` |
| `northstar_update_proposed` | CreateGame signalled trajectory drift, or gap identified but not closable |
| `max_depth_reached` | Decomposition exceeded `max_depth` |

`_run_project_iterations` converts `play_game_no_delta` and `no_state_change` to `northstar_update_proposed` at the outer loop, appending a blackboard proposal so the human is alerted through the NorthStar approval channel.

---

### Adapters

#### Document (`src/baps/document_adapter.py`)

- Section-based document state
- CreateGame StateView: renders NorthStar + current sections (sanitized)
- PlayGame StateView: renders NorthStar + full section bodies (sanitized)
- Delta operations: `append_section`, `modify_section`, `delete_section`
- Export: markdown file

#### Coding (`src/baps/coding_adapter.py`)

- File-based codebase state; language-agnostic via plugin registry
- CreateGame StateView: renders NorthStar + existing file contents (first 30 lines, sanitized)
- PlayGame StateView: renders NorthStar + full file contents (sanitized)
- Delta operations: `write_file`, `write_files` (preferred), `delete_file`
- Export: file tree + language-plugin boilerplate
- Verification: delegates to `LanguagePlugin.run_tests`; result evidence feeds next CreateGame
- Sandbox: `sandbox_mode` propagated from config/CLI through `run.py` → `play_game` → adapter → plugin → `sandbox.run_sandboxed`
- Language resolved from `CodingArtifact.language` (set at `create_initial_state` from the spec's `language` key; **required** — omitting it raises `ValueError` listing available languages); unknown names also raise `ValueError`

#### Language Plugins (`src/baps/language_plugin.py`, `src/baps/language_python.py`, `src/baps/language_zig.py`)

`LanguagePlugin` protocol: `name`, `test_command`, `docker_image`, `initialize`, `run_tests`, `build`, `parse_test_failures`, `has_tests`

- `test_command` — shell command passed as the `sh -c` argument inside the Docker container
- `docker_image` — Docker image for sandboxed execution; passed directly to `sandbox.run_sandboxed`
- `get_language_plugin(name)` resolves a name to a plugin or raises `ValueError("Language 'X' is not supported. Available languages: ...")`

Active implementations:

| Plugin | Key | Docker image | Test command | Boilerplate |
|---|---|---|---|---|
| `PythonLanguagePlugin` | `python` | `python:3.12-slim` | `pip install pytest -q 2>/dev/null && python -m pytest` | `conftest.py`, `.gitignore`; bare mode: `uv run pytest` |
| `ZigLanguagePlugin` | `zig` | `baps-zig:latest` | `zig build test` | `build.zig`, `src/main.zig`, `.gitignore`; bare mode: `zig build test` |

The language is stored on `CodingArtifact.language` at creation time and persists in authoritative state. All subsequent operations (export, verify_export, verify_candidate) read it from the artifact — not from config. Adding a new language requires implementing `LanguagePlugin`, registering it in `language_plugin.py` and `coding_adapter.py`, and adding a spec example. `sandbox.py` requires no changes.

#### Audit (`src/baps/audit_adapter.py`)

- Document-based findings report over an external source tree
- CreateGame StateView: renders NorthStar + source file listing + current findings; stale findings marked `[STALE — source changed]`
- PlayGame StateView: renders NorthStar + full source file contents
- Delta operations: `append_section` (finding), `modify_section` (revise finding), `no_finding` (confirmed clean)
- Each accepted section stores `source_hash` (SHA-256 of source files at write time) for staleness detection
- Export: markdown findings report
- Separate workspace per spec required (each spec has its own `artifact_id`)

All adapters expose tools for Blue's tool-call interface in addition to JSON output.

---

### StateView (`src/baps/northstar_projection.py`)

- `StateView`: `id`, `projection_type`, `content`, `input_fingerprint`, `metadata`
- Content uses explicit delimiters (`=== StateView Start/End ===`)
- Built by adapters for CreateGame and PlayGame contexts
- Never passed as raw JSON to prompts
- All model-generated content embedded in `StateView.content` is NFKC-normalized and injection-pattern-sanitized before inclusion

---

### Model Layer (`src/baps/models.py`)

Active backends:

- `AnthropicClient` — Anthropic API (Claude models)
- `OpenAIClient` — OpenAI API (GPT models)
- `OllamaClient` — local Ollama server
- `FakeModelClient` — deterministic test double with queued responses and prompt capture

`Role` wraps a client with name, output schema, and constrained-decoding flag. Roles supporting research phases use `generate_agentic(...)` for tool-use loops before producing their primary output.

---

### Adaptive Scheduler (`src/baps/scheduler.py`)

Runs specs repeatedly across a model ladder with policy-guided selection:

- EMA reward scoring: `score = 0.7 * score + 0.3 * reward`
- Softmax model selection with decaying temperature
- Automatic escalation to stronger model on low reward
- Underperformer dropping: models below score floor after min runs are removed
- Multi-round support with ladder reload between rounds
- Configurable via `BAPS_MODEL_LADDER` (comma-separated model names)
- Policy path validated to be within current working directory

---

### NorthStar Apply CLI (`src/baps/northstar_apply.py`)

Reviews and applies approved NorthStar proposals from the blackboard:

```bash
baps-apply-northstar <workspace> [--index N] [--dry-run]
```

Reads `<workspace>/blackboard/northstar_proposals.jsonl`, lists proposals interactively, writes accepted `proposed_northstar` to `baps-config.json`. Config path is validated to remain within the workspace (symlink escape rejection).

---

### Security Boundaries (`src/baps/project_adapter.py`, `src/baps/tools.py`)

- `sanitize_model_string`: NFKC-normalizes and applies injection-pattern regex before embedding model-generated strings in prompts
- `sanitize_model_title`: additionally collapses to a single line and strips leading `#` characters
- `normalize_json_candidate`: enforces 64 KB byte-length cap before `json.loads` to bound memory allocation
- `_sanitize_external_content` (tools.py): same NFKC normalization applied to external web content
- All delta payload models use `extra="forbid"` — unexpected fields are rejected rather than silently dropped
- GameSpec fields (`objective`, `success_condition`) are sanitized before embedding in Red and Referee prompts
- Referee/Red rationale is sanitized before re-embedding in `previous_feedback` for subsequent Blue turns
- NorthStar proposals are sanitized before writing to the blackboard
- `sandbox.py`: `run_sandboxed(cwd, mode, test_command, docker_image)` — runs `test_command` inside `docker_image` via `docker run --rm -v <cwd>:/work:rw`; the image and command are plugin-owned; `sandbox=none` opt-in emits `SANDBOX_NONE_WARNING` at run start; configurable via `--sandbox` CLI flag or `sandbox` spec key (default: `docker`)

---

## 3. Repository Structure

```
src/baps/
  run.py                  # Generic lifecycle orchestration, recursive gap solver
  project_adapter.py      # ProjectTypeAdapter protocol, registry, sanitizers, Blue prompt core
  document_adapter.py     # DocumentProjectAdapter — all document mechanics
  coding_adapter.py       # CodingProjectAdapter — all coding mechanics (language-agnostic)
  audit_adapter.py        # AuditProjectAdapter — all audit mechanics, source fingerprinting
  language_plugin.py      # LanguagePlugin protocol + get_language_plugin registry lookup
  language_python.py      # PythonLanguagePlugin — Python/pytest specifics
  language_zig.py         # ZigLanguagePlugin — Zig/build.zig specifics
  state.py                # Authoritative schemas, mutation, delta application
  state_service.py        # StateService — the only mutation boundary
  state_store.py          # JsonStateStore — JSON persistence
  models.py               # ModelClient, backends, FakeModelClient, Role
  northstar_projection.py # StateView, ProjectionType, projection utilities
  scheduler.py            # Adaptive multi-model scheduler with policy learning
  scheduler_policy.py     # ModelPolicy, EMA scoring, softmax selection
  northstar_apply.py      # baps-apply-northstar CLI
  sandbox.py              # run_sandboxed — generic Docker/bare execution, SANDBOX_NONE_WARNING
  tools.py                # fetch_url, web_search, ToolExecutor — research phase tools

tests/
  test_state.py
  test_state_service.py
  test_state_store.py
  test_northstar_projection.py
  test_models.py
  test_run.py
  test_audit_adapter.py
  test_language_plugin.py
  test_scheduler_policy.py
  test_scheduler.py
  test_northstar_apply.py
  test_tools.py
  test_sandbox.py

docs/
  SYSTEM.md               # Normative system contract
  ARCHITECTURE.md         # Implementation description (this file)
  NORTH-STAR.md           # Long-term intent and philosophy

examples/
  document-project.yaml
  coding-project.yaml
  coding-project-zig.yaml
  audit-baps.yaml         # Security audit spec (workspace: .baps-workspace-security)
  audit-coverage.yaml     # Test coverage audit spec (workspace: .baps-workspace-coverage)

docker/
  zig/
    Dockerfile            # Debian Bookworm + Zig toolchain; build: docker build -t baps-zig:latest docker/zig/
```

---

## 4. Canonical Runtime Flow

### Lifecycle commands

- `start` — initialize (if no state) or resume (if state exists), then run the game loop
- `reset` — wipe workspace state and output file, then exit; no model calls

### Iteration flow (inside `_solve_gap`)

1. **CreateGame** — gap analysis
   - Adapter builds CreateGame `StateView` (NorthStar + current artifact state)
   - Core renders gap-analysis prompt with optional `context_chain` from parent levels
   - Model returns `GameSpec`, `DecomposeSpec`, `no_new_game`, or `northstar_update_needed`
   - If `DecomposeSpec`: recurse for each sub-gap with extended context chain; `play_game_no_delta` clears between siblings

2. **PlayGame** — adversarial execution (leaf games only)
   - Optional research phase: each role may run agentic tool loops before producing output
   - Adapter builds PlayGame `StateView`
   - Blue prompt includes full `context_chain` from all ancestor levels
   - Blue produces candidate `DeltaState` (JSON or tool call)
   - Red evaluates against `GameSpec`; its rationale is sanitized before feeding back to Blue
   - Referee decides accept/revise/reject
   - Bounded retries with sanitized feedback on rejected attempts

3. **Integration**
   - Accepted delta mapped to `StateUpdateProposal` by adapter
   - `StateService.apply_delta` applies as durable mutation
   - NorthStar artifact IDs are protected — proposals targeting them are rejected

4. **Export**
   - Adapter exports state-derived artifacts to output path
   - Adapter verification may execute (coding: language plugin test suite; audit: structural check)
   - Verification result fed into next CreateGame call

### Multiscale decomposition

```
_solve_gap((), ctx, depth=0)           ← outer loop re-invokes this after all sub-gaps complete
  → CreateGame returns DecomposeSpec(sub_gaps=[A, B, C])
  → _solve_gap(("A",), ctx, depth=1)
      → CreateGame returns GameSpec for A
      → PlayGame → integrate → export   ← state updated; B and C will see result
  → _solve_gap(("B",), ctx, depth=1)
      → CreateGame returns DecomposeSpec(sub_gaps=[B1, B2])
      → _solve_gap(("B", "B1"), ctx, depth=2)
          → PlayGame → integrate → export
      → _solve_gap(("B", "B2"), ctx, depth=2)
          → ...
  → _solve_gap(("C",), ctx, depth=1)
      → ...
→ outer loop: CreateGame re-assesses at depth=0 against updated state
```

Only leaf PlayGame executions count against `max_iterations`. Decomposition is free. The project is not considered complete until CreateGame returns `no_new_game` at depth 0.

### Persistence

- Authoritative state: `<workspace>/state/state.json`
- Blackboard (non-authoritative): `<workspace>/blackboard/northstar_proposals.jsonl`
- Workspace config: `<workspace>/baps-config.json`
- Run result: `<workspace>/run-result.json`

---

## 5. Schema Documentation

### `CodingArtifact`

- Fields: `id`, `kind` (`"coding"`), `language` (required; set from spec at creation time), `files`
- `language`: set at `create_initial_state` from the spec's `language` key; persists in authoritative state; read by all coding operations (export, verify_export, verify_candidate) to select the language plugin

### `Section`

- Fields: `title`, `body`, `source_hash` (optional, default `None`)
- `source_hash`: set by audit adapter only; SHA-256 of source files at write time; used for staleness detection on subsequent runs
- Document and coding adapters never set `source_hash`

### `GameSpec`

- Fields: `objective`, `target_artifact_id`, `allowed_delta_type`, `success_condition`, `context_chain`
- `context_chain`: tuple of gap descriptions from coarsest ancestor to immediate parent
- Invariants: objective, target, delta type, success condition all non-empty
- Purpose: binding contract for one PlayGame cycle, with full planning context

### `DecomposeSpec`

- Fields: `rationale`, `sub_gaps`
- `sub_gaps`: ordered tuple of `SubGapSpec` — each closes a coherent portion of the parent gap
- Invariants: rationale non-empty, at least one sub-gap, length bounded by `max_sub_gaps`
- Purpose: CreateGame response when the gap is too large for one game

### `SubGapSpec`

- Fields: `description`
- Purpose: a gap description passed as context to the next decomposition level

### Delta payload models

All payload models use `model_config = ConfigDict(extra="forbid")`:

- `AppendSectionDelta` — `section: Section`
- `ModifySectionDelta` — `section_title`, `new_body`
- `DeleteSectionDelta` — `section_title`
- `WriteFileDelta` — `file: CodeFile`
- `WriteFilesDelta` — `files: tuple[CodeFile, ...]`
- `DeleteFileDelta` — `path`

### `RedFinding`

- Fields: `disposition` (accept|revise|reject), `rationale`, `success_condition_met`, `findings`
- Purpose: adversarial review output; rationale is sanitized before re-embedding in feedback

### `RefereeDecision`

- Fields: `disposition` (accept|revise|reject), `rationale`, `red_override`, `improvement_hints`
- Purpose: game-local adjudication output; rationale is sanitized before re-embedding in feedback

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
- `GameSpec` fields: objective (sanitized), target, delta type, success condition (sanitized)
- Execution rules including feedback repair on retry

Adapter supplements inject delta-shape instructions and project-specific constraints.

### Red and Referee prompts

- Core Red evaluates candidate against `GameSpec.success_condition` (sanitized)
- Core Referee adjudicates Red finding + candidate + GameSpec
- Adapter supplements inject type-specific guidance
- Verification result (if available) is passed as evidence to both
- Red/Referee rationale and findings are sanitized before flowing into `previous_feedback`

### Research phases

Before producing their primary output, Blue, Red, and Referee roles may optionally run agentic tool-use loops (`generate_agentic`). Tool call logs are passed between roles for transparency. Adapters control which tools each role receives.

---

## 7. Testing Strategy

Philosophy: contract-first deterministic testing of runtime boundaries and parser behavior.

- `FakeModelClient` provides queued responses and prompt capture
- Autouse fixture patches `_build_model_client` and `_build_role_client` to inject fakes
- Prompt content and parser validation tests
- Recursive solve behavior: decompose, context chain injection, max_depth enforcement, sibling continuation after `play_game_no_delta`
- Adapter boundary regression tests
- Schema validation and update semantics
- State persistence and service mutation
- Export and verification paths
- Language plugin wiring: `resolve_run_config` propagation, `verify_export` and `verify_candidate` routing to correct plugin and Docker image
- Security boundary tests: path anchoring, symlink escape rejection, policy path validation
- Sandbox boundary tests: Docker command construction, bind-mount scope, symlink resolution, flag invariants, warning emission, unknown-mode rejection
- Scheduler policy tests: EMA scoring, softmax selection, underperformer dropping

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
12. Model-generated content is sanitized before embedding in any prompt.
13. Delta payload models reject unexpected fields.
14. Model response size is bounded before deserialization.
15. Model-generated code executes inside a Docker container during verification; unsandboxed execution requires explicit opt-in.
16. Decomposition branching factor is bounded by `max_sub_gaps`; excess sub-gaps are truncated before recursion begins.
17. Language plugin is selected from `CodingArtifact.language` (persisted in state at creation time); all operations read from the artifact, not from runtime config.

---

## 9. Current Limitations

1. Sub-gap planning is fixed at decomposition time — individual leaf results cannot trigger re-planning of remaining siblings within the same iteration.
2. Only `document`, `coding`, and `audit` project types are active.
3. Audit source staleness detection uses a fixed hash of all source files; per-file granularity is not yet implemented.

---

## 10. Suggested Next Milestones

1. ~~**`max_sub_gaps` enforcement**~~ — done: `max_sub_gaps` config key (default 5) truncates oversized `DecomposeSpec` before execution
2. ~~**Language plugin system**~~ — done: `LanguagePlugin` protocol with Python and Zig implementations; language stored on `CodingArtifact`; `sandbox.run_sandboxed` is generic
3. **Per-file staleness** — track source hash per file within audit sections for finer-grained invalidation
4. **Docker network isolation** — add `--network=none` to the Docker sandbox for language plugins that do not need network access at test time (Zig is a candidate; Python with pip install is not)
5. **Prompt-complexity routing** — extend DECOMPOSE role to select model based on StateView size or estimated task complexity
6. **Stronger contract tests** — verify decomposition invariants and context chain integrity end-to-end
7. **Additional language plugins** — C, JavaScript/Node, or others; each adds only a plugin file and registry entry

---

## 11. Glossary

- **State**: Authoritative project condition persisted as JSON.
- **NorthStar**: Intent artifact(s) embedded inside authoritative state; the target all gap analysis measures against.
- **StateView**: Bounded, sanitized text projection for model-facing prompts.
- **GameSpec**: Bounded task contract for one PlayGame cycle; carries `context_chain`.
- **DecomposeSpec**: CreateGame response signalling the gap is too large; carries ordered sub-gaps.
- **SubGapSpec**: A gap description passed down to the next decomposition level.
- **context_chain**: Ordered tuple of ancestor gap descriptions flowing from coarsest to finest into every leaf game.
- **DeltaState**: Proposed project mutation from role execution.
- **artifact**: Typed state unit (document/coding) within `State`.
- **adapter**: `ProjectTypeAdapter` implementation owning all project-specific behavior.
- **LanguagePlugin**: Protocol owning `docker_image`, `test_command`, and test lifecycle for a specific programming language within the coding adapter.
- **RedFinding**: Adversarial reviewer decision output.
- **RefereeDecision**: Game-local adjudication output.
- **StateUpdateProposal**: Integration envelope for mutation through `StateService`.
- **runtime**: Lifecycle orchestration via `start` (initialize-or-resume + game loop) and `reset` (wipe only).
- **ModelClient**: Generation interface for model backends and test doubles.
- **Role**: A named model client with schema, constrained-decoding flag, and optional research phase.
- **export**: One-way materialization of state to filesystem outputs.
- **canonical spine**: The active execution path from NorthStar through recursive gap solving to export.
- **gap analysis**: CreateGame's process of comparing current state against NorthStar to identify what is missing.
- **multiscale**: The property that decomposition can recurse to arbitrary depth, with each level informed by all levels above.
- **source_hash**: SHA-256 fingerprint of source files stored per audit section; used to detect staleness on re-runs.
- **research phase**: Optional agentic tool-use loop run by a role before producing its primary output.
- **sandbox**: Execution isolation for model-generated code during verification; `docker` (default) runs the language plugin's `test_command` inside its `docker_image`; `none` runs bare with a warning.
