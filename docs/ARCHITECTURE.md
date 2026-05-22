# ARCHITECTURE.md

This document records the **actual implemented architecture** of `bounded-adversarial-production` (`baps`) and is aligned with [SYSTEM.md](SYSTEM.md).

Canonical runtime spine (authoritative):

`config/NorthStar -> State -> StateView -> CreateGame -> GameSpec -> PlayGame -> DeltaState -> StateUpdateProposal -> StateService -> export`

## 1. Project Overview

### IMPLEMENTED

`baps` is an adapter-driven runtime for bounded, iterative project evolution over authoritative `State`.

Current execution behavior:

1. Read config (including NorthStar content and runtime controls).
2. Create or load authoritative `State`.
3. Build adapter-owned `StateView` for model reasoning.
4. Run `CreateGame` to derive a bounded `GameSpec`.
5. Run `PlayGame` (Blue -> Red -> Referee) to obtain an accepted `DeltaState`.
6. Convert delta to `StateUpdateProposal` and apply through `StateService`.
7. Export materialized output via adapter.
8. Optionally verify export via adapter and feed that evidence into next `CreateGame`.

Current philosophy in code:

- `State` is authority.
- `StateView` is model-facing projection.
- Core orchestration is generic.
- Project-specific behavior is adapter-owned.
- Runtime is bounded by iterations and bounded PlayGame attempts.

### CONCEPTUAL

Observed conceptual direction in code/docs (not active runtime):

- richer tool-mediated role execution,
- stronger semantic quality controls,
- blackboard reintegration as append-only process history.

### HISTORICAL / INACTIVE

- Blackboard/proposal history paths exist but are not canonical runtime authority.
- No alternate execution spine is active in lifecycle commands.

## 2. Current System Capabilities

### Schemas

Purpose:

- Define authoritative state, delta contracts, game contracts, decisions, and integration payloads.

Key models (in `src/baps/state.py`):

- `State`, `NorthStar`, `StateArtifact`, `DocumentArtifact`, `CodingArtifact`, `Section`, `CodeFile`.
- `GameSpec`.
- `DeltaDocumentState` (`append_section`), `DeltaCodingState` (`write_file`).
- `RedFinding`, `RefereeDecision`, `PlayGameRuntime`.
- `StateUpdateProposal`, `StateUpdateTarget`.

Limitations:

- Active delta operations in canonical adapter flow are bounded to document section append and coding file write.

Dependencies:

- Pydantic validation and model serialization.

Boundary:

- Schema layer encodes domain constraints and update application semantics.

### Runtime

Purpose:

- Execute lifecycle commands and bounded CreateGame/PlayGame/integration/export loop.

Implemented responsibilities (`src/baps/run.py`):

- Commands: `init`, `run`, `init_and_run`.
- `create_game(...)`: prompt generation, parsing, validation, adapter normalization, contract checks.
- `play_game(...)`: Blue/Red/Referee orchestration with bounded retries.
- Integration through `StateService`.
- Export and optional adapter verification.

Limitations:

- Prompt-only role execution.
- No tool-execution runtime in active flow.
- No multi-agent scheduler.

Dependencies:

- `ProjectTypeAdapter`, model clients, state service/store.

Boundary:

- Core runtime orchestrates; adapters own project semantics.

### Adapters (`document`, `coding`)

Purpose:

- Encapsulate project-type behavior behind one protocol.

Implemented capabilities:

- initial state creation,
- CreateGame/PlayGame `StateView` rendering,
- prompt supplements,
- delta parsing,
- delta->update mapping,
- export,
- export verification.

Limitations:

- Only `document` and `coding` project types are active.

Dependencies:

- Shared adapter protocol + state schemas.

Boundary:

- All project-specific logic remains in adapter implementations.

### StateView

Purpose:

- Provide bounded textual projection for prompts.

Implementation (`src/baps/northstar_projection.py`, adapter builders):

