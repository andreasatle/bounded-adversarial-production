# Bounded Adversarial Production (`baps`) Architecture

## 1. Project Overview

### Purpose of the framework
`bounded-adversarial-production` (`baps`) is a typed Python framework for bounded adversarial execution and state-centric iterative improvement. The repository currently contains two active orchestration families:

1. runtime adversarial game execution (`blue` / `red` / `referee`) with append-only event recording,
2. state-centric progression/execution/integration loop components with explicit (not implicit) state-update and blackboard-recording bridges.

### Current project philosophy
Observed from implementation and tests:

- strict Pydantic schema boundaries,
- deterministic fakes and deterministic parsers/renderers for core seams,
- append-only durable process memory in the blackboard,
- additive development slices that preserve earlier modules,
- explicit separation between pure value transforms and side effects.

### Current architectural direction
Code is layered but currently dual-path:

- legacy/established runtime path: `runtime.py`, `game_service.py`, `roles.py`, prompt/model modules, `runtime_integration.py`, `projections.py`.
- state-centric path: `state.py`, `state_store.py`, `state_service.py`, `northstar_projection.py`, `project_intake.py`, `state_progressor.py`, `game_executor.py`, `integration.py`, `loop.py`.

### What “bounded adversarial production” means in practice
Current concrete behavior:

- bounded: `max_rounds` caps runtime loops; role invocation retries are capped.
- adversarial: Blue proposes, Red critiques, Referee decides accept/revise/reject.
- production-oriented: durable structured events, replayable projections, explicit integration decisions, and explicit update proposals.

### Current implementation vs future aspirations
Implemented now:

- bounded adversarial runtime loop with durable blackboard events,
- deterministic state-centric render/progress/execute/integrate loop primitives,
- pure state model + adapter + proposal/update boundaries,
- explicit JSON-file state persistence (`JsonStateStore`),
- service-level base-state fingerprint enforcement before state updates.

Conceptual/future (not yet fully integrated):

- unified runtime-to-state mutation pipeline,
- artifact-kind-specific mutation semantics,
- convergence between replay projection (`projections.py`) and state-view rendering (`northstar_projection.py`),
- richer multi-agent/tool-enabled adversarial orchestration.

## 2. Current System Capabilities

### Schemas (`src/baps/schemas.py`)
Purpose:

- canonical typed contracts for runtime, events, governance lifecycle, replay projection, and artifact records.

Important classes/functions:

- runtime request/contract: `GameRequest`, `GameContract`, `Target`.
- role outputs: `Move`, `Finding`, `Decision`.
- run/result: `GameRound`, `GameState`, `GameResponse`, `RoundSummary`.
- governance and lifecycle: `IntegrationDecision` (runtime path), discrepancy/accepted-state lifecycle records.
- event envelope: `Event`.

Current limitations:

- some cross-object policies are enforced in services/policies, not only in model validators.

Relationships:

- shared by runtime, blackboard, integrator, projections, artifacts, planner, tests.

### Blackboard (`src/baps/blackboard.py`)
Purpose:

- append/read/query JSONL event persistence.

Important classes/functions:

- `Blackboard.append`, `read_all`, `query`, `query_by_run`, `query_completed_runs`.
- append helpers for integration and lifecycle event types.

Current limitations:

- linear scans, no indexes, no lock manager.

Relationships:

- runtime/integrator and loop result recording append events.
- projection/replay and tests consume events.

### Artifacts (`src/baps/artifacts.py`)
Purpose:

- filesystem artifact lifecycle operations.

Important classes/functions:

- `ArtifactAdapter`, `ArtifactHandler`, `DocumentArtifactAdapter` operations.

Current limitations:

- only `document` adapter implemented.
- not automatically driven by state update acceptance.

Relationships:

- uses artifact models from `schemas.py`.
- separate from `StateArtifact` references in `state.py`.

### Runtime (`src/baps/runtime.py`)
Purpose:

- bounded adversarial round execution with ordered event emission.

Important classes/functions:

- `RuntimeEngine.run_game`, terminal response construction helpers.

Current limitations:

- linear Blue->Red->Referee flow only.
- no tool system.

Relationships:

- invoked via `game_service.py` and demos.
- depends on roles + blackboard.

### Roles (`src/baps/roles.py`, `src/baps/example_roles.py`, `src/baps/prompt_roles.py`)
Purpose:

- role invocation guard and deterministic/prompt-based role implementations.

Important classes/functions:

- `RoleInvocationGuard`, `RoleInvocationError`.
- deterministic roles and prompt role builders.

