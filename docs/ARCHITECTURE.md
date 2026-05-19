# Bounded Adversarial Production (`baps`) Architecture

## 1. Project Overview
### Purpose of the framework
`baps` is a Python framework for bounded adversarial reasoning loops with explicit typed contracts, durable event history, and incremental state-oriented orchestration. The repository currently contains two active execution families:

1. Runtime adversarial game flow (`blue` -> `red` -> `referee`) persisted to blackboard events.
2. State-centric progression/execution/integration flow with explicit proposal derivation and explicit optional state application.

A third, product-shaped CLI (`baps-run`) now composes configuration resolution, state creation, LLM-backed game specification, and bounded in-game deliberation (`Blue`, `Red`, `Referee`) with deterministic parsing/validation boundaries.

### Current project philosophy
Observed in code and tests:

- typed boundaries enforced with Pydantic models,
- deterministic testability at seams (fake clients/progressors/executors/integrators),
- explicit side-effect boundaries (file I/O, network I/O, blackboard appends),
- additive evolution (old runtime and newer state-centric flows coexist),
- separation between authoritative state and operational/replay views.

### Current architectural direction
Current architecture is intentionally multi-path:

- Runtime path: `runtime.py`, `game_service.py`, `runtime_integration.py`, roles/prompt/model modules, blackboard, projections.
- State-centric path: `state.py`, `state_store.py`, `state_service.py`, `northstar_projection.py`, `state_progressor.py`, `game_executor.py`, `integration.py`, `loop.py`.
- Product CLI hardening path: `run.py` (`baps-run`) with staged transforms (`read_config`, `create_state`, `create_game`, `play_game`).

### What “bounded adversarial production” means in practice
In implemented behavior:

- bounded: runtime rounds (`max_rounds`) and play-game attempts (`max_attempts`) are capped,
- adversarial: Blue proposes change candidates, Red critiques, Referee adjudicates,
- production-oriented: structured outputs, strict validation, optional durable event logging, explicit update boundaries.

### Current implementation vs future aspirations
Implemented now:

- fully typed runtime adversarial game execution with event persistence,
- deterministic and LLM-backed role paths,
- explicit integration decision records in both runtime and state-centric namespaces,
- explicit state update proposal derivation and service-level fingerprint checks,
- LLM-backed `CreateGame`, `Blue`, `Red`, `Referee` in `baps-run` PlayGame (with bounded attempts and strict JSON contracts).

Not fully integrated yet:

- no integrated `IntegrateState` step in `baps-run` to mutate authoritative `State`,
- no unified integration ontology between `schemas.IntegrationDecision` and `integration.IntegrationDecision`,
- no single canonical bridge from runtime replay projections to authoritative state mutation,
- no tool protocol or generalized multi-agent topology beyond current bounded loops.

## 2. Current System Capabilities
### Schemas (`src/baps/schemas.py`)
Purpose:

- canonical runtime/event/governance/replay contracts.

Important models:

- request/contract: `GameRequest`, `GameContract`, `Target`,
- role outputs: `Move`, `Finding`, `Decision`,
- runtime result: `GameRound`, `GameState`, `GameResponse`, `RoundSummary`,
- runtime integration governance: `IntegrationDecision` (runtime namespace),
- event envelope: `Event`,
- replay/read-model support: accepted/discrepancy/artifact lifecycle records.

Limitations:

- domain coupling is partly schema-level and partly policy-level; some semantics are enforced by orchestrators rather than validators.

Relationships:

- consumed across runtime engine, game service, blackboard, runtime integration, replay projection, demos, tests.

### Blackboard (`src/baps/blackboard.py`)
Purpose:

- append-only JSONL event storage with read/query helpers.

Key functions:

- `append`, `read_all`, `query`, `query_by_run`, `query_completed_runs`,
- typed append helpers for integration/discrepancy/lifecycle records.

Limitations:

- linear scans only; no indexing or locking layer.

Relationships:

- runtime appends role/round/completion events,
- runtime integration appends integration decisions,
- projections/tests consume event history.

### Artifacts (`src/baps/artifacts.py`)
Purpose:

- filesystem artifact lifecycle operations (`create`, `snapshot`, `propose_change`, `apply_change`, `rollback`).

Key classes:

- `ArtifactAdapter`, `ArtifactHandler`, `DocumentArtifactAdapter`.

Limitations:

- only document adapter implemented,
- not automatically invoked by state updates.