- `StateView` includes `id`, `projection_type`, `content`, `input_fingerprint`, `metadata`.
- Active projections use textual sections with explicit delimiters.

Limitations:

- `ProjectionType` currently active as `NORTH_STAR`.

Boundary:

- `StateView` is not authoritative state.

### Model Layer

Purpose:

- Provide generation interface and deterministic test doubles.

Implementation (`src/baps/models.py`):

- `ModelClient` interface.
- `FakeModelClient` for deterministic queued responses and prompt capture.
- `OllamaClient` HTTP-backed model client.

Limitations:

- No active tool-call execution loop in canonical runtime.

### Testing

Purpose:

- Enforce deterministic contracts and architectural boundaries.

Implementation:

- Heavy `FakeModelClient` use.
- Prompt content and parser validation tests.
- Adapter boundary regression tests.
- State mutation/persistence tests.
- Export and verification behavior tests.

## 3. Repository Structure

### Core orchestration

- `src/baps/run.py`
  - Purpose: lifecycle/runtime orchestration.
  - Responsibilities: config resolution, CreateGame/PlayGame loop, integration, export, summary/debug output.
  - Dependencies: adapters, models, state service/store, schemas.
  - Boundary: must remain project-type generic.

- `src/baps/project_adapter.py`
  - Purpose: adapter contract and dispatch.
  - Responsibilities: `ProjectTypeAdapter` protocol, adapter registry resolution, shared Blue prompt core rendering.
  - Dependencies: schema and model abstractions.
  - Boundary: defines adapter seam between core and project-specific mechanics.

### Adapter mechanics

- `src/baps/document_adapter.py`
  - Purpose: document-type behavior.
  - Responsibilities: document state init/view rendering, delta parsing/mapping, markdown export, document export verification.
  - Dependencies: schema models and adapter protocol.
  - Boundary: document logic only.

- `src/baps/coding_adapter.py`
  - Purpose: coding-type behavior.
  - Responsibilities: coding init/view rendering, delta parsing/mapping, code export, conftest export support, pytest verification, coding prompt supplements.
  - Dependencies: schema models and adapter protocol.
  - Boundary: coding logic only.

### State and persistence

- `src/baps/state.py`
  - Purpose: domain schema and update semantics.
  - Responsibilities: model definitions, validation, update application, runtime decision application.
  - Dependencies: Pydantic.
  - Boundary: authoritative domain contract.

- `src/baps/state_service.py`
  - Purpose: mutation boundary service.
  - Responsibilities: load/apply/revalidate/save state updates.
  - Dependencies: state store + registry.
  - Boundary: only service path for durable mutation in runtime.

- `src/baps/state_store.py`
  - Purpose: persistence abstraction.
  - Responsibilities: state load/save protocol and JSON implementation.
  - Dependencies: filesystem + schema serialization.
  - Boundary: persistence transport, not domain logic.

### Models and projections

- `src/baps/models.py`
  - Purpose: model client abstractions and implementations.
  - Responsibilities: `ModelClient`, `FakeModelClient`, `OllamaClient`, tool-call payload types.
  - Dependencies: HTTP (`requests`) for Ollama.
  - Boundary: generation transport interface.

- `src/baps/northstar_projection.py`
  - Purpose: projection schema and rendering helpers.
  - Responsibilities: `StateView` model and projection input structures.
  - Dependencies: schema layer.
  - Boundary: model-facing projection structure.

## 4. Canonical Runtime Flow

### Lifecycle commands

- `init`
  1. resolve config,
  2. validate workspace is not initialized,
  3. create initial adapter-owned `State`,
  4. persist state JSON.

- `run`
  1. load persisted state,
  2. run bounded iterations.

- `init_and_run`
  1. initialize state,
  2. immediately run bounded iterations.

### Iteration flow

1. **CreateGame**
   - Adapter builds CreateGame `StateView`.
   - Core renders generic CreateGame prompt plus adapter supplement.
   - Model returns GameSpec JSON.
   - Core parses and validates GameSpec.
   - Adapter may normalize GameSpec.

