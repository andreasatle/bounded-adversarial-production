# ARCHITECTURE.md

## 1. Project Overview

### Purpose
`bounded-adversarial-production` (`baps`) is a Python framework for running bounded, iterative state updates driven by model-generated game specifications and deltas.

The current executable product is the `baps-run` CLI lifecycle:

- `baps init`
- `baps run`
- `baps init_and_run`

### Current philosophy in code
The current implementation enforces these practical principles:

- authoritative state is persisted (`State` JSON) under `workspace/state/state.json`
- model-facing context is projected as textual `StateView.content`
- project-type-specific mechanics are delegated to `ProjectTypeAdapter`
- update application goes through `StateService` + `apply_state_update`
- output export is one-way from `State` to filesystem output

### Current architectural direction
The active direction visible in code is:

- adapter-based multi-project support (`document`, `coding`)
- model-driven `CreateGame` and `PlayGame`
- bounded attempts in `PlayGame`
- explicit state integration/persistence boundary

### “Bounded adversarial production” in practice (current)
In the current code, bounded adversarial behavior is implemented as a fixed Blue/Red/Referee sequence per attempt:

- Blue proposes a typed delta JSON
- Red evaluates candidate quality and objective fit
- Referee decides `accept|revise|reject`
- runtime keeps best accepted delta (`PlayGameRuntime.current_best_delta`)

This is bounded by `max_attempts` in `play_game` and `max_iterations` in CLI run loop.

### Implemented vs aspirational
Implemented now:

- CLI lifecycle commands
- adapter-dispatched state creation, state views, delta parsing, integration mapping, export
- model clients (`FakeModelClient`, `OllamaClient`)
- Pydantic schema validation for state/deltas/game decisions

Conceptual/aspirational (not implemented as active modules):

- a first-class blackboard runtime subsystem in active orchestration
- multi-agent orchestration beyond Blue/Red/Referee prompt sequence
- tool execution subsystem

---

## 2. Current System Capabilities

### Schemas (`src/baps/state.py`)
Purpose:

- define authoritative state, project artifacts, game contracts, deltas, and update proposals

Important models/functions:

- `StateArtifact`, `DocumentArtifact`, `CodingArtifact`
- `Section`, `CodeFile`
- `State`, `NorthStar`
- `GameSpec`, `DeltaDocumentState`, `DeltaCodingState`, `RedFinding`, `RefereeDecision`
- `StateUpdateProposal`, `StateUpdateTarget`
- `apply_state_update`, `validate_state_artifacts`, `fingerprint_state`

Limitations:

- only `append_section` and `write_file` operations are implemented for structured mutation
- registry adapters for custom artifact kinds are minimal (simple validate/project behavior)

Relationships:

- consumed by adapters and `run.py`
- persisted via `JsonStateStore`
- orchestrated through `StateService`

### Blackboard
Purpose in repository currently:

- stored event traces under `blackboard/*.jsonl`

Current implementation status:

- no active `src/baps/blackboard.py` runtime module in canonical spine
- blackboard files are data artifacts, not orchestrated by `baps-run`

Observation:

- architecture documents discuss blackboard semantics, but canonical CLI path does not append/query these files.

### Artifacts
Purpose:

- represent project condition in `State`
- `DocumentArtifact` stores ordered sections
- `CodingArtifact` stores ordered files

Important mechanics:

- adapter-specific rendering to model-facing `StateView`
- adapter-specific export to filesystem
- generic update operations in `apply_state_update`

Limitations:

- no artifact versioning or snapshot subsystem wired into canonical spine

### Runtime
Purpose:

- execute lifecycle + iteration loop in `run.py`

Important functions:

- lifecycle: `main`, `_initialize_project`, `_load_project_service`, `_run_project_iterations`
- synthesis: `create_game`, `play_game`
- integration: `_derive_state_update_from_delta` + `StateService.apply_update`

Limitations:

- no explicit blackboard append/query in active path
- no external tool calls beyond model generation

### Roles
Current role behavior is prompt-driven inside `run.py`:

- Blue prompt: adapter-provided and parsed by adapter
- Red prompt: `_render_red_prompt`
- Referee prompt: `_render_referee_prompt`

No separate active `roles.py` module exists in canonical path.

### Prompt rendering
Implemented via direct string renderers:

- CreateGame: `_render_create_game_prompt`
- Blue core helper: `project_adapter.render_blue_prompt_core`
- Blue project-specific supplements: adapter methods
- Red/Referee: run-local renderers

### Model abstraction
`src/baps/models.py`:

- `ModelClient` interface
- `FakeModelClient` deterministic test support
- `OllamaClient` HTTP API integration

