# ARCHITECTURE.md

This document describes the **current implementation** of `bounded-adversarial-production` (`baps`) and is aligned to [docs/SYSTEM.md](docs/SYSTEM.md).

Canonical runtime spine (authoritative):

`config/NorthStar -> State -> StateView -> CreateGame -> GameSpec -> PlayGame -> DeltaState -> StateUpdateProposal -> StateService -> export`

---

## 1. Project Overview

### IMPLEMENTED

`baps` is a bounded, adapter-driven runtime for model-mediated project evolution. The runtime:

1. initializes authoritative `State` from config/NorthStar,
2. renders model-facing `StateView` text,
3. derives a bounded `GameSpec` (`CreateGame`),
4. runs adversarial evaluation (`PlayGame`: Blue -> Red -> Referee),
5. maps accepted deltas to `StateUpdateProposal`,
6. applies mutations through `StateService`,
7. exports state to output files.

Current philosophy in code:

- `State` is authoritative and persisted JSON.
- `StateView` is a projection for prompts, not authority.
- Core orchestration (`run.py`) is project-type generic.
- Project behavior is adapter-owned (`document`, `coding`).
- Runtime is bounded by max iterations and bounded PlayGame attempts.

### CONCEPTUAL

- richer tool-assisted execution/evaluation pathways,
- more sophisticated semantic validation across roles,
- optional blackboard reintegration as append-only run history.

### HISTORICAL / INACTIVE

- blackboard/event history is present on disk but not part of active canonical lifecycle execution.
- legacy runtime references remain in documentation artifacts, not in active orchestration.

---

## 2. Current System Capabilities

### Schemas (purpose, boundaries)

#### IMPLEMENTED

Defined in `src/baps/state.py`:

- `State`, `NorthStar`, `StateArtifact`, `DocumentArtifact`, `CodingArtifact`, `Section`, `CodeFile`.
- delta contracts: `DeltaDocumentState` (`append_section`), `DeltaCodingState` (`write_file`).
- game/decision contracts: `GameSpec`, `RedFinding`, `RefereeDecision`, `PlayGameRuntime`.
- integration contracts: `StateUpdateTarget`, `StateUpdateProposal`.

Responsibilities:

- enforce model shape and field non-emptiness,
- enforce artifact identity disjointness (`NorthStar` IDs cannot overlap state artifact IDs),
- provide update application (`apply_state_update`) and state fingerprinting.

Limitations:

- active delta operations are limited to `append_section` and `write_file` in adapter flow.

Dependencies:

- Pydantic v2.

Boundary:

- authoritative domain contract and mutation semantics.

### Runtime (lifecycle, integration, export)

#### IMPLEMENTED

Defined in `src/baps/run.py`:

- lifecycle commands: `init`, `run`, `init_and_run`.
- `create_game(...)` generates/parses/validates/normalizes `GameSpec`.
- `play_game(...)` executes Blue/Red/Referee with bounded attempts.
- accepted delta -> `StateUpdateProposal` -> `StateService.apply_update(...)`.
- adapter export after update; optional adapter verification (coding runs pytest).

Limitations:

- prompt-only role execution,
- no tool execution subsystem,
- no scheduler beyond bounded sequential control flow.

Dependencies:

- adapters, model clients, state service/store.

Boundary:

- orchestration only; project semantics are delegated to adapters.

### Adapters

#### IMPLEMENTED

Defined by `ProjectTypeAdapter` protocol (`src/baps/project_adapter.py`) and implemented by:

- `DocumentProjectAdapter` (`src/baps/document_adapter.py`),
- `CodingProjectAdapter` (`src/baps/coding_adapter.py`).

Adapter responsibilities:

1. create initial state,
2. render CreateGame `StateView`,
3. render PlayGame `StateView`,
4. render Blue prompt supplement,
5. parse Blue delta,
6. map delta to `StateUpdateProposal`,
7. export state,
8. optional verify_export,
9. optional prompt supplements for CreateGame/Red/Referee,
10. optional `normalize_game_spec`.

### StateView projection model

#### IMPLEMENTED

`StateView` is defined in `src/baps/northstar_projection.py` as frozen model with:

- `id`, `projection_type`, `content`, `input_fingerprint`, `metadata`.

In active runtime, adapters construct textual `StateView.content` blocks with explicit section delimiters and metadata fingerprints.

Limitations:

- `ProjectionType` currently only includes `NORTH_STAR`.

### Model layer

#### IMPLEMENTED

Defined in `src/baps/models.py`:

- `ModelClient` base interface,
- `FakeModelClient` deterministic queued responses for tests,
- `OllamaClient` HTTP client (`/api/generate`).

### Testing

#### IMPLEMENTED