Relationships:

- operates on `schemas.Artifact` family,
- separate from authoritative `state.py` artifact identity models.

### Runtime (`src/baps/runtime.py`)
Purpose:

- bounded adversarial execution engine with ordered event emission.

Key functions/classes:

- `RuntimeEngine.run_game`,
- `build_game_response`,
- terminal semantics helpers.

Limitations:

- linear role topology (`blue` -> `red` -> `referee`) only,
- no tool-calling protocol.

Relationships:

- orchestrated by `GameService`, role outputs validated by `RoleInvocationGuard`, events persisted to `Blackboard`.

### Roles (`src/baps/roles.py`, `src/baps/example_roles.py`, `src/baps/prompt_roles.py`)
Purpose:

- role invocation contracts and deterministic/prompt-backed role implementations.

Key classes/functions:

- `RoleInvocationGuard`, `RoleInvocationError`,
- deterministic example roles,
- prompt role builders.

Limitations:

- no branching role graph or tool execution model.

Relationships:

- runtime engine invokes these roles directly or via prompt/model adapters.

### Prompt rendering (`src/baps/prompts.py`, `src/baps/prompt_assembly.py`)
Purpose:

- deterministic prompt assembly and rendering.

Key classes/functions:

- `PromptSection`, `PromptSpec`, `PromptRenderer`, `assemble_prompt`.

Limitations:

- simple template composition; no advanced prompt planning layer.

Relationships:

- used by prompt roles and planning/game definition modules.

### Model abstraction (`src/baps/models.py`)
Purpose:

- provider-neutral generation interface.

Key classes:

- `ModelClient` protocol-like base,
- `FakeModelClient`,
- `OllamaClient`.

Limitations:

- no built-in retry/backoff/streaming orchestration.

Relationships:

- consumed by roles, planner-like flows, and `baps-run` CreateGame/PlayGame LLM stages.

### Ollama integration
Purpose:

- synchronous local model generation through `/api/generate`.

Behavior:

- JSON POST with `stream=False`,
- strict response field check for `response`.

Limitations:

- no stream API integration in current code,
- failure handling is exception-based and caller-managed.

### Deterministic testing
Purpose:

- preserve reproducibility for orchestration boundaries and schema invariants.

Current behavior:

- extensive use of `FakeModelClient` and deterministic fakes,
- validation-focused tests for success/failure paths,
- ordering and boundary assertions across runtime/state flows.

### Demo and runnable execution
Entry points in `pyproject.toml`:

- `baps-demo`, `baps-adversarial-demo`, `baps-ollama-adversarial-demo`,
- `baps-play-game`, `baps-state-loop-demo`,
- `baps-run`.

`baps-run` is now the most product-shaped executable loop surface, with configuration/state/game/play stages and bounded adversarial attempts.

## 3. Repository Structure
```text
src/baps/
  runtime.py
  game_service.py
  runtime_integration.py
  roles.py
  example_roles.py
  prompt_roles.py
  prompts.py
  prompt_assembly.py
  models.py
  blackboard.py
  projections.py
  artifacts.py
  schemas.py

  state.py
  state_store.py
  state_service.py
  northstar_projection.py
  state_progressor.py
  game_executor.py
  integration.py
  loop.py
  run.py
  state_loop_demo.py

tests/
  test_runtime.py
  test_blackboard.py
  test_integrator.py
  test_projections.py
  test_artifacts.py
  test_state.py
  test_state_store.py
  test_state_service.py
  test_integration_models.py
  test_loop.py
  test_run.py
  ...

docs/
  ARCHITECTURE.md
  SYSTEM.md
  ONTOLOGY-MAPPING.md
  INTEGRATION-ONTOLOGY.md
  RENAME-PLAN.md
  STATE-HANDLING-AUDIT.md
  ...
```

Module boundaries:

- `state.py`: authoritative state, deltas, game-local runtime decision models, pure transforms/validators.
- `state_service.py`: service boundary for load/validate/fingerprint-check/apply/save.
- `integration.py`: state-centric integration semantics and decision->proposal derivation.
- `runtime_integration.py`: runtime response governance/integration event policy.
- `loop.py`: minimal progression/execution/integration orchestration + explicit helper bridges.
- `run.py`: staged runnable command path (`read_config -> create_state -> create_game -> play_game`) plus legacy deterministic `run_baps_loop` helper path.

