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
                               integration-eligible DeltaState → StateService.apply_delta → export
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

### Schemas (`src/baps/state/state.py`)

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

### Runtime (`src/baps/core/run.py`, `src/baps/core/orchestration.py`)

**`run.py` — lifecycle commands:** `start`, `reset`, config resolution, `main()`

**`orchestration.py` — recursive gap solver:**

- `_solve_gap(context_chain, ctx, ..., depth)` — recursive gap solver; accumulates context chain; counts only leaf executions against `max_iterations`; clears `play_game_no_delta` between sibling sub-gaps
- `_run_project_iterations(...)` — outer loop calling `_solve_gap` at depth 0 until stop
- `_RunContext` — mutable context threaded through recursion tracking current state, remaining iterations, verification result, and stop reason

**`game/` — game execution package (split from former `core/game.py`):**

- `engine.py` — `create_game(...)` and `play_game(...)` entry points; gap-analysis prompt, parsing, validation, adapter normalization, Blue/Red/Referee orchestration
- `attempt.py` — `_run_play_game_attempt(...)` (single attempt: Blue → Red → Referee), `_apply_play_game_attempt_decision(...)` (accept/retry/stop logic)
- `roles.py` — `_resolve_play_game_roles(...)`, `_build_play_game_fallbacks(...)`, role schemas (Red, Referee)
- `play.py` — `_record_play_game_telemetry(...)` (blackboard + debug events at end of `play_game`)
- `telemetry.py` — `_append_*_to_blackboard(...)` helpers, `_sanitize_feedback_dict(...)`, `_sanitize_game_spec_dict(...)`, `_VERIFICATION_SUMMARY_CAP`

**`max_sub_gaps`:** Config key (default 5, spec-overridable) bounding decomposition branching factor. `_parse_create_game_output` truncates any `DecomposeSpec` whose `sub_gaps` length exceeds the limit and prints a notice. Validated >= 1 in `resolve_run_config`.

**Model configuration — spec-first, env fallback:**

Backend and model are configured in the spec file. No hardcoded defaults — the run fails with a clear error if nothing is configured:

```yaml
backend: ollama          # anthropic | openai | ollama
model: gemma4:e4b

roles:                   # optional per-role overrides
  blue:
    backend: anthropic
    model: claude-sonnet-4-6
  create_game:
    backend: ollama
    model: gemma4:26b
    fallback:            # escalated to only after all primary JSON-correction retries are exhausted
      backend: ollama
      model: gemma4:27b
  decompose:
    backend: ollama
    model: gemma4:e4b
```

Precedence: role-spec > global-spec > role-env (`BAPS_{ROLE}_BACKEND` / `BAPS_{ROLE}_MODEL`) > global-env (`BAPS_BACKEND` / `BAPS_*_MODEL`). Environment variables remain as a fallback for CI or spec-free usage.

Client construction is handled by `_resolve_backend_model(role, config)` → `_build_client_for_role(role, config)`. Both functions are config-dict-driven and raise `ValueError("No model configured...")` if no backend/model can be resolved.

**Model fallback/escalation:** Each role may optionally declare a `fallback` block with its own `backend` and `model`. Chains can be arbitrarily deep — a `fallback` block may itself contain a `fallback`, and so on. After the primary model exhausts all JSON-correction retries, the chain is traversed in order, trying each link exactly once. No escalation occurs outside what is declared in the spec. The `_build_fallback_chain_for_role(role, config)` → `_make_fallback_chain_fn(role, primary_model, chain)` pathway constructs and wraps the fallback chain once before the attempt loop. A WARNING is logged at each escalation step with the source and target model names. If the entire chain is exhausted, `RuntimeError("<role>: all models in fallback chain exhausted")` is raised.

**`DECOMPOSE` role** — used for CreateGame calls at decomposition nodes (`depth > 0`). These are structural planning tasks that require less raw capability than leaf execution. A typical setup assigns a lighter model to `DECOMPOSE` and a stronger model to `BLUE`.

**Stop conditions:**

| Stop reason | Trigger |
|---|---|
| `iteration_limit_reached` | `max_iterations` leaf games consumed |
| `create_game_no_new_game` | No gap at depth 0; only valid when no verification has run or last verification passed |
| `play_game_no_delta` | PlayGame returned no accepted delta; at depth 0, escalates to `northstar_update_proposed` |
| `no_state_change` | Delta produced no state change; at depth 0, escalates to `northstar_update_proposed` |
| `northstar_update_proposed` | CreateGame signalled trajectory drift, or gap identified but not closable |
| `max_depth_reached` | Decomposition exceeded `max_depth` |

`_run_project_iterations` converts `play_game_no_delta` and `no_state_change` to `northstar_update_proposed` at the outer loop, appending a blackboard proposal so the human is alerted through the NorthStar approval channel.

