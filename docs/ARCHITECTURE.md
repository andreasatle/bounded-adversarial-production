# ARCHITECTURE.md

## 1. Project Overview

### Purpose
`bounded-adversarial-production` (`baps`) is a Python framework for bounded, model-driven project evolution through typed state, typed deltas, and explicit mutation boundaries.

### Current philosophy (IMPLEMENTED)
- `State` is authoritative and persisted.
- models consume projected textual `StateView`, not authoritative state internals.
- project-specific behavior is adapter-owned.
- orchestration is lifecycle-driven (`init`, `run`, `init_and_run`) and bounded by configured limits.

### Current architectural direction (IMPLEMENTED)
Canonical runtime:

`config/NorthStar -> State -> StateView -> CreateGame -> GameSpec -> PlayGame -> DeltaState -> StateUpdateProposal -> StateService -> export`

### Bounded adversarial production as currently implemented
Per runtime iteration:
- CreateGame proposes a bounded `GameSpec`.
- PlayGame executes Blue -> Red -> Referee with bounded attempts.
- accepted candidate delta is mapped to `StateUpdateProposal`.
- `StateService` validates/applies/persists.
- adapter exports state-derived output.

### Implemented vs conceptual vs historical
- IMPLEMENTED: adapter-driven lifecycle/runtime above.
- CONCEPTUAL: blackboard-centric operational memory reintegration, richer tooling/scheduling.
- HISTORICAL/INACTIVE: legacy alternate runtime paths are not active in canonical `baps-run` flow.

---

## 2. Current System Capabilities

### Schemas (`src/baps/state.py`)
Purpose:
- define authoritative state, artifact types, game contracts, deltas, decisions, and update proposals.

Key classes/functions:
- `State`, `NorthStar`, `StateArtifact`, `DocumentArtifact`, `CodingArtifact`
- `Section`, `CodeFile`
- `GameSpec`
- `DeltaState`, `DeltaDocumentState`, `DeltaCodingState`
- `RedFinding`, `RefereeDecision`, `PlayGameRuntime`
- `StateUpdateProposal`, `StateUpdateTarget`
- `apply_state_update`, `validate_state_artifacts`, `fingerprint_state`

Limitations:
- active structured ops are `append_section` (document) and `write_file` (coding).

Dependencies:
- Pydantic v2

Boundary:
- authoritative contracts and mutation semantics.

### Runtime (`src/baps/run.py`)
Purpose:
- lifecycle command entrypoint and canonical orchestration.

Key functions:
- lifecycle/config: `main`, `resolve_run_config`, `_initialize_project`, `_load_project_service`
- loop: `_run_project_iterations`
- game stages: `create_game`, `play_game`
- model parsing/validation helpers and prompts

Limitations:
- prompt-driven role execution only.
- no active blackboard append/query in canonical runtime.

Dependencies:
- adapters, state service/store, model clients.

Boundary:
- project-type generic orchestration; no project-specific mechanics should be embedded in core flow.

### Adapters (`src/baps/project_adapter.py`, `document_adapter.py`, `coding_adapter.py`)
Purpose:
- own project-type mechanics behind `ProjectTypeAdapter`.

Implemented project types:
- `document`
- `coding`

Adapter-owned behaviors:
- initial state creation
- CreateGame and PlayGame `StateView` rendering
- Blue prompt supplement
- delta parsing
- delta->proposal mapping
- export

Limitations:
- only two adapters implemented.

Boundary:
- project specifics live here; core orchestration dispatches via adapter interface.

### StateView / Projection (`src/baps/northstar_projection.py`)
Purpose:
- immutable model-facing projection object.

Key models:
- `StateView`, `ProjectionType`
- projection input/renderer models for northstar projection helpers

Rendering rules in active runtime:
- adapter renderers provide textual `StateView.content` with explicit delimiters/sections.

Boundary:
- prompt input surface, not authoritative state.

### Model Layer (`src/baps/models.py`)
Purpose:
- model transport abstraction.

Classes:
- `ModelClient` (base)
- `FakeModelClient` (deterministic testing)
- `OllamaClient` (HTTP calls)

Limitations:
- no tool execution boundary in model layer.

### Testing (`tests/*`)
Purpose:
- deterministic contract coverage of runtime, schemas, adapters, store/service, and projection helpers.

Key characteristics:
- extensive `FakeModelClient` use and monkeypatch-driven deterministic flows.
- strict validation/error-path assertions.

---

## 3. Repository Structure

### Core orchestration modules