## 4. Core Runtime Flow
### A. Runtime adversarial game flow (`GameService.play`)
1. Build or resolve `GameDefinition` from request.
2. Resolve optional state source context (`state_sources.py`) if requested.
3. Build Blue/Red/Referee role callables (`prompt_roles.py`).
4. Build `GameContract`.
5. Execute `RuntimeEngine.run_game`:
   - append `game_started`,
   - per round: invoke Blue -> append, invoke Red -> append, invoke Referee -> append,
   - stop on `accept`/`reject` or round exhaustion,
   - append `game_completed`.
6. Build `GameResponse` via `build_game_response`.
7. Run runtime integration policy (`runtime_integration.integrate_response`) and append integration decision event.
8. Return `GameResponse`.

### B. Role invocation and validation flow
1. `RoleInvocationGuard.invoke` calls role callable.
2. Output is parsed/validated against target model.
3. Optional semantic validator checks cross-field/domain constraints.
4. Retries occur within guard policy; failure raises `RoleInvocationError`.

### C. Prompt and model call flow
1. Prompt text is assembled/rendered.
2. `ModelClient.generate(prompt)` called (fake or Ollama).
3. Raw model output parsed into strict Pydantic model.
4. Invalid outputs raise deterministic validation exceptions unless caller handles explicitly.

### D. State-centric loop flow (`loop.run_loop`)
1. `progressor.progress(input)` -> `StateProgressionProposal`.
2. `executor.execute(game_proposal)` -> `GameExecutionResult`.
3. `integrator.integrate(execution_result)` -> `integration.IntegrationDecision`.
4. Return `LoopResult`.

No implicit state mutation or blackboard write in `run_loop` itself.

### E. `baps-run` staged flow (`run.py`)
Current top-level flow in `main()`:
1. Read CLI + optional YAML spec and resolve config precedence.
2. `create_state(config)` from `project_type` (currently `document` only implemented).
3. `create_game(config, state)` via LLM JSON `GameSpec` contract.
4. `play_game(state, game_spec)` bounded in-attempt adversarial loop:
   - build `StateView` once,
   - Blue LLM produces candidate `DeltaDocumentState`,
   - Red LLM critiques to `RedFinding`,
   - Referee LLM decides `RefereeDecision`,
   - `apply_referee_decision_to_runtime` updates `PlayGameRuntime.current_best_delta`,
   - accept returns immediately; revise/reject continue until `max_attempts`.
5. If no accepted delta by exhaustion, `None` is returned and CLI exits cleanly.
6. Legacy deterministic `run_baps_loop` remains present and callable, but is separate from the new staged flow.

## 5. Schema Documentation
### Authoritative state and document models (`state.py`)
- `StateArtifact(id, kind)`:
  - non-empty `id`/`kind`.
- `DocumentArtifact(StateArtifact)`:
  - `kind` fixed to `"document"`,
  - `sections: tuple[Section, ...]`.
- `Section(title, body)`:
  - non-empty title/body.
- `NorthStar(artifacts)`:
  - unique artifact IDs.
- `State(northstar, artifacts=())`:
  - unique ordinary artifact IDs,
  - disjoint IDs between northstar and ordinary artifacts.

Why:

- keep authoritative project condition compact and type-checked.

### Delta and play-game runtime models (`state.py`)
- `DeltaState(artifact_id)` base for proposed changes.
- `DeltaDocumentState(artifact_id, operation="append_section", payload)`.
- `AppendSectionDelta(section)`.
- `RedFinding(disposition, rationale)`.
- `RefereeDecision(disposition, rationale)`.
- `PlayGameRuntime(current_best_delta)` ephemeral runtime memory.

Why:

- separate proposed change contracts and game-local adjudication memory from authoritative state.

### State update proposal models (`state.py`)
- `StateUpdateTarget(artifact_id, section?)`.
- `StateUpdateProposal(id, target, summary, payload, base_state_fingerprint?)`.
  - optional fingerprint must be non-empty when provided.

Why:

- explicit mutation requests with optional optimistic-concurrency anchor.

### Runtime and governance models (`schemas.py`)
- runtime request/contract/round/result/event models,
- runtime integration governance models (`schemas.IntegrationDecision` etc.).

Why:

- stable replayable contracts for runtime path and blackboard lifecycle.