`create_game_no_new_game` is only accepted as a stop when no verification has run (non-coding project) or the last verification passed. When verification is failing, `no_new_game` is treated as a model error: the runtime logs a warning and retries `create_game` with the failing verification already in context. A second consecutive `no_new_game` with failing verification escalates to `northstar_update_proposed`.

---

### Adapters

#### Document (`src/baps/adapters/document_adapter.py`)

- Section-based document state
- CreateGame StateView: renders NorthStar + current sections (sanitized)
- PlayGame StateView: renders NorthStar + full section bodies (sanitized)
- Delta operations: `append_section`, `modify_section`, `delete_section`
- Export: markdown file

#### Coding (`src/baps/adapters/coding_adapter.py` + `src/baps/adapters/coding/`)

`coding_adapter.py` is a thin facade; all implementation is split into focused modules under `coding/`:

- `common.py` — `_validate_file_path`, `_plugin_for`, `_config_language`, `coding_artifact_from_state`
- `delta_apply.py` — `_apply_delta_to_files`, `_normalize_coding_export_content`
- `parsing.py` — `parse_coding_delta_json` (validates `write_file`, `write_files`, `delete_file`; malformed-JSON recovery path)
- `prompting.py` — `render_coding_blue_prompt`, `_render_coding_evaluation_supplement`
- `state_updates.py` — `derive_coding_state_update_from_delta`
- `views.py` — `build_coding_create_game_state_view`, `build_coding_state_view`