### Ollama integration
Through `OllamaClient.generate()`:

- endpoint: `{base_url}/api/generate`
- payload includes model, prompt, `stream=False`
- error normalization for HTTP/URL failures

### Deterministic testing
Capabilities:

- extensive deterministic coverage for schemas, run orchestration, parsing, adapters
- fake model responses drive repeatable tests without external model dependency

### Demo game execution
Canonical demo execution is live via `baps-run` and example specs:

- `examples/document-project.yaml`
- `examples/coding-project.yaml`

---

## 3. Repository Structure

### Top-level map (current)

- `src/baps/`
  - `run.py`: CLI + lifecycle + orchestration
  - `project_adapter.py`: adapter protocol/registry/dispatch + Blue prompt core
  - `document_adapter.py`: document mechanics (state views, delta parsing/mapping, export)
  - `coding_adapter.py`: coding mechanics (state views, delta parsing/mapping, export)
  - `state.py`: core schemas + state update logic + artifact registry
  - `state_service.py`: load/validate/apply/save service boundary
  - `state_store.py`: JSON persistence
  - `models.py`: model client abstractions and Ollama transport
  - `northstar_projection.py`: generic `StateView`/projection models + renderer
- `tests/`
  - `test_run.py`, `test_state.py`, `test_models.py`, `test_state_service.py`, `test_state_store.py`, `test_northstar_projection.py`
- `examples/`
  - project specs for CLI runs
- `blackboard/`
  - JSONL event logs (data artifacts)
- `docs/`
  - architecture/system/planning docs

### Responsibility boundaries

- `run.py`: lifecycle and loop orchestration only
- adapters: project-specific mechanics
- `state.py`: canonical data contracts and mutation logic
- `state_service.py`/`state_store.py`: persistence and validation boundary
- `models.py`: model transport abstraction

---

## 4. Core Runtime Flow

### Lifecycle commands

1. `init`
- resolve config
- ensure state file does not already exist
- `create_state` via adapter
- persist initial state via `JsonStateStore.save`

2. `run`
- ensure state file exists
- load current state via `StateService`
- execute bounded iterations

3. `init_and_run`
- run init sequence
- immediately run bounded iterations

### Iteration sequence (`_run_project_iterations`)

Per iteration:

1. `create_game(config, current_state, adapter)`
- adapter builds CreateGame `StateView`
- prompt rendered with goal + state view + constraints
- model output parsed to `GameSpec` (or explicit no-game signal)
- artifact and delta-type contract checks enforced

2. `play_game(current_state, game_spec, adapter)`
- adapter builds play-time `StateView`
- bounded attempts (default 3)
- Blue generates candidate delta JSON
- adapter parses delta
- Red evaluates candidate
- Referee decides disposition
- runtime tracks accepted best delta

3. integration
- map delta -> `StateUpdateProposal` using adapter
- `StateService.apply_update` validates/applies/saves

4. export
- `adapter.export_state(updated_state, output_path, artifact_id)`
- output changed flag tracked

5. loop continuation/stop
- stop on no game, no delta, no state change, or iteration limit

### Persistence details

- authoritative state path: `<workspace>/state/state.json`
- load/save only through `StateService`/`StateStore` in canonical path

### Blackboard/event recording status

- no active event writes in canonical `run.py` flow
- existing `blackboard/*.jsonl` files are not updated by active run loop

---

## 5. Schema Documentation

### Artifact and state models (`state.py`)

- `StateArtifact`
  - fields: `id`, `kind`
  - validators: non-empty strings

- `DocumentArtifact(StateArtifact)`
  - `kind="document"`
  - `sections: tuple[Section, ...]`

- `CodingArtifact(StateArtifact)`
  - `kind="coding"`
  - `files: tuple[CodeFile, ...]`

- `Section`
  - `title`, `body` non-empty

- `CodeFile`
  - `path`, `content` non-empty

- `NorthStar`
  - `artifacts: tuple[SerializeAsAny[StateArtifact], ...]`
  - unique artifact IDs enforced
  - pre-validation coercion supports document/coding/base artifacts

- `State`
  - `northstar: NorthStar`
  - `artifacts: tuple[SerializeAsAny[StateArtifact], ...]`
  - unique IDs in state artifacts
  - disjointness between northstar IDs and state artifact IDs

Why they exist:

- preserve typed authoritative state with explicit invariants and polymorphic artifact support

### Delta and game models

- `DeltaState` base (`artifact_id` non-empty)
- `DeltaDocumentState` (`operation="append_section"`, payload `AppendSectionDelta`)
- `DeltaCodingState` (`operation="write_file"`, payload `WriteFileDelta`)
- `GameSpec`
  - `objective`, `target_artifact_id`, `allowed_delta_type`, `success_condition` (all non-empty)