Test suite (`tests/`) emphasizes deterministic runtime contracts:

- heavy `FakeModelClient` usage,
- explicit prompt/validation checks,
- adapter boundary checks,
- state mutation and persistence checks.

---

## 3. Repository Structure

### Core orchestration

- `src/baps/run.py`:
  - CLI/config resolution,
  - lifecycle execution,
  - CreateGame/PlayGame orchestration,
  - stop conditions,
  - summary/debug output.

- `src/baps/project_adapter.py`:
  - adapter protocol and dispatch,
  - default adapter registry,
  - shared Blue prompt core renderer.

### Adapter mechanics

- `src/baps/document_adapter.py`:
  - document state initialization,
  - document-specific state view rendering,
  - append-section delta parsing/mapping,
  - markdown export.

- `src/baps/coding_adapter.py`:
  - coding state initialization,
  - coding state view rendering,
  - write-file delta parsing/mapping,
  - code/test export,
  - export verification (`uv run pytest` fallback `python -m pytest`),
  - coding-specific CreateGame/Red/Referee supplements and normalization.

### State/persistence/model/projection modules

- `src/baps/state.py`: core schema + mutation + artifact registry.
- `src/baps/state_service.py`: mutation boundary service.
- `src/baps/state_store.py`: storage protocol + `JsonStateStore`.
- `src/baps/models.py`: model clients.
- `src/baps/northstar_projection.py`: projection/view models and renderer utilities.

Boundary summary:

- `run.py`: generic orchestration.
- adapters: project-specific mechanics.

---

## 4. Canonical Runtime Flow

### Lifecycle commands

- `init`:
  1. parse config,
  2. ensure workspace not initialized,
  3. adapter creates initial `State`,
  4. persist JSON state.

- `run`:
  1. load persisted state,
  2. run bounded iterations.

- `init_and_run`:
  1. initialize,
  2. immediately run bounded iterations.

### Iteration flow

1. **CreateGame**
   - adapter builds CreateGame `StateView`.
   - core renders generic CreateGame prompt + adapter supplement.
   - model output parsed into `GameSpec`.
   - adapter may normalize `GameSpec`.
   - runtime validates artifact/delta-type alignment.

2. **PlayGame**
   - adapter builds PlayGame `StateView`.
   - Blue generates candidate `DeltaState` (adapter parse).
   - Red evaluates candidate against `GameSpec`.
   - Referee decides accept/revise/reject.
   - bounded retries (`max_attempts`, default 3).

3. **Integration**
   - adapter maps accepted delta -> `StateUpdateProposal`.
   - `StateService.apply_update(...)` loads/validates/applies/revalidates/saves.

4. **Export**
   - adapter exports current state to output path.
   - adapter verification may run (coding: pytest) after export.

5. **Next iteration CreateGame evidence**
   - previous iteration verification result is passed explicitly into next CreateGame prompt context.

### Persistence

- authoritative state file: `<workspace>/state/state.json`.
- exported output files are derived materialization, not canonical authority.

### Stop conditions (IMPLEMENTED)

- `create_game_no_new_atomic_game`,
- `play_game_no_delta`,
- `no_state_change`,
- `iteration_limit_reached`.

---

## 5. Schema Documentation

All below are implemented in `src/baps/state.py` except `StateView`/`ProjectionType` in `src/baps/northstar_projection.py`.

- `State`
  - fields: `northstar`, `artifacts`.
  - invariants: unique state artifact IDs; no overlap with NorthStar artifact IDs.

- `NorthStar`
  - fields: `artifacts`.
  - invariants: unique artifact IDs.

- `StateArtifact`
  - fields: `id`, `kind` (non-empty).

- `DocumentArtifact`
  - fields: `kind="document"`, `sections`.

- `CodingArtifact`
  - fields: `kind="coding"`, `files`.

- `Section`
  - fields: `title`, `body` (non-empty).

- `CodeFile`
  - fields: `path`, `content` (non-empty).

- `GameSpec`
  - fields: `objective`, `target_artifact_id`, `allowed_delta_type`, `success_condition` (all non-empty).

- `DeltaDocumentState`
  - fields: `artifact_id`, `operation="append_section"`, `payload.section`.

- `DeltaCodingState`
  - fields: `artifact_id`, `operation="write_file"`, `payload.file`.

- `RedFinding`
  - fields: `disposition in {accept, revise, reject}`, `rationale` (non-empty).

- `RefereeDecision`
  - fields: `disposition in {accept, revise, reject}`, `rationale` (non-empty).

- `StateUpdateTarget`
  - fields: `artifact_id` (required), `section` (optional non-empty when present).

- `StateUpdateProposal`
  - fields: `id`, `target`, `summary`, `payload`, `base_state_fingerprint` (optional non-empty when present).

