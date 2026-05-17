# ONTOLOGY-MAPPING

## Purpose
This document maps currently implemented concepts in `baps` into explicit ontology families so future consolidation work can be planned without changing behavior.

Scope:

- documentation only,
- no code renames,
- no implementation changes,
- no architectural redesign claims.

## 1. Concept Families

### A. Runtime Adversarial Family
Primary modules:

- `src/baps/runtime.py`
- `src/baps/game_service.py`
- `src/baps/roles.py`
- `src/baps/example_roles.py`
- `src/baps/prompt_roles.py`
- `src/baps/prompts.py`
- `src/baps/prompt_assembly.py`
- `src/baps/models.py`

Core concepts:

- `GameRequest`, `GameContract`
- Blue/Red/Referee role invocation
- `Move`, `Finding`, `Decision`
- bounded round execution

### B. Blackboard/Event-Replay Family
Primary modules:

- `src/baps/blackboard.py`
- `src/baps/projections.py`
- `src/baps/runtime_integration.py`
- `src/baps/schemas.py` (event/governance records)

Core concepts:

- append-only `Event`
- runtime event history
- replay/projected state
- runtime-path integration decisions

### C. Filesystem Artifact Lifecycle Family
Primary modules:

- `src/baps/artifacts.py`
- artifact models in `src/baps/schemas.py`

Core concepts:

- `ArtifactAdapter` / `ArtifactHandler`
- `DocumentArtifactAdapter`
- snapshot/propose/apply/rollback on disk

### D. Authoritative State Family
Primary modules:

- `src/baps/state.py`
- `src/baps/state_store.py`
- `src/baps/state_service.py`

Core concepts:

- `State`, `NorthStar`, `StateArtifact`
- `StateUpdateProposal`, `StateUpdateTarget`
- adapter-based state validation/projection
- fingerprinted base-state validation at service boundary

### E. State View / North Star Projection Family
Primary modules:

- `src/baps/northstar_projection.py`
- `src/baps/project_intake.py`

Core concepts:

- `NorthStarProjectionInput`, `NorthStarProjectionItem`
- `ProjectionPolicy`, `ProjectionType`
- `StateView` / `NorthStarView`
- deterministic rendering and fingerprinting

### F. State-Centric Progress/Execute/Integrate Loop Family
Primary modules:

- `src/baps/state_progressor.py`
- `src/baps/game_executor.py`
- `src/baps/integration.py`
- `src/baps/loop.py`

Core concepts:

- `StateProgressorInput` -> `StateProgressionProposal`
- `GameProposal` -> `GameExecutionResult`
- `IntegrationDecision` + `StateChange`
- explicit bridges:
  - decision -> state update proposal,
  - optional apply via `StateService`,
  - optional record to blackboard

## 2. Classification

### 2.1 Authoritative vs Operational

Authoritative project condition:

- `State` family (`state.py`, `state_store.py`, `state_service.py`)

Operational/process memory:

- blackboard/event family (`blackboard.py`, `projections.py`, runtime events)

Execution orchestration (transient):

- runtime adversarial family,
- state-centric loop family

### 2.4 Authority Classes

Project-authoritative class:

- `State` and its nested `NorthStar`/`StateArtifact` structures in `state.py`.
- This class is the current accepted project condition.

Process-authoritative class:

- Blackboard events and replay-derived records in `blackboard.py` and `projections.py`.
- This class is authoritative for process history/provenance, not for current project condition.

Execution-authoritative class (ephemeral):

- in-flight runtime and loop outputs before integration/application.
- Examples: `GameState`, `LoopResult`, intermediate proposals/results/decisions.

### 2.2 Pure vs Side-Effecting

Mostly pure/deterministic transforms:

- `state.py` helper functions
- `northstar_projection.py`
- parser/renderer helpers in `state_progressor.py`
- derivation helpers in `integration.py`

Side-effecting boundaries:

- `blackboard.py` (event persistence)
- `state_store.py` (`JsonStateStore` filesystem I/O)
- `artifacts.py` filesystem mutation
- `models.py` (`OllamaClient` HTTP)

### 2.3 Generic vs Domain-Specific Semantics

Generic framework contracts:

- model protocols (`ModelClient`, `StateStore`, `StateProgressor`, `GameExecutor`, `Integrator`)
- envelope/event patterns

Domain-specific semantics currently encoded:

- adversarial roles (`blue`/`red`/`referee`)
- integration semantics (`accepted`, `satisfaction`, `materiality`)
- north star view category headings

## 3. Lifecycle Ownership

State lifecycle ownership:

- owner modules: `state.py`, `state_store.py`, `state_service.py`.
- responsibility: represent, validate, persist, and update authoritative project condition.

Runtime lifecycle ownership:

- owner modules: `runtime.py`, `game_service.py`, `roles.py`.
- responsibility: execute bounded adversarial rounds and produce runtime outcomes/events.

Process-memory lifecycle ownership:

- owner modules: `blackboard.py`, `projections.py`, `runtime_integration.py`.
- responsibility: append durable events and reconstruct replay/read models from event history.

State-centric loop lifecycle ownership:

- owner modules: `state_progressor.py`, `game_executor.py`, `integration.py`, `loop.py`.
- responsibility: generate progression proposals, execute candidates, produce integration decisions, and expose explicit optional bridges for recording/application.

Filesystem artifact lifecycle ownership:

- owner module: `artifacts.py`.
- responsibility: local artifact snapshot/propose/apply/rollback operations.

## 4. Explicit Replay Definition

Replay in this repository means deterministic reconstruction of read models from append-only event history.

Replay properties:

- input: ordered blackboard events,
- transform: deterministic projection logic,
- output: replay/read-model structures (for example `ProjectedState` and related query views).

Replay does not directly materialize authoritative `State` in `state.py`.

Explicit boundary statement:

- replay reconstructs history/provenance and derived operational views,
- replay does not define or overwrite current authoritative project `State` unless an explicit bridge/policy layer performs that mapping.

## 5. Merge Targets

Merge targets are documentation/planning targets only, not implemented changes.

### Target A: Integration Semantics Unification
Current split:

- runtime-path integration (`src/baps/runtime_integration.py` + `schemas.IntegrationDecision`)
- state-centric integration (`src/baps/integration.py` + `integration.IntegrationDecision`)

Merge target:

- one canonical integration ontology with explicit compatibility mapping for both paths.

### Target B: Projection Semantics Unification
Current split:

- replay projection (`src/baps/projections.py`)
- north star/state view projection (`src/baps/northstar_projection.py`)

Merge target:

- shared projection terminology with two concrete projection modes (replay-derived vs state-derived).

### Target C: Artifact Ontology Unification
Current split:

- filesystem artifact lifecycle (`artifacts.py`)
- authoritative state artifacts (`state.py`)

Merge target:

- explicit bridge contract from authoritative state artifact identity to concrete filesystem artifact instances.

### Target D: Loop-to-State Lifecycle Unification
Current split:

- loop result generation (`run_loop`)
- optional state application (`apply_loop_decision_update`)
- optional blackboard recording (`record_loop_result`)

Merge target:

- one documented lifecycle profile describing when each explicit step is invoked by policy.

## 6. Future Rename Candidates

Rename candidates below are documentation candidates only. No code renames are proposed in this step.

### Candidate Group 1: Integration Types
Potential ambiguity:

- `IntegrationDecision` exists in both `schemas.py` and `integration.py` with different shapes.

Candidate direction:

- distinguish runtime integration decision vs state-loop integration decision in naming.

### Candidate Group 2: Projection/View Terms
Potential ambiguity:

- `ProjectedState` (replay) vs `StateView`/`NorthStarView` (rendered view).

Candidate direction:

- align under a single umbrella term with explicit subtype names.

### Candidate Group 3: Artifact Terms
Potential ambiguity:

- `Artifact` (filesystem lifecycle) vs `StateArtifact` (authoritative identity-only record).

Candidate direction:

- make the lifecycle-vs-identity distinction explicit in terminology.

### Candidate Group 4: Integrator Naming
Potential ambiguity:

- `runtime_integration.py` and `integration.py` represent different layers.

Candidate direction:

- clarify policy/orchestration integrator vs schema/derivation integration namespace.

## 7. Current Non-Goals

- no code/module renames,
- no behavior changes,
- no migration plan execution,
- no compatibility layer implementation,
- no API deprecations.

## 8. Observations

1. The repository intentionally preserves additive coexistence of legacy runtime and state-centric loop slices.
2. Vocabulary overlap is the primary source of ambiguity, not immediate runtime defects.
3. Existing explicit bridges (`derive_state_update_from_decision`, `apply_decision_update`, `apply_loop_decision_update`) already provide stable anchors for later ontology consolidation.