2. **PlayGame**
   - Adapter builds PlayGame `StateView`.
   - Blue produces candidate `DeltaState`.
   - Red evaluates candidate.
   - Referee decides accept/revise/reject.
   - Bounded retries on rejected/invalid attempts.

3. **Integration**
   - Accepted delta is mapped to `StateUpdateProposal` by adapter.
   - `StateService` applies update as durable mutation.

4. **Export**
   - Adapter exports state-derived artifacts.
   - Adapter verification may execute (coding: pytest; document: consistency check).

5. **Evidence carry-forward**
   - Previous verification result is explicitly passed into subsequent CreateGame prompt context.

### Persistence

- Authoritative state path: `<workspace>/state/state.json`.
- Exported output is derived materialization only.

### Stop conditions

Implemented stop reasons include bounded-iteration completion, no usable CreateGame, no accepted PlayGame delta, and initialization-only flow.

## 5. Schema Documentation

### `State`

- Fields: `northstar`, `artifacts`.
- Invariants: non-empty northstar artifacts; artifact IDs unique; no overlap with NorthStar artifact IDs.
- Relationships: root authority for all runtime operations.
- Purpose: authoritative project condition.

### `NorthStar`

- Fields: `artifacts`.
- Invariants: non-empty.
- Relationships: nested inside `State`.
- Purpose: intent anchor included in authority model.

### `StateArtifact`

- Fields: `id`, `kind`.
- Invariants: non-empty `id`; `kind` discriminator.
- Relationships: base class for concrete artifact types.
- Purpose: artifact polymorphism.

### `DocumentArtifact`

- Fields: `id`, `kind="document"`, `sections`.
- Invariants: section titles non-empty.
- Relationships: concrete `StateArtifact` for document projects.
- Purpose: ordered section-based document state.

### `CodingArtifact`

- Fields: `id`, `kind="coding"`, `files`.
- Invariants: file paths unique and non-empty.
- Relationships: concrete `StateArtifact` for coding projects.
- Purpose: codebase file state.

### `Section`

- Fields: `title`, `body`.
- Invariants: title non-empty.
- Purpose: document unit.

### `CodeFile`

- Fields: `path`, `content`.
- Invariants: `path` non-empty.
- Purpose: coding file unit.

### `GameSpec`

- Fields: `objective`, `target_artifact_id`, `allowed_delta_type`, `success_condition`.
- Invariants: all non-empty.
- Relationships: binding contract for PlayGame.
- Purpose: bounded next move contract.

### `DeltaDocumentState`

- Fields: `artifact_id`, `operation="append_section"`, `payload.section`.
- Invariants: payload shape strict; section title/body non-empty.
- Purpose: document mutation proposal.

### `DeltaCodingState`

- Fields: `artifact_id`, `operation="write_file"`, `payload.file`.
- Invariants: payload shape strict; path/content non-empty.
- Purpose: coding mutation proposal.

### `RedFinding`

- Fields: `disposition` (`accept|revise|reject`), `rationale`.
- Purpose: adversarial review output.

### `RefereeDecision`

- Fields: `disposition` (`accept|revise|reject`), `rationale`.
- Purpose: game-local adjudication output.

### `StateUpdateProposal`

- Fields: `id`, `target`, `summary`, `payload`.
- Purpose: mutation request envelope consumed by `StateService`.

### `StateUpdateTarget`

- Fields: `artifact_id`.
- Purpose: identify mutation target artifact.

### `StateView`

- Fields: `id`, `projection_type`, `content`, `input_fingerprint`, `metadata`.
- Invariants: non-empty identifiers/content/fingerprint.
- Purpose: bounded model-facing projection.

### `ProjectionType`

- Values: `NORTH_STAR`.
- Purpose: projection classifier for view semantics.

## 6. Blackboard Status

### IMPLEMENTED OBSERVATION