Current limitations:

- no tool protocol or multi-branch role graph.

Relationships:

- consumed by runtime and service layers.

### Prompt rendering (`src/baps/prompts.py`, `src/baps/prompt_assembly.py`)
Purpose:

- deterministic assembly/rendering of prompt text.

Important classes/functions:

- `PromptSection`, `PromptSpec`, `assemble_prompt`, `PromptRenderer`.

Current limitations:

- template system is simple `str.format` style.

Relationships:

- used by prompt roles and game definitions.

### Model abstraction (`src/baps/models.py`)
Purpose:

- provider-agnostic text generation interface.

Important classes/functions:

- `ModelClient`, `FakeModelClient`, `OllamaClient`.

Current limitations:

- no provider-level retry/backoff abstraction.

Relationships:

- prompt roles, planner, and model-backed state progressor use this abstraction.

### Ollama integration
Purpose:

- synchronous local Ollama `generate` call path.

Important behavior:

- POST to `/api/generate`, `stream=False`, runtime validation/error mapping.

Current limitations:

- no streaming path or built-in retries.

Relationships:

- CLI and demo flows.

### Deterministic testing
Purpose:

- guarantee stable behavior for orchestration and schema boundaries.

Important behavior:

- deterministic fakes (model/progressor/executor/integrator),
- strict parser validation,
- strong ordering assertions.

Current limitations:

- limited nondeterministic live integration coverage.

Relationships:

- comprehensive suite in `tests/` across runtime and state-centric slices.

### Demo game execution
Purpose:

- narrow runnable examples (deterministic and Ollama-backed).

Important entry points:

- `baps-demo`, `baps-adversarial-demo`, `baps-ollama-adversarial-demo`, `baps-play-game`.

Current limitations:

- demos do not unify all state-centric update pipelines end-to-end.

Relationships:

- compose runtime/service/model/game-type modules.

## 3. Repository Structure

```text
src/baps/
  runtime.py
  game_service.py
  roles.py
  prompts.py
  models.py
  blackboard.py
  runtime_integration.py
  projections.py
  artifacts.py

  state.py
  state_store.py
  state_service.py
  northstar_projection.py
  project_intake.py
  state_progressor.py
  game_executor.py
  integration.py
  loop.py

tests/
  test_runtime.py
  test_blackboard.py
  test_integrator.py
  test_projections.py
  test_artifacts.py
  test_state.py
  test_state_store.py
  test_state_service.py
  test_northstar_projection.py
  test_state_progressor.py
  test_game_executor.py
  test_integration_models.py
  test_loop.py
  ...

docs/
  ARCHITECTURE.md
  STATE_MODEL.md
  SYSTEM.md
  NORTH-STAR.md
  ...
```

Important module boundaries:

- `state.py`: pure authoritative state models + validation + projection + update transforms.
- `state_service.py`: service boundary orchestration and fingerprint validation enforcement.
- `integration.py`: state-centric integration semantics and decision->proposal bridges.
- `loop.py`: minimal orchestrator and explicit recording/application helpers.
- `runtime_integration.py`: runtime-path integration policy and blackboard append behavior.

## 4. Core Runtime Flow

### Runtime game flow (`RuntimeEngine.run_game`)

1. generate run ID.
2. append `game_started` event.
3. for each round up to `max_rounds`:
4. invoke Blue via guard.
5. append blue move event.
6. invoke Red via guard.
7. append red finding event.
8. invoke Referee via guard.
9. append referee decision event.
10. decide terminate/continue on decision.
11. build final `GameState`.
12. append `game_completed` event.
13. return `GameState`.

### Role invocation flow

`RoleInvocationGuard`:

1. call role,
2. validate Pydantic output,
3. validate semantics,
4. retry until attempts exhausted,
5. raise `RoleInvocationError` on exhaustion.

### Prompt rendering and model call flow

1. assemble prompt sections,
2. render prompt text,
3. `ModelClient.generate(prompt)`,
4. parse structured output into role models.

### Runtime persistence and blackboard recording

- runtime persists via blackboard append-only events.
- `game_service.py` appends integration decisions via runtime-path integrator.

### Artifact interaction with runtime

- runtime does not directly call `artifacts.py` operations.
- artifact lifecycle and state update transforms remain explicit separate flows.

### State-centric loop flow (`run_loop`)

1. `proposal = progressor.progress(input)`.
2. `execution_result = executor.execute(proposal.game_proposal)`.
3. `decision = integrator.integrate(execution_result)`.
4. return `LoopResult`.