#### `src/baps/run.py`
- Purpose: CLI + lifecycle + canonical execution loop.
- Responsibilities: config resolution, command preconditions, CreateGame/PlayGame orchestration, integration/export sequencing, stop conditions, debug surfaces.
- Dependencies: adapter registry/dispatch, state service/store, model clients, schemas.
- Boundary: generic orchestration only.

#### `src/baps/project_adapter.py`
- Purpose: adapter protocol + registry/resolve + shared Blue prompt core.
- Responsibilities: define adapter contract and dynamic adapter resolution.
- Dependencies: `StateView`, state/game proposal models.
- Boundary: interface and dispatch only.

### Adapter mechanics modules

#### `src/baps/document_adapter.py`
- Purpose: document project mechanics.
- Responsibilities: document state init, state view rendering, delta parse/map, markdown export.
- Dependencies: document/cross-state models, Blue prompt core.
- Boundary: all document-specific behavior.

#### `src/baps/coding_adapter.py`
- Purpose: coding project mechanics.
- Responsibilities: coding state init, state view rendering, delta parse/map, file export.
- Dependencies: coding/cross-state models, Blue prompt core.
- Boundary: all coding-specific behavior.

### State and persistence modules

#### `src/baps/state.py`
- Purpose: authoritative schema and mutation logic.
- Responsibilities: model validation, update application, artifact registry, runtime decision state models.
- Boundary: state semantics and state transitions.

#### `src/baps/state_service.py`
- Purpose: mutation boundary service.
- Responsibilities: load/validate/apply/validate/save sequence.
- Boundary: canonical mutation gateway.

#### `src/baps/state_store.py`
- Purpose: persistence backend contract and JSON implementation.
- Responsibilities: load/save `State` at a file path.
- Boundary: storage mechanism.

### Model/projection modules

#### `src/baps/models.py`
- Purpose: model client abstractions and Ollama transport.

#### `src/baps/northstar_projection.py`
- Purpose: projection/view models and renderer utilities.

---

## 4. Canonical Runtime Flow

### Lifecycle commands

#### `init`
1. parse config/spec.
2. ensure state file does not exist.
3. adapter creates initial state.
4. save initial state to `<workspace>/state/state.json`.

#### `run`
1. parse config/spec.
2. ensure state file exists.
3. load persisted state.
4. run bounded iterations.

#### `init_and_run`
1. perform `init`.
2. perform `run` immediately in same invocation.

### Iteration flow (`_run_project_iterations`)
Per iteration:
1. **CreateGame**
   - adapter builds CreateGame `StateView` from current `State` + config.
   - prompt -> model -> parse/validate -> `GameSpec`.
2. **PlayGame**
   - adapter builds PlayGame `StateView`.
   - Blue model call -> adapter delta parse.
   - Red model evaluation.
   - Referee model decision.
   - accepted candidate tracked in `PlayGameRuntime` and returned.
3. **Integration**
   - adapter maps `DeltaState` -> `StateUpdateProposal`.
   - `StateService.apply_update` validates/applies/persists.
4. **Export**
   - adapter exports from updated `State` to output path.

### Persistence
- canonical persisted state: `<workspace>/state/state.json`.
- output files are materialized projections; they are not canonical state.

### Stop conditions
- CreateGame returns explicit no-new-game signal.
- PlayGame returns no delta.
- no state change after update.
- iteration limit reached.

---

## 5. Schema Documentation

### `StateArtifact`
- Fields: `id`, `kind`.
- Validation: non-empty strings.
- Purpose: base artifact identity/type.

### `DocumentArtifact(StateArtifact)`
- Fields: `kind="document"`, `sections: tuple[Section, ...]`.
- Purpose: canonical document state.

### `CodingArtifact(StateArtifact)`
- Fields: `kind="coding"`, `files: tuple[CodeFile, ...]`.
- Purpose: canonical coding/file state.

### `Section`
- Fields: `title`, `body`.
- Validation: non-empty strings.

### `CodeFile`
- Fields: `path`, `content`.
- Validation: non-empty strings.

### `NorthStar`
- Fields: `artifacts`.
- Validation: unique artifact ids.
- Relationship: embedded in `State.northstar`.

### `State`
- Fields: `northstar`, `artifacts`.
- Validation:
  - artifact coercion to known artifact models
  - unique state artifact ids
  - no id overlap between northstar and state artifacts
- Purpose: authoritative current project condition.

### `GameSpec`
- Fields: `objective`, `target_artifact_id`, `allowed_delta_type`, `success_condition`.
- Validation: all non-empty.
- Purpose: bounded task contract for PlayGame.

### `DeltaDocumentState`
- Inherits: `DeltaState`.
- Fields: `artifact_id`, `operation="append_section"`, `payload.section`.
- Purpose: proposed document change.