### State-centric integration models (`integration.py`)
- `StateChange(id, execution_result_id, summary, applied_delta, materiality, risks)`.
- `IntegrationSatisfaction` enum.
- `integration.IntegrationDecision(id, state_change, accepted, satisfaction, rationale)`.

Why:

- explicit state-mutation-oriented integration decision surface.

## 6. Blackboard/Event System
### Append-only philosophy
- no mutation-in-place API; events are appended line-by-line JSON.

### Persistence
- `Blackboard.append` writes one serialized event per line.
- `read_all` reparses into validated `Event` models.

### Querying
- by type (`query`),
- by `run_id` (`query_by_run`),
- completed runs helper (`query_completed_runs`).

### Event lifecycle
Observed event families:

- runtime lifecycle (`game_started`, role-recorded events, `game_completed`),
- integration/lifecycle governance events,
- state loop helper events (`state_progression_proposed`, `game_executed`, `integration_decided`).

### Current role of blackboard
- durable process/provenance memory and replay input,
- not authoritative `State` by itself.

## 7. Artifact System
### Filesystem lifecycle path (`artifacts.py`)
- `create`: initialize artifact directory.
- `snapshot`: copy `current` into versioned directory.
- `propose_change`: stage proposed content + diff metadata.
- `apply_change`: promote proposed content to current and snapshot.
- `rollback`: restore current from chosen version.

### Handler delegation
- `ArtifactHandler` routes by `artifact.type`.

### Metadata and snapshot structure
Example document artifact layout:

```text
<root>/<artifact_id>/
  metadata.json
  current/main.md
  versions/vNNN/
  changes/cNNN/
    proposed.md
    change.json
```

### Assumptions/constraints
- only `document` adapter implemented,
- separate from authoritative `State` mutation semantics.

## 8. Runtime Engine
### Responsibilities
- bounded round execution,
- role invocation and output validation via guard,
- deterministic event ordering,
- terminal response semantics computation.

### Guard and retry behavior
- guard validates schema + semantics per role output,
- retries are local invocation concerns, not global workflow retries.

### Game model
- fixed Blue/Red/Referee per-round sequence,
- continuation depends on Referee decisions and round budget.

### Deterministic execution approach
- deterministic role implementations and fake model clients heavily used in tests.

## 9. Roles and Prompt System
### Deterministic role implementations
- example roles provide stable output contracts for tests and demos.

### Prompt-driven roles
- prompt role builders construct role callables around model generation and strict parsing.

### PromptRenderer
- deterministic prompt text assembly and template rendering.

### FakeModelClient
- queue-based deterministic responses,
- captures prompts for assertion.

### OllamaClient
- synchronous local HTTP generation with strict response checks.

### Role flow in `baps-run` PlayGame
- Blue prompt: `StateView + GameSpec + attempt/feedback` -> `DeltaDocumentState` JSON,
- Red prompt: `StateView + GameSpec + candidate delta` -> `RedFinding` JSON,
- Referee prompt: `StateView + GameSpec + candidate delta + RedFinding` -> `RefereeDecision` JSON.

### Current limitations
- no tool system,
- no parallel/concurrent role topology,
- no persisted in-game deliberation branches.

## 10. Testing Strategy
### Philosophy
- boundary-driven, deterministic, additive coverage.

### Deterministic approach
- use of `FakeModelClient`, fake integrators/progressors/executors,
- strict parser tests for accepted/rejected formats,
- explicit assertions over event ordering and state invariants.

### Coverage areas
- runtime flow and response semantics,
- blackboard event persistence/query,
- runtime integration policy behavior,
- state models/deltas/updates/fingerprints,
- state store/service mutation rules,
- `baps-run` staged config and PlayGame behavior,
- projection/rendering modules and prompt assembly.

### Why deterministic tests matter here
- architecture depends on strict contract boundaries,
- adversarial loop decisions are schema/policy sensitive,
- replay/state semantics require reproducibility to avoid ontology drift.

## 11. Architectural Invariants (Code-Enforced)
1. Non-empty string fields are validated at model boundaries where declared.
2. Runtime rounds are bounded and ordered.
3. Blackboard append/read model is append-only.
4. `State` enforces unique artifact IDs and northstar/ordinary ID disjointness.
5. `StateUpdateProposal.base_state_fingerprint` is optional but non-empty if provided.
6. `fingerprint_state` is deterministic SHA-256 over canonical JSON.
7. `validate_update_base_state`: `None` fingerprint passes; provided fingerprint must match current state.
8. `StateService.apply_update` validates current state, validates fingerprint gate, applies update, validates/saves updated state.
9. `apply_state_update` supports only explicit operations (`replace_artifact`, `add_artifact`); unknown operations fail.
10. In PlayGame runtime update semantics:
   - `accept` may set `current_best_delta`,
   - `revise`/`reject` preserve previously accepted best delta.