Why:

- enforce strict input/output contracts between CreateGame/PlayGame/integration

### Review/decision runtime models

- `RedFinding`, `RefereeDecision`
  - `disposition: accept|revise|reject`
  - `rationale` non-empty
- `PlayGameRuntime`
  - `current_best_delta: DeltaState | None`

Why:

- represent bounded in-memory decision state without mutating authoritative project state

### Update models

- `StateUpdateTarget`
  - `artifact_id` required, optional non-empty `section`
- `StateUpdateProposal`
  - `id`, `target`, `summary`, `payload`, optional `base_state_fingerprint`

Why:

- normalize integration boundary from accepted delta to authoritative state mutation request

### Projection/view models (`northstar_projection.py`)

- `StateView` (frozen)
  - `id`, `projection_type`, `content`, `input_fingerprint`, `metadata`
- `ProjectionType` currently contains `NORTH_STAR`

Why:

- enforce “model sees projected text, not mutable state object internals”

---

## 6. Blackboard/Event System

### Append-only philosophy
Documented in repo docs (`docs/SYSTEM.md`) but not actively enforced by a runtime subsystem in canonical code path.

### Current implementation

- blackboard data files exist:
  - `blackboard/events.jsonl`
  - `blackboard/adversarial-events.jsonl`
  - `blackboard/ollama-adversarial-events.jsonl`
  - `blackboard/play-game-events.jsonl`
- no active module in `src/baps` reads/writes these during `baps-run` lifecycle

### Event querying/lifecycle

- no in-code query API or lifecycle manager currently wired into canonical execution

### Intended future role (inferred from docs, not active code)

- docs indicate blackboard as historical/process memory
- canonical CLI currently operates without this integration

Observation:

- blackboard semantics are documented conceptually, but implementation is currently decoupled from the active spine.

---

## 7. Artifact System

### Lifecycle in canonical path

1. initialize artifact in `create_initial_state` (adapter)
2. build model-facing views from artifact state (adapter)
3. parse model-produced delta (adapter)
4. map delta to `StateUpdateProposal` (adapter)
5. apply update through `StateService` + `apply_state_update`
6. export artifact state to output path (adapter)

### Adapter responsibilities

- `DocumentProjectAdapter`
  - state init with document artifact
  - create-game and play-game StateView rendering
  - parse document delta JSON
  - map to append-section update proposal
  - export markdown report from sections

- `CodingProjectAdapter`
  - state init with coding artifact
  - create-game and play-game StateView rendering
  - parse coding delta JSON
  - map to write-file update proposal
  - export files under output directory

### Filesystem assumptions

- document export writes single markdown file at configured `output_path`
- coding export treats `output_path` as directory root and writes each file path underneath
- parent directories are created as needed

Constraints:

- export is one-way from authoritative state
- output files are not treated as source of truth for state reconstruction

---

## 8. Runtime Engine

### Responsibilities (`run.py`)

- parse lifecycle command and config
- enforce init/run preconditions
- dispatch project adapter
- run bounded create/play/integrate/export iterations
- print structured run summary fields

### Guardrails and validation

- strict non-empty config field checks
- project type resolution errors (`git` explicitly not implemented)
- strict JSON parsing for model outputs
- strict key-set validation for generated JSON structures
- strict adapter/delta-type match checks

### Retry behavior

- `play_game(..., max_attempts=3)` bounded retry loop
- Blue validation failures become attempt rejections with feedback
- Red and Referee evaluated per attempt

### Current deterministic execution approach

- production path uses model clients (default `OllamaClient`)
- deterministic behavior in tests is achieved with `FakeModelClient` and monkeypatched generators

---

## 9. Roles and Prompt System

### Prompt-driven roles

- CreateGame prompt:
  - derives one coherent `GameSpec` from goal + projected state + NorthStar
  - supports explicit no-game JSON response

- Blue prompt:
  - generic core from `render_blue_prompt_core`
  - project-specific schema/mechanics appended by adapter

- Red prompt:
  - evaluates candidate delta against objective/success_condition and quality criteria

- Referee prompt:
  - game-local accept/revise/reject authority
  - explicitly states it is not final state integration authority

### Clients

- `FakeModelClient`: deterministic fixed-response queue + prompt capture
- `OllamaClient`: HTTP transport abstraction

### Current limitations

- no tool invocation protocol in prompts/runtime
- no multi-agent scheduling beyond sequential Blue/Red/Referee calls
- no external verification of generated content quality beyond schema + role judgments

---

## 10. Testing Strategy

### Philosophy