### `DeltaCodingState`
- Inherits: `DeltaState`.
- Fields: `artifact_id`, `operation="write_file"`, `payload.file`.
- Purpose: proposed coding/file change.

### `RedFinding`
- Fields: `disposition`, `rationale`.
- Validation: non-empty rationale.

### `RefereeDecision`
- Fields: `disposition`, `rationale`.
- Validation: non-empty rationale.

### `StateUpdateTarget`
- Fields: `artifact_id`, optional `section`.
- Validation: non-empty values when present.

### `StateUpdateProposal`
- Fields: `id`, `target`, `summary`, `payload`, optional `base_state_fingerprint`.
- Validation: non-empty identifiers/summary and optional fingerprint when present.

### `StateView` (`northstar_projection.py`)
- Fields: `id`, `projection_type`, `content`, `input_fingerprint`, `metadata`.
- Validation: non-empty key string fields.
- Config: frozen.
- Purpose: immutable model-facing projection.

### `ProjectionType`
- Enum currently includes `NORTH_STAR`.

---

## 6. Blackboard Status

### Existing files
- `blackboard/events.jsonl`
- `blackboard/adversarial-events.jsonl`
- `blackboard/ollama-adversarial-events.jsonl`
- `blackboard/play-game-events.jsonl`

### Current status
- HISTORICAL/INACTIVE relative to canonical `baps-run` flow.
- canonical lifecycle/orchestration does not append/query blackboard in active runtime path.

### Separation
- `State` remains authoritative.
- blackboard data is not part of canonical mutation/persistence path.

Observation:
- docs discuss blackboard conceptually; code does not currently wire it into active lifecycle execution.

---

## 7. Artifact System

### Canonical lifecycle per artifact
1. initialization via adapter `create_initial_state`
2. CreateGame/PlayGame `StateView` rendering via adapter
3. Blue delta parsing via adapter
4. delta->proposal mapping via adapter
5. proposal application via `StateService`
6. state->filesystem export via adapter

### Adapter ownership
- document mechanics in `document_adapter.py`
- coding mechanics in `coding_adapter.py`

### Filesystem assumptions
- document export writes markdown file at configured output path.
- coding export writes one file per `CodeFile.path` under configured output directory.
- parent directories are created as needed.

### Constraints
- export is one-way from `State`.
- output files are not used as source of truth for authoritative state.

---

## 8. Runtime Engine

### Responsibilities
- lifecycle gating (`init`/`run`/`init_and_run` preconditions)
- project-type generic orchestration
- bounded CreateGame/PlayGame iterations
- integration through `StateService`
- export and stop-reason signaling

### Bounded attempts and retry
- `play_game` retries Blue/Red/Referee attempts up to `max_attempts` (default 3).
- invalid Blue output is treated as attempt rejection with feedback.

### Integration path
- accepted delta mapped by adapter to `StateUpdateProposal`.
- `StateService.apply_update` performs load/validate/apply/validate/save.

### Deterministic testing path
- `FakeModelClient` and monkeypatched helpers drive deterministic branch coverage.

### Validation boundaries
- schema-level validation via Pydantic models.
- strict prompt output parsing and key checks in runtime parsers.
- adapter allowed delta type and target artifact consistency checks.

---

## 9. Roles and Prompt System

### CreateGame prompt
- rendered in `run.py` using goal + adapter-provided CreateGame `StateView` + contract constraints.
- expects strict JSON `GameSpec` or explicit no-game JSON sentinel.

### Blue prompt flow
- generic core prompt: `project_adapter.render_blue_prompt_core`.
- adapter supplements:
  - document: append-section delta shape/rules
  - coding: write-file delta shape/rules

### Red prompt
- prompt-only evaluator of objective/success_condition fit and quality/completeness concerns.

### Referee prompt
- prompt-only decision authority for game-local `accept|revise|reject`.
- explicitly not final integration authority.

### Model layer
- `ModelClient` base interface.
- `FakeModelClient` deterministic tests.
- `OllamaClient` live HTTP generation.

### Current limitations
- no tool execution subsystem.
- no multi-agent scheduler.
- role execution is prompt-only sequential calls.
- limited semantic validation in core (primarily structural/schema and explicit checks).

---

## 10. Testing Strategy

### Philosophy
- deterministic, contract-first testing across state/runtime/adapter boundaries.

### Deterministic execution approach
- fake responses and monkeypatching isolate orchestration logic from model variability.