No implicit blackboard append or state update occurs in `run_loop` itself.

## 5. Schema Documentation

### State model schemas (`state.py`)

- `StateArtifact(id, kind)`: non-empty identity fields.
- `NorthStar(artifacts)`: tuple of artifacts; unique IDs enforced.
- `State(northstar, artifacts=())`: unique ordinary IDs, no northstar/ordinary overlap.
- `StateUpdateTarget(artifact_id, section?)`: non-empty artifact ID; non-empty section when present.
- `StateUpdateProposal(id, target, summary, payload, base_state_fingerprint?)`.
  - `base_state_fingerprint` optional but non-empty when provided.
- `StateProjection(northstar, artifacts)`.

Why:

- maintain small pure authoritative state shape and explicit update contracts.

### State-centric integration schemas (`integration.py`)

- `StateChange(id, execution_result_id, summary, applied_delta, materiality, risks)`.
  - `materiality` exact allowed values: `"none" | "partial" | "full"`.
- `IntegrationSatisfaction` enum: `NONE`, `PARTIAL`, `FULL`.
- `IntegrationDecision(id, state_change, accepted, satisfaction, rationale)`.

Why:

- encode acceptance and satisfaction/materiality semantics independently.

### Progress/execution/loop schemas

- `StateProgressorInput`, `GameProposal`, `StateProgressionProposal`.
- `GameExecutionResult`.
- `LoopResult`.

Why:

- explicit typed contracts for each loop stage.

## 6. Blackboard/Event System

### Append-only philosophy

- blackboard only appends events; no in-place mutation API.

### Event persistence

- JSONL lines validated into `Event` model on read.

### Event querying

- query by type, run ID, and completed-run helper.

### Event lifecycle

Active event families:

- runtime flow events (`game_started`, role events, `game_completed`, integration events).
- loop recording helper events (`state_progression_proposed`, `game_executed`, `integration_decided`).

### Intended future role of blackboard

- durable process memory and replay/audit substrate, separate from authoritative `State` value.

## 7. Artifact System

### Artifact lifecycle

`DocumentArtifactAdapter` in `artifacts.py` supports:

- create,
- snapshot,
- propose change,
- apply change,
- rollback.

### Adapter systems

Two separate adapter systems exist:

1. filesystem artifact adapters in `artifacts.py`,
2. state artifact adapters in `state.py` (`StateArtifactRegistry`).

### Snapshots and metadata

Document artifact versions and proposals are stored under per-artifact directories with `metadata.json`.

### Filesystem structure (document artifacts)

```text
<root>/<artifact_id>/
  metadata.json
  current/main.md
  versions/vNNN/
  changes/cNNN/
    proposed.md
    change.json
```

### Current assumptions/constraints

- only document filesystem adapter is implemented.
- state-level document/git adapters are currently stubs for validation/projection.

## 8. Runtime Engine

### Responsibilities

- bounded game execution,
- guard-enforced role validation/retries,
- deterministic event ordering,
- final state/result generation.

### Role invocation guard

- retries for schema/semantic failures,
- explicit failure classification via exceptions.

### Retry behavior

- local to each role call; no global run-level retry policy.

### Game execution model

- linear Blue -> Red -> Referee loop per round.

### Deterministic execution approach

- deterministic role implementations and fake model responses in tests.

## 9. Roles and Prompt System

### Deterministic example roles

- deterministic baseline Blue/Red/Referee behaviors for tests and demos.

### Prompt-driven roles

- prompt assembly + rendering + model generation + parsing into typed outputs.

### `PromptRenderer`

- deterministic template renderer with output validation.

### `FakeModelClient`

- deterministic queued responses and prompt capture.

### `OllamaClient`

- synchronous generate API integration.

### Role execution flow

- service builds role callables,
- runtime invokes via guard,
- validated outputs persisted as events.

### Current limitations

- no tool request/execution protocol,
- no concurrent adversarial role topology.

## 10. Testing Strategy

### Current testing philosophy

- deterministic, boundary-first, behavior-driven validation.

### Deterministic approach

- fake model clients,
- fake progressor/executor/integrator,
- pure-function tests for parser/fingerprint/projection/update helpers.

### Coverage

- schema validation,
- runtime flow,
- blackboard replay/query,
- artifact lifecycle,
- state model/store/service enforcement,
- decision->update derivation,
- loop orchestration and explicit recording.

### Why deterministic tests matter

- architecture depends on exact event ordering, strict schema semantics, and reproducible update behavior.

## 11. Architectural Invariants (Enforced by code)