- Runtime includes `_append_northstar_proposal_to_blackboard(...)` in `run.py` for NorthStar proposal logging.
- Filesystem location used: `<workspace>/blackboard/` with proposal JSONL logging.

### CANONICAL STATUS

- Blackboard is not part of the canonical execution spine.
- Blackboard is not authoritative state.
- Lifecycle mutation authority remains `State` via `StateService`.

### HISTORICAL / INACTIVE CONTEXT

- Blackboard appears as auxiliary process history/meta, not active runtime authority.

## 7. Artifact System

Artifact lifecycle (implemented):

1. **Initialization**: adapter creates initial artifact in `State`.
2. **StateView rendering**: adapter projects artifact to model-facing text.
3. **Delta parsing**: adapter parses model output to typed delta.
4. **Update mapping**: adapter converts accepted delta to `StateUpdateProposal`.
5. **State mutation**: `StateService` applies proposal into authoritative `State`.
6. **Export**: adapter materializes artifact content to filesystem.

Ownership:

- Adapters own artifact-specific render/parse/map/export behavior.
- Core runtime does not own artifact semantics.

Filesystem assumptions:

- State is persisted to workspace state JSON.
- Export paths are adapter-controlled under configured output path.
- Coding export writes file tree and root `conftest.py`; document export writes markdown file.

Constraints:

- Export is derived and one-way.
- Export verification is adapter-specific and evidence-only for subsequent planning.

## 8. Runtime Engine

Responsibilities:

- deterministic command handling,
- bounded iterative orchestration,
- typed parsing/validation,
- proposal integration via service boundary,
- export and optional verification.

Bounded attempts and retry behavior:

- PlayGame retries bounded (`max_attempts`, default 3).
- Invalid Blue outputs are rejected with feedback and retried within bound.

Integration path:

- `DeltaState` -> adapter mapping -> `StateUpdateProposal` -> `StateService.apply_update`.

Deterministic testing path:

- `FakeModelClient` drives deterministic prompt/response behavior.

Validation boundaries:

- Pydantic validation on schemas/deltas/specs.
- Prompt/output JSON shape checks in runtime and adapters.
- No semantic validator engine beyond explicit contract checks.

## 9. Roles and Prompt System

### CreateGame

- Core renders a generic CreateGame prompt with strict JSON contract and bounded-game constraints.
- Adapter supplements add project-specific rules (and verification evidence when available).

### Blue prompt flow

- Generic Blue core prompt from `render_blue_prompt_core(...)`.
- Adapter supplement injects delta-shape and project-specific constraints.

### Red prompt

- Core Red prompt evaluates candidate against GameSpec and state view context.
- Adapter supplement injects type-specific evaluation guidance.

### Referee prompt

- Core Referee prompt adjudicates Red + candidate + GameSpec context.
- Adapter supplement injects type-specific adjudication guidance.

### Model layer

- `ModelClient`: interface.
- `FakeModelClient`: deterministic testing.
- `OllamaClient`: live generation client.

### Current limitations (implemented)

- no tool execution subsystem in canonical runtime loop,
- no true multi-agent scheduler,
- prompt-only role execution,
- limited semantic validation beyond explicit contracts.

## 10. Testing Strategy

Testing philosophy:

- contract-first deterministic testing of runtime boundaries and parser behavior.

Deterministic execution:

- `FakeModelClient` provides queued responses and prompt capture.

Coverage areas:

- schema validation and update semantics,
- state persistence and service mutation,
- runtime command and loop behavior,
- adapter boundary behavior,
- prompt construction and parser constraints,
- export/verification paths.

Why deterministic testing matters here:

- runtime correctness depends on strict contracts at orchestration boundaries,
- deterministic tests prevent regression in architecture invariants,
- tests guard against drift from adapter ownership and canonical spine.

## 11. Architectural Invariants

### Enforced / Implemented