- deterministic, schema-first, boundary-focused tests
- heavy use of fake/model stubs to make orchestration reproducible

### Coverage areas

- `test_state.py`
  - validation invariants, update semantics, runtime decision behavior
- `test_run.py`
  - lifecycle command behavior, config resolution, prompts/parsing, adapters, export, iteration flow
- `test_models.py`
  - model client behavior and error paths
- `test_state_service.py` / `test_state_store.py`
  - persistence and update boundary behavior
- `test_northstar_projection.py`
  - projection/render/fingerprint invariants

Why deterministic tests matter here:

- model outputs are probabilistic in production; deterministic tests enforce contract correctness independently of live model variance.

---

## 11. Architectural Invariants (Enforced by Code)

- `State` is schema-validated and persisted as JSON (`JsonStateStore`).
- `northstar.artifacts` and `state.artifacts` IDs are unique and disjoint.
- `GameSpec`, deltas, findings, and decisions require non-empty critical fields.
- state mutations in canonical run path go through `StateService.apply_update`.
- model-facing prompt context uses `StateView.content` text.
- adapter dispatch controls project-specific mechanics (`document`, `coding`).
- lifecycle preconditions enforce init/run state-file existence rules.

Not currently enforced by active canonical code:

- append-only blackboard logging as part of runtime loop.

---

## 12. Current Architectural Direction

### Implemented direction

- generic orchestration + project adapters
- model-driven CreateGame and PlayGame
- bounded iterative state evolution
- typed integration boundary through proposals

### Conceptual/future signals from code/docs

- richer adversarial loop controls beyond current fixed role sequence
- stronger blackboard/event integration
- broader project-type ecosystem via adapters

Observation:

- repository docs still describe broader historical/conceptual systems; canonical executable path is now narrower and adapter-centric.

---

## 13. Current Limitations

- blackboard/event subsystem is not integrated into active run loop
- Red/Referee are prompt-only evaluations without independent tooling/checkers
- no workspace resume semantics beyond state-file load
- no external transaction/audit log for per-iteration decisions in canonical path
- limited delta operations (`append_section`, `write_file`)
- no parallel role execution or pluggable policy engine

---

## 14. Suggested Next Milestones (Additive)

1. Integrate lightweight blackboard appends in canonical loop
- append CreateGame/PlayGame/integration outcomes per iteration

2. Formalize role result envelopes
- standardize parsed role outputs with versioned envelopes for Blue/Red/Referee

3. Add adapter-level validation hooks
- optional per-project semantic checks pre-integration

4. Strengthen tool boundary
- explicit mechanism for model-requested tool actions with allowlist and audit trail

5. Expand adapter test matrix
- shared contract tests for any new project type adapter

---

## 15. Developer Workflow

### Running tests

- full suite: `uv run pytest`
- targeted files: `uv run pytest tests/test_run.py`

### Typical change flow (as seen in tests and module boundaries)

- update schema/adapter/orchestration in `src/baps/*`
- add/update deterministic tests under `tests/*`
- run full suite
- keep behavior behind existing boundaries (run orchestration vs adapter mechanics)

### Additive development preference

- extend via adapter methods and typed models
- preserve lifecycle command semantics
- avoid parallel competing execution paths in canonical CLI

---

## 16. Glossary

- **State**: authoritative persisted project condition (`State` model).
- **NorthStar**: directional intent represented as artifacts in `State.northstar`.
- **StateView**: immutable text projection consumed by model prompts.
- **ProjectTypeAdapter**: project-specific mechanics boundary used by generic orchestration.
- **GameSpec**: one coherent task contract for PlayGame (`objective`, target, delta type, success condition).
- **DeltaState**: proposed state change output from PlayGame (typed by project).
- **RedFinding**: critique/evaluation output (`accept|revise|reject`).
- **RefereeDecision**: game-local decision controlling candidate acceptance.
- **StateUpdateProposal**: integration request to mutate authoritative state.
- **StateService**: load/validate/apply/save service boundary for state updates.
- **StateStore**: persistence backend protocol; `JsonStateStore` is current implementation.
- **Export**: one-way projection from State to external output files.
- **Canonical spine**: `config/northstar -> adapter -> CreateGame -> PlayGame -> StateService -> export` within lifecycle commands.

---

## Architectural Observations / Ambiguities

1. `run.py` still re-exports/imports several adapter-specific symbols for test compatibility; orchestration is generic, but module surface is broader than strict CLI ownership.
2. `run.py` includes a compatibility helper `_build_create_game_state_view(state, artifact_id)` that assumes document adapter (`project_type="document"`) for older tests; this is not used by canonical orchestration path.
3. BlackBoard semantics are well documented conceptually, but active runtime integration is currently absent.