1. non-empty required IDs/text fields where validators exist.
2. runtime round bounds and deterministic role call order.
3. append-only blackboard API surface.
4. unique state artifact IDs and no northstar/ordinary overlap.
5. state update replacement preserves artifact ID and kind.
6. state adapter registry rejects unknown/duplicate/empty kinds.
7. `fingerprint_state` deterministic SHA-256 over canonical sorted-key JSON.
8. `validate_update_base_state` semantics:
   - `None` fingerprint => valid,
   - provided fingerprint must match current state fingerprint.
9. `StateService.apply_update` enforces fingerprint check before applying update and raises `ValueError` containing `base_state_fingerprint` on mismatch.
10. integration semantics independence:
    - `accepted` independent of `satisfaction`,
    - `StateChange.materiality` independent of both `accepted` and `satisfaction`.

## 12. Current Architectural Direction

### Implemented direction

- coexistence of legacy runtime path and newer state-centric path,
- explicit bridges (decision -> update proposal, optional decision application),
- deterministic fingerprint/version-guard semantics at service boundary.

### Conceptual/future direction

- deeper runtime-to-state integration,
- unified integration semantics across `runtime_integration.py` and `integration.py`,
- richer adversarial loop with tool boundaries and potentially multi-role expansion,
- tighter projection/view alignment.

## 13. Current Limitations

- `apply_state_update` supports only generic `replace_artifact`.
- no artifact-kind-specific content mutation semantics.
- no automatic state application from runtime decisions.
- `run_loop` orchestration remains minimal and does not include retries/escalation.
- two integration and projection concept families coexist without a single canonical bridge.
- no conflict-resolution/rebase/merge semantics beyond fingerprint mismatch rejection.

## 14. Suggested Next Milestones (Additive)

1. Add explicit policy layer deciding when to call `apply_decision_update` / `apply_loop_decision_update`.
2. Add adapter-level concrete mutation semantics per artifact kind while preserving pure state transforms.
3. Add integration tests that validate old runtime integration outputs against new state-centric decision/update bridges.
4. Introduce reconciliation adapters between `projections.py` replay output and `NorthStarView` rendering inputs.
5. Add explicit conflict-handling policy around fingerprint mismatch outcomes at service boundary.

## 15. Developer Workflow

### Running tests

```bash
uv run pytest
```

### Typical implementation workflow

1. add/adjust typed model boundary,
2. add deterministic tests for success and failure paths,
3. implement pure helper or narrow service enforcement,
4. keep side effects explicit and isolated,
5. run full suite.

### Commit/style characteristics

- small additive slices,
- architecture boundary hardening before integration expansion,
- documentation updates to reflect actual code.

## 16. Glossary

- **Game**: bounded runtime adversarial execution under a `GameContract`.
- **Role**: Blue/Red/Referee callable in runtime loop.
- **Move**: Blue role output.
- **Finding**: Red role critique output.
- **Decision**: Referee output controlling runtime continuation/termination.
- **State**: current authoritative project condition (`state.py`).
- **NorthStar**: dedicated authoritative state subset.
- **StateArtifact**: minimal artifact identity in authoritative state.
- **StateView / NorthStarView**: immutable rendered view artifact.
- **Blackboard**: append-only durable process-memory log.
- **StateProgressor**: component producing `StateProgressionProposal`.
- **GameProposal**: proposed game candidate from progressor.
- **GameExecutor**: component producing `GameExecutionResult`.
- **StateChange**: proposed/applied change summary from integration stage, including `materiality`.
- **IntegrationDecision**: integration outcome with independent `accepted` and `satisfaction` semantics.
- **StateUpdateProposal**: explicit state update request, optionally guarded by `base_state_fingerprint`.
- **StateService**: load/validate/apply/save orchestration boundary.

## Observations and Ambiguities

1. Two integration surfaces coexist:
   - runtime path (`runtime_integration.py` + `schemas.IntegrationDecision`),
   - state-centric path (`integration.py` + `integration.IntegrationDecision`).
2. Two projection surfaces coexist:
   - replay projection (`projections.py`),
   - state view rendering (`northstar_projection.py`).
3. Two artifact systems coexist:
   - filesystem lifecycle (`artifacts.py`),
   - authoritative-state artifact references/adapters (`state.py`).
4. Fingerprint validation is enforced only at `StateService` boundary; lower-level `apply_state_update` remains fingerprint-agnostic by design.
5. `materiality`, `satisfaction`, and `accepted` are independent in current schema semantics; policy coupling is not yet implemented.