- `StateView`
  - fields: `id`, `projection_type`, `content`, `input_fingerprint`, `metadata`.
  - invariant: frozen (immutable model config), non-empty key string fields.

- `ProjectionType`
  - implemented enum value: `north_star`.

---

## 6. Blackboard Status

### IMPLEMENTED (observed)

- Blackboard event files exist in repository root:
  - `blackboard/events.jsonl`
  - `blackboard/adversarial-events.jsonl`
  - `blackboard/ollama-adversarial-events.jsonl`
  - `blackboard/play-game-events.jsonl`

### HISTORICAL / INACTIVE

- Canonical `baps-run` lifecycle does not read/write these files.
- `run.py` active orchestration does not call a blackboard subsystem.

### CONCEPTUAL

- If reintroduced, `docs/SYSTEM.md` requires blackboard to remain append-only run history/meta and non-authoritative vs `State`.

---

## 7. Artifact System

### IMPLEMENTED lifecycle

1. Artifact initialized in adapter-created initial `State`.
2. Adapter renders artifact context into `StateView` for CreateGame/PlayGame.
3. Adapter parses model delta into typed `DeltaState`.
4. Adapter maps delta into `StateUpdateProposal`.
5. `StateService` applies proposal against authoritative `State`.
6. Adapter exports updated artifact content to filesystem.

### Adapter ownership boundaries

- Core does not parse project file/section semantics.
- Adapters own path/section-level mechanics and export formats.

### Filesystem assumptions

- state JSON lives under workspace `state/`.
- export path is configurable and may be relative to workspace.
- coding export creates parent directories as needed.

### Export behavior

- Document: render sections to markdown file.
- Coding: write each `CodeFile` to `<output>/<file.path>`.
- Export is one-way; exported files are not fed back as authority except through explicit state updates.

---

## 8. Runtime Engine

### IMPLEMENTED responsibilities

- resolve config and lifecycle command,
- construct/dispatch adapters,
- enforce CreateGame and PlayGame contract validation,
- control bounded iterations and bounded attempts,
- integrate via `StateService`,
- export and optional verification,
- emit deterministic summary/debug fields.

### Bounded behavior

- outer loop bounded by `max_iterations`.
- PlayGame bounded by `max_attempts` (default 3).

### Retry behavior

- Blue validation failures produce structured feedback for retry.
- Red/Referee non-accept outcomes feed next attempt feedback.

### Validation boundaries

- prompt-output JSON shape validation in core and adapters,
- schema validation in Pydantic models,
- mutation validation in `StateService` via registry.

### Deterministic testing path

- substitute clients with `FakeModelClient` or monkeypatched call points,
- assert exact prompts, outcomes, and summary fields.

---

## 9. Roles and Prompt System

### CreateGame prompt

- core generic prompt in `run.py` defines one-task, one-delta contract.
- adapter adds project-type supplement.
- optional previous verification evidence is included explicitly.

### Blue prompt flow

- generic Blue core from `project_adapter.render_blue_prompt_core(...)`.
- adapter supplements:
  - document delta rules (`append_section` + non-empty section body),
  - coding delta rules (`write_file`, `src/` and `tests/test_*.py` preferences).

### Red prompt

- core generic contract enforces GameSpec-authoritative evaluation policy.
- optional adapter supplement adds project-specific guidance.
- optional verification evidence for current PlayGame context.

### Referee prompt

- core generic decision contract aligned to GameSpec.
- optional adapter supplement.
- optional verification evidence.

### Model layer

- `ModelClient`: abstract interface.
- `FakeModelClient`: deterministic test responder.
- `OllamaClient`: runtime HTTP generator.

### Current limitations

#### IMPLEMENTED limitations

- no tool execution subsystem,
- no multi-agent scheduler,
- prompt-only role execution,
- limited semantic validation beyond typed contracts and prompt policies.

---

## 10. Testing Strategy

### IMPLEMENTED philosophy

- deterministic contract testing over stochastic behavior,
- isolate orchestration correctness from model randomness.

Techniques:

- `FakeModelClient` sequences deterministic outputs,
- monkeypatch lifecycle boundaries (`create_game`, `play_game`, verification hooks),
- assert validation failures, stop reasons, and prompt contents.

Coverage areas:

- schemas and update semantics (`test_state.py`),
- state mutation boundary (`test_state_service.py`),
- state persistence (`test_state_store.py`),
- projection contracts (`test_northstar_projection.py`),
- model client behavior (`test_models.py`),
- runtime orchestration and adapter wiring (`test_run.py`).

Why deterministic testing matters here:

- runtime correctness depends on strict contract handling under variable model outputs,
- deterministic tests verify that orchestration/persistence boundaries remain stable while prompts evolve.

---

## 11. Architectural Invariants

### Enforced (code-backed)

1. `State` is authoritative persisted JSON (`JsonStateStore`, `StateService`).
2. `StateView` is separate projection model and prompt input.
3. `NorthStar` exists inside `State` and remains disjoint by artifact ID from state artifacts.
4. Core orchestration dispatches through `ProjectTypeAdapter`.
5. `StateService` is the mutation gateway (`apply_update`).
6. Export is one-way from `State` to output files.
7. Schema and prompt-output validation is mandatory before integration.
8. Runtime loops are bounded (`max_iterations`, `max_attempts`).

### Conceptual (not strictly enforced everywhere)

- richer semantic quality validation beyond current contract checks,
- expanded adapter ecosystem beyond document/coding.

---

## 12. Current Architectural Direction

### IMPLEMENTED trajectory

- adapter expansion pattern is established in protocol/registry,
- bounded game loop with role interaction is stable,
- verification evidence is now threaded through coding CreateGame and PlayGame evaluation contexts.

### CONCEPTUAL trajectory

- clearer future tool boundary integration,
- potential blackboard reintegration as non-authoritative append-only history.

### HISTORICAL context

- docs reference older runtime/event artifacts, but canonical active path is current adapter-driven `baps-run`.

---

## 13. Current Limitations

### IMPLEMENTED constraints

- blackboard runtime integration is inactive,
- prompt-only model role execution,
- narrow delta operation surface (`append_section`, `write_file`),
- no tool subsystem for executing arbitrary role actions,
- no scheduler/parallel role runtime,
- bounded role loop may stop before semantically ideal output,
- generic model behavior can still produce low-quality but contract-valid outputs.

---

## 14. Suggested Next Milestones (additive)

1. Blackbox-safe blackboard reintegration as append-only run metadata (non-authoritative).
2. Formal tool boundary for controlled execution beyond prompt-only roles.
3. Adapter-level verification hook expansion (beyond coding pytest).
4. Stronger contract tests around role outputs vs success_condition semantics.
5. Optional structured role envelopes for richer machine-checkable rationale.

All above are additive and preserve canonical spine and adapter boundaries.

---

## 15. Developer Workflow

1. Update code within existing boundaries (core orchestration vs adapter mechanics).
2. Keep schema-driven changes explicit in `state.py` and adapter mapping logic.
3. Run full tests: `uv run pytest`.
4. Validate runtime behavior via `baps-run` on example specs.
5. Prefer additive changes; avoid bypassing `StateService` and adapter dispatch.

Expected contributor discipline:

- preserve authoritative `State` semantics,
- preserve `StateView` as prompt-only projection,
- preserve adapter ownership,
- avoid project-specific leakage into `run.py` core.

---

## 16. Glossary

- **State**: authoritative persisted project condition.
- **NorthStar**: goal/policy artifact set embedded in `State`.
- **StateView**: immutable model-facing textual projection of relevant state.
- **GameSpec**: bounded game contract (objective, target, allowed delta, success condition).
- **DeltaState**: typed candidate mutation proposed by Blue.
- **artifact**: typed state unit (`document`, `coding`, etc.).
- **adapter**: project-type implementation of rendering/parsing/mapping/export behavior.
- **RedFinding**: adversarial assessment result (`accept`/`revise`/`reject` + rationale).
- **RefereeDecision**: authority decision for PlayGame candidate.
- **StateUpdateProposal**: integration payload for `StateService` mutation.
- **runtime**: lifecycle orchestration (`init`, `run`, `init_and_run`) plus bounded iterations.
- **ModelClient**: generation interface (`FakeModelClient`, `OllamaClient`).
- **export**: one-way materialization of state to files.
- **canonical spine**: required runtime flow from config/NorthStar through export.

---

## System Contract Alignment

Alignment check against `docs/SYSTEM.md`:

1. **State != StateView**: aligned (`State` authoritative, `StateView` projection).
2. **prompts consume StateView only**: aligned in active orchestration prompt construction.
3. **core orchestration generic**: aligned by adapter protocol dispatch.
4. **adapter ownership preserved**: aligned (CreateGame/PlayGame render/parse/map/export in adapters).
5. **export != state**: aligned (state persisted separately; export is derived output).
6. **blackboard inactive**: aligned for canonical `baps-run` execution.

Observed mismatches / caveats:

- `run.py` still contains compatibility helper imports (`_build_document_state_view`, `_build_coding_state_view`, etc.) used primarily for tests/legacy helper references, while active orchestration remains adapter-driven.
- repository-level docs include historical references to legacy runtime modules not present in active canonical flow.