Adapter capabilities:
- File-based codebase state; language-agnostic via plugin registry
- CreateGame StateView: renders NorthStar + existing file contents (first 30 lines, sanitized)
- PlayGame StateView: renders NorthStar + full file contents (sanitized)
- Delta operations: `write_file`, `write_files` (preferred), `delete_file`
- Tool-call interface: `write_files`, `write_file`, `delete_file` tools exposed via `build_blue_tools()`; `tool_call_to_delta()` converts tool call to `DeltaState`
- Export: file tree + language-plugin boilerplate; `commit_export()` optionally git-commits to the output path
- Verification: `verify_export()` (export-level tests), `verify_candidate()` (in-flight candidate in temp dir); both delegate to `LanguagePlugin.run_tests`; result evidence feeds next CreateGame
- Sandbox: `sandbox_mode` propagated from config/CLI through `run.py` → `play_game` → adapter → plugin → `sandbox.run_sandboxed`
- Language resolved from `CodingArtifact.language` (set at `create_initial_state` from the spec's `language` key; **required** — omitting it raises `ValueError` listing available languages); unknown names also raise `ValueError`

#### Language Plugins (`src/baps/plugins/language_plugin.py`, `src/baps/plugins/language_python.py`, `src/baps/plugins/language_zig.py`)

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

#### Audit (`src/baps/adapters/audit_adapter.py`)

- Document-based findings report over an external source tree
- CreateGame StateView: renders NorthStar + source file listing + current findings; stale findings marked `[STALE — source changed]`
- PlayGame StateView: renders NorthStar + full source file contents
- Delta operations: `append_section` (finding), `modify_section` (revise finding), `no_finding` (confirmed clean)
- Each accepted section stores `source_hash` (SHA-256 of source files at write time) for staleness detection
- Export: markdown findings report
- Separate workspace per spec required (each spec has its own `artifact_id`)

All adapters expose tools for Blue's tool-call interface in addition to JSON output.

---

### StateView (`src/baps/northstar/northstar_projection.py`)

- `StateView`: `id`, `projection_type`, `content`, `input_fingerprint`, `metadata`
- Content uses explicit delimiters (`=== StateView Start/End ===`)
- Built by adapters for CreateGame and PlayGame contexts
- Never passed as raw JSON to prompts
- All model-generated content embedded in `StateView.content` is NFKC-normalized and injection-pattern-sanitized before inclusion

---

### Model Layer (`src/baps/models/models.py`)

Active backends:

- `AnthropicClient` — Anthropic API (Claude models)
- `OpenAIClient` — OpenAI API (GPT models)
- `OllamaClient` — local Ollama server
- `FakeModelClient` — deterministic test double with queued responses and prompt capture

`Role` wraps a client with name, output schema, and constrained-decoding flag. Roles supporting research phases use `generate_agentic(...)` for tool-use loops before producing their primary output.

---

### Adaptive Scheduler (`src/baps/scheduler/scheduler.py`)

Runs specs repeatedly across a model ladder with policy-guided selection:

- EMA reward scoring: `score = 0.7 * score + 0.3 * reward`
- Softmax model selection with decaying temperature
- Automatic escalation to stronger model on low reward
- Underperformer dropping: models below score floor after min runs are removed
- Multi-round support with ladder reload between rounds
- Configurable via `BAPS_MODEL_LADDER` (comma-separated model names)
- Policy path validated to be within current working directory

---

### NorthStar Apply CLI (`src/baps/northstar/northstar_apply.py`)

Reviews and applies approved NorthStar proposals from the blackboard:

```bash
baps-apply-northstar <workspace> [--index N] [--dry-run]
```

Reads `<workspace>/blackboard/northstar_proposals.jsonl`, lists proposals interactively, writes accepted `proposed_northstar` to `baps-config.json`. Config path is validated to remain within the workspace (symlink escape rejection).

---

### Security Boundaries (`src/baps/adapters/project_adapter.py`, `src/baps/tools/tools.py`)

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
  core/
    run.py                  # Lifecycle commands (start, reset), config resolution, main()
    orchestration.py        # _solve_gap, _run_project_iterations, _RunContext — recursive gap solver
    prompts.py              # All prompt rendering functions
    parsers.py              # All model output parsing functions
    clients.py              # All client-building functions, SpecRole, backend resolution
    debug.py                # Debug print helpers
  game/                     # Game execution package (split from core/game.py)
    engine.py               # create_game, play_game — top-level orchestration entry points
    attempt.py              # _run_play_game_attempt, _apply_play_game_attempt_decision
    play.py                 # _record_play_game_telemetry
    roles.py                # _resolve_play_game_roles, _build_play_game_fallbacks, role schemas
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
      state_updates.py      # derive_coding_state_update_from_delta
      views.py              # build_coding_create_game_state_view, build_coding_state_view
  state/
    state.py                # Authoritative schemas, mutation, delta application
    state_service.py        # StateService — the only mutation boundary
    state_store.py          # JsonStateStore — JSON persistence
  models/
    models.py               # ModelClient, backends, FakeModelClient, Role
    model_output.py         # Single model output parsing pipeline
  plugins/
    language_plugin.py      # LanguagePlugin protocol + get_language_plugin registry lookup
    language_python.py      # PythonLanguagePlugin — Python/pytest specifics
    language_zig.py         # ZigLanguagePlugin — Zig/build.zig specifics
  scheduler/
    scheduler.py            # Adaptive multi-model scheduler with policy learning
    scheduler_policy.py     # ModelPolicy, EMA scoring, softmax selection
  tools/
    tools.py                # fetch_url, web_search, ToolExecutor — research phase tools
    sandbox.py              # run_sandboxed — generic Docker/bare execution, SANDBOX_NONE_WARNING
  northstar/
    northstar_projection.py # StateView, ProjectionType, projection utilities
    northstar_apply.py      # baps-apply-northstar CLI

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
  SYSTEM.md               # Normative system contract
  ARCHITECTURE.md         # Implementation description (this file)
  NORTH-STAR.md           # Long-term intent and philosophy

examples/
  document-project.yaml
  coding-project.yaml
  coding-project-zig.yaml
  audit-baps.yaml         # Security audit spec
  audit-coverage.yaml     # Test coverage audit spec
  audit-dry.yaml

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
   - `play_game` returns an integration-eligible `DeltaState` (or `None`)
   - `_solve_gap` applies that `DeltaState` via `StateService.apply_delta` as the runtime mutation boundary
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
- Purpose: non-runtime mutation envelope consumed by `StateService.apply_update` for proposal/workflow use cases

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
18. `create_game_no_new_game` is only a valid stop when no verification has run or the last verification passed; failing tests are evidence of an open gap and must not be silently ignored.

---

## 9. Current Limitations

1. Sub-gap planning is fixed at decomposition time — individual leaf results cannot trigger re-planning of remaining siblings within the same iteration.
2. Only `document`, `coding`, and `audit` project types are active.
3. Audit source staleness detection uses a fixed hash of all source files; per-file granularity is not yet implemented.

---

## 10. Suggested Next Milestones

1. ~~**`max_sub_gaps` enforcement**~~ — done: `max_sub_gaps` config key (default 5) truncates oversized `DecomposeSpec` before execution
2. ~~**Language plugin system**~~ — done: `LanguagePlugin` protocol with Python and Zig implementations; language stored on `CodingArtifact`; `sandbox.run_sandboxed` is generic
3. ~~**Formal tool boundary**~~ — done: `build_blue_tools()` and `tool_call_to_delta()` on `ProjectTypeAdapter`; coding adapter exposes `write_files`, `write_file`, `delete_file` tools; Blue can produce deltas via tool call or JSON
4. **Per-file staleness** — track source hash per file within audit sections for finer-grained invalidation
5. **Docker network isolation** — add `--network=none` to the Docker sandbox for language plugins that do not need network access at test time (Zig is a candidate; Python with pip install is not)
6. **Prompt-complexity routing** — extend DECOMPOSE role to select model based on StateView size or estimated task complexity
7. **Stronger contract tests** — verify decomposition invariants and context chain integrity end-to-end
8. **Additional language plugins** — C, JavaScript/Node, or others; each adds only a plugin file and registry entry

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
- **StateUpdateProposal**: Proposal/workflow mutation envelope used by `StateService.apply_update` (not the canonical runtime integration path).
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