## 12. Current Architectural Direction
### Implemented direction
- coexistence of runtime governance path and state-centric mutation path,
- increasingly explicit state contracts (document sections, deltas, game specs),
- hardening `baps-run` into staged transformations with bounded adversarial attempts and strict JSON interfaces.

### Conceptual/future direction (inferred from code/docs)
- complete integration stage from accepted delta to authoritative `State` mutation in product path,
- consolidation of overlapping integration ontologies,
- expanded adversarial orchestration depth (potential multi-attempt/multi-role refinements),
- clearer bridge between replay/provenance outputs and authoritative state transitions.

## 13. Current Limitations
- `baps-run` currently stops at PlayGame candidate delta; no integrated state-mutation/export completion stage in the new flow.
- Runtime integration (`runtime_integration.py`) and state-centric integration (`integration.py`) remain parallel concept families.
- Artifact filesystem lifecycle and authoritative state artifact identity remain separate systems.
- Replay projections and state views are both active with overlapping terminology.
- LLM output correctness is controlled by strict parsing and retry bounds, but still relies on model adherence to prompt constraints.

## 14. Suggested Next Milestones (Additive)
1. Add explicit `IntegrateState` stage in `baps-run` that validates/apply-saves accepted deltas through `StateService`.
2. Add a narrow export stage mapping canonical in-memory document state to `report.md` (one-way projection).
3. Add integration tests spanning `create_state -> create_game -> play_game -> integrate_state` with fingerprint guard behavior.
4. Add compatibility adapter tests documenting mapping between runtime integration decisions and state-centric decisions.
5. Add policy tests around Referee/Red semantics for success-condition completeness and harmful/incoherent rejection criteria.

## 15. Developer Workflow
### Running tests
```bash
uv run pytest
```

### Typical change workflow
1. Add/adjust Pydantic schema boundary.
2. Add deterministic tests for success and failure paths.
3. Implement narrow transform or service boundary change.
4. Keep side effects explicit and isolated.
5. Run full test suite.

### Contribution style reflected in repository
- additive slices,
- boundary-first changes,
- explicit debugability (notably in `baps-run` with `BAPS_DEBUG=1`),
- preservation of prior module paths while hardening newer path.

## 16. Glossary
- **Game**: bounded adversarial decision cycle under a `GameContract` or `GameSpec`.
- **Role**: Blue/Red/Referee function in an adversarial loop.
- **Move**: Blue output in runtime path (`schemas.Move`).
- **Finding**: Red output in runtime path (`schemas.Finding`) or game-local critique (`state.RedFinding`).
- **Decision**: Referee output in runtime path (`schemas.Decision`) or PlayGame (`state.RefereeDecision`).
- **State**: authoritative project condition in `state.py`.
- **NorthStar**: dedicated subset of authoritative state artifacts.
- **StateArtifact**: base artifact identity in authoritative state.
- **DocumentArtifact**: concrete state artifact containing structured sections.
- **DeltaState**: proposed (non-authoritative) state change.
- **StateUpdateProposal**: explicit mutation request envelope for `StateService`.
- **Blackboard**: append-only durable event log for process history/provenance.
- **StateView / NorthStarView**: immutable rendered view for model reasoning.
- **Runtime Integration**: governance decision path over `GameResponse` (`runtime_integration.py`).
- **State-Centric Integration**: decision/proposal derivation path for potential state mutation (`integration.py`).

## Observations and Ambiguities
1. Two integration ontologies are active and valid, but distinct:
   - runtime governance (`schemas.IntegrationDecision`),
   - state-mutation derivation (`integration.IntegrationDecision`).
2. `baps-run` now has a hardened staged path plus legacy deterministic loop helper in the same module (`run_baps_loop`), which can blur product-path boundaries.
3. Replay projections (`projections.py`) and state views (`northstar_projection.py`) remain separate conceptual families with overlapping terminology.
4. `play_game` includes bounded retries and candidate selection, but accepted candidate integration into authoritative `State` is intentionally not yet in the executable `baps-run` path.