1. `State` is authoritative and persisted JSON.
2. `StateView` is a text projection model.
3. `NorthStar` is inside `State`.
4. Adapter owns project-specific mechanics.
5. `StateService` is runtime mutation boundary.
6. Core orchestration remains project-type generic.
7. Export is one-way from `State`.
8. Schema validation is enforced via typed models and runtime checks.
9. Deterministic tests enforce boundary contracts.

### Conceptual (not enforced as separate engine)

- richer semantic quality adjudication,
- tool-execution role augmentation,
- blackboard-centered coordination.

## 12. Current Architectural Direction

### IMPLEMENTED DIRECTION

- Strengthening adapter-owned behavior and prompt supplements.
- Strengthening bounded retry/error-handling in PlayGame.
- Increasing contract tests for anti-drift boundaries.
- Verification evidence propagation into CreateGame.

### CONCEPTUAL DIRECTION

- adapter expansion for additional project types,
- stronger tool boundaries,
- blackboard reintegration as non-authoritative process context.

### HISTORICAL / INACTIVE DIRECTION

- non-canonical blackboard artifacts remain auxiliary and not lifecycle authority.

## 13. Current Limitations

1. Blackboard runtime is not part of canonical spine.
2. Role execution is prompt-only.
3. Active delta space is limited to document append and coding write-file.
4. No active tool execution subsystem in canonical runtime loop.
5. No scheduler for parallel/multi-agent role execution.
6. Role model is bounded and sequential.
7. Semantic validation remains limited to explicit constraints and typed checks.

## 14. Suggested Next Milestones

Additive milestones consistent with current architecture:

1. Formalize blackboard as append-only, non-authoritative run-history interface.
2. Introduce explicit tool boundary contracts for role execution.
3. Add adapter-level validation hooks for stricter export/verification invariants.
4. Add role envelope contracts for consistent evidence and rationale structure.
5. Expand contract-test suite for canonical spine and anti-drift guarantees.

## 15. Developer Workflow

Expected workflow:

1. Keep changes additive and boundary-preserving.
2. Treat `SYSTEM.md` as normative contract and `ARCHITECTURE.md` as implementation evidence.
3. Implement project-specific behavior in adapters, not in core orchestration.
4. Add deterministic tests for any new contract behavior.
5. Run `uv run pytest` before finalization.

Development posture:

- preserve canonical spine,
- avoid introducing competing runtimes,
- maintain `State` authority and `StateView` prompt boundary.

## 16. Glossary

- **State**: Authoritative project condition persisted as JSON.
- **NorthStar**: Intent artifact(s) embedded inside authoritative state.
- **StateView**: Bounded text projection for model-facing prompts.
- **GameSpec**: Bounded task contract for one PlayGame cycle.
- **DeltaState**: Proposed project mutation from role execution.
- **artifact**: Typed state unit (document/coding) within `State`.
- **adapter**: ProjectTypeAdapter implementation owning project-specific behavior.
- **RedFinding**: Adversarial reviewer decision output.
- **RefereeDecision**: Game-local adjudication output.
- **StateUpdateProposal**: Integration envelope for mutation through service.
- **runtime**: Lifecycle orchestration path (`init`, `run`, `init_and_run`).
- **ModelClient**: Generation interface for model backends/test doubles.
- **export**: One-way materialization of state to filesystem outputs.
- **canonical spine**: `config/NorthStar -> State -> StateView -> CreateGame -> GameSpec -> PlayGame -> DeltaState -> StateUpdateProposal -> StateService -> export`.

## System Contract Alignment

Checked against `SYSTEM.md`:

1. `State != StateView`: aligned.
2. Prompts consume `StateView` context in runtime prompts: aligned.
3. Core orchestration generic; project specifics adapter-owned: aligned.
4. Adapter ownership preserved for create/view/parse/map/export/verify: aligned.
5. `export != state`: aligned.
6. Blackboard inactive as canonical authority: aligned.

Observed mismatch/nuance:

- `run.py` includes auxiliary blackboard proposal logging for NorthStar update proposals. This remains outside canonical authority and does not supersede `State`.