### What is covered
- schema validation and mutation rules (`tests/test_state.py`)
- runtime lifecycle/orchestration/parsing/prompt contracts (`tests/test_run.py`)
- model client behavior and error handling (`tests/test_models.py`)
- state store/service behavior (`tests/test_state_store.py`, `tests/test_state_service.py`)
- projection model behavior (`tests/test_northstar_projection.py`)

Why deterministic tests matter:
- ensure runtime contracts stay stable despite nondeterministic model behavior in production.

---

## 11. Architectural Invariants

### Enforced (code-backed)
1. `State` is authoritative and persisted as JSON.
2. `NorthStar` is inside `State`.
3. prompts consume projected `StateView` text surfaces.
4. project-specific mechanics are adapter-owned.
5. runtime orchestration dispatches by project type / delta type through adapter resolution.
6. `StateService` is canonical mutation boundary.
7. export is one-way from `State` to output files.
8. schema validation is enforced via Pydantic models and runtime parse checks.
9. deterministic tests enforce runtime contracts.

### Conceptual (not fully enforced in active runtime)
1. blackboard append-only runtime memory integrated with canonical flow.
2. broader governance/replay semantics described in docs but not active in orchestration.

---

## 12. Current Architectural Direction

### IMPLEMENTED direction
- adapter expansion pattern (`document`, `coding`)
- bounded game iterations and bounded role attempts
- explicit state mutation boundary (`StateService`)

### CONCEPTUAL direction (observed in docs/code signals)
- future tool boundary integration
- possible blackboard reintegration
- richer role envelopes/coordination semantics

### HISTORICAL/INACTIVE
- blackboard event files as historical traces not used by canonical runtime.

---

## 13. Current Limitations

1. blackboard runtime is inactive in canonical lifecycle flow.
2. role execution is prompt-only and sequential.
3. delta operations are currently limited (`append_section`, `write_file`).
4. no tool system for validated external actions.
5. no multi-agent scheduler.
6. semantic quality evaluation is largely role-prompt driven, not independently tooled.
7. some compatibility helper surfaces remain in `run.py` for test continuity.

---

## 14. Suggested Next Milestones

1. reintroduce blackboard as append-only run meta/history in canonical spine.
2. define explicit tool request/approval boundary for role execution.
3. add adapter-level semantic validation hooks prior to integration.
4. standardize role result envelopes and provenance fields.
5. add shared adapter contract tests for future project types.

All milestones are additive and preserve current boundaries.

---

## 15. Developer Workflow

### Tests
- run full suite: `uv run pytest`
- run targeted suites as needed during focused changes.

### Development flow
1. change smallest relevant module boundary.
2. update/add deterministic tests.
3. run full suite.
4. keep core orchestration generic and project behavior adapter-owned.

### Additive philosophy
- extend via typed models + adapter contract.
- avoid parallel execution paths.
- preserve state/view boundary and mutation boundary.

---

## 16. Glossary

- **State**: authoritative current project condition persisted as JSON.
- **NorthStar**: directional intent stored as artifacts in `State.northstar`.
- **StateView**: immutable textual projection for model prompts.
- **GameSpec**: bounded task contract for PlayGame.
- **DeltaState**: proposed state change produced by PlayGame.
- **Artifact**: typed unit of state (`DocumentArtifact`, `CodingArtifact`, etc.).
- **Adapter**: `ProjectTypeAdapter` implementation owning project-specific mechanics.
- **RedFinding**: Red role evaluation output.
- **RefereeDecision**: Referee role decision output.
- **StateUpdateProposal**: integration request applied through `StateService`.
- **Runtime**: lifecycle and iteration orchestration in `run.py`.
- **ModelClient**: model generation interface (`FakeModelClient`, `OllamaClient`).
- **Export**: one-way materialization from authoritative state to output files.
- **Canonical spine**: `config/NorthStar -> State -> StateView -> CreateGame -> GameSpec -> PlayGame -> DeltaState -> StateUpdateProposal -> StateService -> export`.

---

## System Contract Alignment (with `SYSTEM.md`)

### Verified alignments
1. `State != StateView` is explicit and preserved.
2. prompts consume `StateView` surfaces, not authoritative state as stateview replacement.
3. core orchestration is adapter-dispatched and project-type generic by contract.
4. adapter ownership is explicit for project-specific mechanics.
5. export is materialization output, not canonical state.
6. blackboard is documented as inactive in canonical runtime.

### Observations / mismatches to monitor
1. `run.py` still carries compatibility/helper symbol surfaces that are broader than strict minimal orchestration API.
2. debug payloads may include `state.model_dump(...)` for observability; this is separate from model-facing `StateView` prompt contract and should remain non-authoritative for prompts.
