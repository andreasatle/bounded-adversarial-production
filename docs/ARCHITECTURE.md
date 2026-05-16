# Bounded Adversarial Production (`baps`) Architecture

## 1. Project Overview

### Purpose of the framework
`baps` is a Python framework for bounded adversarial evaluation and state-centric iteration. The repository currently contains two implemented orchestration families:

1. adversarial runtime/game flow (`blue`/`red`/`referee`) with append-only event recording,
2. state-centric loop flow (`StateProgressor` -> `GameExecutor` -> `Integrator`) with explicit optional blackboard recording.

The codebase emphasizes typed contracts, deterministic behavior, and explicit boundaries between pure transformations and side-effecting persistence/event recording.

### Current project philosophy
Code-level philosophy visible across modules and tests:

- strong Pydantic model validation at boundaries,
- deterministic fake implementations for core orchestration seams,
- explicit append-only event logging for durable process memory,
- additive module growth (new orchestration slices added without replacing old runtime),
- separation between authoritative state models (`baps.state`) and operational history (`baps.blackboard`).

### Current architectural direction
The code is organized into overlapping but explicit slices:

- runtime/game slice: `runtime.py`, `game_service.py`, `roles.py`, prompt/model modules,
- event/governance slice: `blackboard.py`, `integrator.py`, `projections.py`,
- artifact filesystem slice: `artifacts.py`,
- state-centric slice: `state.py`, `state_store.py`, `state_service.py`, `northstar_projection.py`, `project_intake.py`, `state_progressor.py`, `game_executor.py`, `integration.py`, `loop.py`.

### What “bounded adversarial production” means in practice
Current concrete meaning in code:

- bounded: runtime loops cap rounds with `max_rounds`; role invocation retries are bounded.
- adversarial: Blue produces a move, Red produces a finding, Referee decides `accept`/`revise`/`reject`.
- production-oriented: runs emit durable blackboard events, integration decisions are appended, and replay/read models can be reconstructed.

In the newer state-centric loop, boundedness and determinism are represented via fake deterministic components and explicit loop sequencing.

### Current implementation vs future aspirations
Implemented now:

- deterministic runtime game execution with retry-guarded role invocation,
- append-only event persistence and replay projection,
- deterministic state-centric view/progress/execution/integration loop scaffolding,
- pure state update and state projection boundaries,
- explicit JSON state persistence boundary via `JsonStateStore`.

Not yet end-to-end implemented:

- real state mutation pipeline integrated with runtime game acceptance,
- adapter-specific document/git mutation semantics in `baps.state`,
- unified projection bridge between `projections.py` (event replay) and `northstar_projection.py` (state view rendering),
- tool-using or multi-agent adversarial runtime topology.

## 2. Current System Capabilities

### Schemas (`src/baps/schemas.py`)
Purpose:

- canonical runtime/event/governance/projection/artifact contracts.

Important classes/functions:

- request/contract: `Target`, `GameRequest`, `GameContract`.
- role outputs: `Move`, `Finding`, `Decision`.
- runtime results: `GameRound`, `GameState`, `GameResponse`, `RoundSummary`, `PlannedExecutionResult`.
- governance: `IntegrationDecision` and discrepancy/accepted-state lifecycle records.
- projection/read models: `ProjectedState` and list item records.
- artifact records: `Artifact`, `ArtifactVersion`, `ArtifactChange`, `ArtifactProposalRecord`.
- envelope: `Event`.

Current limitations:

- some cross-model semantics are enforced in service/policy code, not only schema validators.

Relationships:

- shared across runtime, blackboard, integrator, projections, planner, artifacts, and tests.

### Blackboard (`src/baps/blackboard.py`)
Purpose:

- append/read/query JSONL event log.

Important classes/functions:

- `Blackboard.append`, `read_all`, `query`, `query_by_run`, `query_completed_runs`.
- append helpers for integration/discrepancy/accepted-state/artifact-proposal events.

Current limitations:

- file scan queries, no indexing, no locking/transaction layer.

Relationships:

- runtime/game_service/integrator append and query events.
- `projections.py` and tests replay/query these events.
- `loop.record_loop_result` appends additional event types.

### Artifacts (`src/baps/artifacts.py`)
Purpose:

- filesystem artifact lifecycle (currently document-focused).

Important classes/functions:

- `ArtifactAdapter` interface, `ArtifactHandler` dispatcher.
- `DocumentArtifactAdapter.create/snapshot/propose_change/apply_change/rollback`.

Current limitations:

- only `document` adapter implemented.
- no automatic link from integration acceptance to artifact mutation.

Relationships:

- uses artifact models from `schemas.py`.
- separate from `baps.state` artifact references.

### Runtime (`src/baps/runtime.py`)
Purpose:

- bounded round-based game execution and event emission.

Important classes/functions:

- `RuntimeEngine.run_game`, `generate_run_id`, terminal response helpers.

Current limitations:

- single linear role sequence per round.
- no tool invocation layer.

Relationships:

- depends on `RoleInvocationGuard` and `Blackboard`.
- used by `game_service.py` and demos.

### Roles (`src/baps/roles.py`, `src/baps/example_roles.py`, `src/baps/prompt_roles.py`)
Purpose:

- role invocation enforcement and role implementations (deterministic + prompt-driven).

Important classes/functions:

- `RoleInvocationGuard`, `RoleInvocationError`.
- deterministic roles: `blue_role`, `red_role`, `referee_role`.
- prompt role builders: `make_prompt_*_role`, `build_prompt_roles`.

Current limitations:

- no tool protocol, no branching/multi-agent role graph.

Relationships:

- runtime invokes role callables through guard.
- prompt roles rely on prompt rendering and model clients.

### Prompt rendering (`src/baps/prompts.py`, `src/baps/prompt_assembly.py`)
Purpose:

- deterministic prompt template assembly and rendering.

Important classes/functions:

- `PromptSection`, `PromptSpec`, `assemble_prompt`, `PromptRenderer.render`, `render_prompt`.

Current limitations:

- `str.format`-based templating only.

Relationships:

- consumed by prompt roles and game type definitions.

### Model abstraction (`src/baps/models.py`)
Purpose:

- text-generation client abstraction.

Important classes/functions:

- `ModelClient`, `FakeModelClient`, `OllamaClient`.

Current limitations:

- no tool call abstraction, no built-in retry policy.

Relationships:

- used by prompt roles, planner code, and `ModelStateProgressor`.

### Ollama integration (`src/baps/models.py` + demo/CLI call sites)
Purpose:

- local Ollama HTTP `generate` requests.

Important behavior:

- non-streamed requests (`stream=False`) to `/api/generate`.
- validates non-empty input args and raises `RuntimeError` for transport/response failures.

Current limitations:

- no streaming, no retry/backoff.

Relationships:

- exercised by Ollama demo/CLI paths.

### Deterministic testing
Purpose:

- verify contracts and orchestration behavior without nondeterministic dependencies.

Important behavior:

- fake model/progressor/executor/integrator components,
- strict output and ordering assertions,
- heavy validation-path testing.

Current limitations:

- limited live integration behavior beyond deterministic checks.

Relationships:

- extensive tests across all slices in `tests/test_*.py`.

### Demo game execution
Purpose:

- provide runnable deterministic or Ollama-backed examples.

Important entry points:

- `baps-demo`, `baps-adversarial-demo`, `baps-ollama-adversarial-demo`, `baps-play-game`.

Current limitations:

- demos primarily exercise bounded scenario slices, not a complete autonomous production pipeline.

Relationships:

- demos coordinate runtime/service/game type/model modules.

## 3. Repository Structure

```text
src/baps/
  artifacts.py
  autonomous.py
  blackboard.py
  game_service.py
  integrator.py
  loop.py
  northstar_projection.py
  project_intake.py
  state.py
  state_store.py
  state_service.py
  state_progressor.py
  game_executor.py
  integration.py
  runtime.py
  roles.py
  prompt_roles.py
  prompts.py
  models.py
  projections.py
  schemas.py
  ...
tests/
  test_state.py
  test_state_store.py
  test_state_service.py
  test_northstar_projection.py
  test_project_intake.py
  test_state_progressor.py
  test_game_executor.py
  test_integration_models.py
  test_loop.py
  ...
docs/
  ARCHITECTURE.md
  STATE_MODEL.md
  ...
```

Important module map:

- `state.py`: authoritative state models, adapter registry, validation, projection, update application.
- `state_store.py`: persistence boundary (`StateStore`, `JsonStateStore`).
- `state_service.py`: load/validate/apply/save orchestration for state-only workflow.
- `northstar_projection.py`: north star view inputs, deterministic renderer, fingerprinting, immutable `StateView` alias (`NorthStarView`).
- `project_intake.py`: user-facing intake -> generated north star view.
- `state_progressor.py`: progressor input/output schemas, deterministic prompt rendering, strict JSON parser, fake/model-backed progressors.
- `game_executor.py`: execution result schema and fake executor.
- `integration.py`: integration decision schemas and fake integrator (state-centric loop slice).
- `loop.py`: minimal orchestration (`run_loop`) and explicit blackboard recording (`record_loop_result`).
- `integrator.py`: older runtime-response integration policy and blackboard append helpers (event-governance slice).
- `runtime.py`/`game_service.py`: bounded adversarial runtime orchestration.
- `projections.py`: event-replay projection from blackboard events.
- `artifacts.py`: filesystem artifact operations.

Boundary notes:

- `state.py` models are pure data/pure transforms.
- side effects are isolated in `blackboard.py`, `state_store.py`, `artifacts.py`, and networked model clients.

## 4. Core Runtime Flow

### A. Runtime game execution flow (`RuntimeEngine.run_game`)

1. create `run_id`.
2. append `game_started` event.
3. loop rounds up to `max_rounds`.
4. invoke Blue via `RoleInvocationGuard`.
5. append `blue_move_recorded`.
6. invoke Red.
7. append `red_finding_recorded`.
8. invoke Referee.
9. append `referee_decision_recorded`.
10. append round snapshot in memory.
11. terminate on `accept` or `reject`; continue on `revise` within budget.
12. construct `GameState`.
13. append `game_completed` with serialized final state.
14. return `GameState`.

### B. Prompt-driven role invocation flow

1. assemble prompt sections.
2. render with contract/context values.
3. model client `generate(prompt)`.
4. parse output to role model shape.
5. guard retries on schema/semantic failure.

### C. State-centric loop flow (`loop.run_loop`)

1. `proposal = progressor.progress(input)`.
2. `execution_result = executor.execute(proposal.game_proposal)`.
3. `decision = integrator.integrate(execution_result)`.
4. return `LoopResult(proposal, execution_result, decision)`.

### D. State persistence flow (`StateService.apply_update`)

1. load from `StateStore`.
2. validate artifacts through registry adapters.
3. apply pure `apply_state_update` transformation.
4. validate resulting state again.
5. save via `StateStore.save`.
6. return validated updated state.

### E. Blackboard recording for loop results (`record_loop_result`)

1. append `state_progression_proposed` event.
2. append `game_executed` event.
3. append `integration_decided` event.

All payloads are serialized model dumps; recording is explicit and separate from `run_loop`.

### Runtime state persistence / artifact interaction

- runtime game state durability is event-based through blackboard events.
- `baps.state` persistence is JSON-file-based when using `JsonStateStore`.
- `artifacts.py` lifecycle and `baps.state` update flow are currently separate systems.

## 5. Schema Documentation

### `baps.state` schemas

- `StateArtifact(id, kind)`.
  - both non-empty (whitespace-only rejected).
  - minimal artifact identity contract.

- `NorthStar(artifacts: tuple[StateArtifact, ...])`.
  - enforces unique artifact IDs within north star artifacts.

- `State(northstar, artifacts=())`.
  - enforces unique IDs within ordinary artifacts.
  - enforces no ID overlap between north star and ordinary artifacts.

- `StateUpdateTarget(artifact_id, section=None)`.
  - non-empty `artifact_id`; optional `section` if provided must be non-empty.

- `StateUpdateProposal(id, target, summary, payload={})`.
  - non-empty `id` and `summary`; isolated payload default via `default_factory`.

- `StateProjection(northstar=(), artifacts=())`.
  - tuple-of-strings projection output container.

### North star view schemas (`northstar_projection.py`)

- `ProjectionPolicy`: `VERBATIM`, `SUMMARIZED`, `FILTERED`, `DIRECT`.
- `NorthStarProjectionItem(id, content, source, authority, status, projection_policy)`.
- `NorthStarProjectionInput` with four typed categories:
  - `framework_policy`, `project_state`, `blackboard_history`, `runtime_context`.
- `ProjectionType`: currently `NORTH_STAR`.
- `StateView` (frozen/immutable):
  - `id`, `projection_type`, `content`, `input_fingerprint`, `metadata`.
- `NorthStarView = StateView` alias.

Why these exist:

- to preserve category/authority boundaries while producing deterministic model-readable views.

### State progress/execution/integration schemas

- `StateProgressorInput(id, northstar_view, runtime_objective)`.
- `GameProposal(id, title, description, expected_state_delta, risks=[])`.
- `StateProgressionProposal(id, input_id, game_proposal, rationale)`.
- `GameExecutionResult(id, game_proposal_id, status, summary, state_delta, risks=[])`.
- `StateChange(id, execution_result_id, summary, applied_delta, risks=[])`.
- `IntegrationDecision(id, state_change, accepted, rationale)`.
- `LoopResult(proposal, execution_result, decision)`.

Why these exist:

- to define a strictly typed end-to-end deterministic loop contract without integrating runtime mutation.

## 6. Blackboard/Event System

### Append-only philosophy

- `Blackboard` writes events as new JSONL lines.
- no in-place event mutation API.

### Event persistence

- one event per line, deserialized and validated into schema models.

### Event querying

- by type, by run ID, by completed-run convenience helpers.

### Event lifecycle

Two active event lifecycles:

1. runtime lifecycle (`game_started` -> move/finding/decision events -> `game_completed` + integration decision record).
2. state-loop lifecycle (`state_progression_proposed` -> `game_executed` -> `integration_decided`) via explicit `record_loop_result`.

### Intended role of blackboard

- durable process/operational memory and replay substrate.
- not the authoritative mutable state object itself.

## 7. Artifact System

### Runtime artifact lifecycle (`artifacts.py`)

- `create`, `snapshot`, `propose_change`, `apply_change`, `rollback` for document artifacts.

### State artifacts (`state.py`)

- minimal identity records (`StateArtifact`) and adapter-mediated validation/projection.

### Adapters / handler delegation

- runtime artifacts: `ArtifactHandler` delegates by `artifact.type`.
- state artifacts: `StateArtifactRegistry` resolves `StateArtifactAdapter` by `kind`.

### Snapshots / metadata / filesystem

`artifacts.py` document layout:

```text
<root>/<artifact_id>/
  metadata.json
  current/main.md
  versions/vNNN/
  changes/cNNN/{proposed.md,change.json}
```

### Assumptions and constraints

- document adapter is the only runtime filesystem adapter.
- state adapters for `document` and `git_repository` are deterministic stubs in `state.py`.

## 8. Runtime Engine

### Responsibilities

- execute bounded adversarial rounds,
- validate role outputs via guard,
- emit ordered events,
- return terminal runtime response.

### Role invocation guard

- retries schema/semantic validation failures up to configured attempts.
- raises `RoleInvocationError` on exhaustion.

### Retry behavior

- per-role invocation retry only.
- no global run retry orchestration.

### Game execution model

- linear Blue -> Red -> Referee round.
- deterministic termination semantics.

### Deterministic execution approach

- deterministic role/model doubles dominate tests.
- event ordering and payload shape are asserted explicitly.

## 9. Roles and Prompt System

### Deterministic example roles

- deterministic `blue_role`, `red_role`, `referee_role` implementations for repeatable runs.

### Prompt-driven roles

- render prompts, call `ModelClient`, parse into typed outputs.

### `PromptRenderer`

- thin deterministic string renderer around templates.

### `FakeModelClient`

- queued deterministic responses and captured prompts for assertions.

### `OllamaClient`

- synchronous HTTP generation call.

### Role execution flow

- game service constructs roles,
- runtime invokes through guard,
- outputs are validated and recorded as events.

### Current limitations

- no tool-use channel,
- no concurrent role graph,
- no adversarial runtime integration with the newer `run_loop` models.

## 10. Testing Strategy

### Current philosophy

- deterministic, contract-heavy, module-focused tests.

### Deterministic testing approach

- fakes for model/progressor/executor/integrator.
- strict parser/prompt tests (including snapshot-style prompt tests).

### Coverage currently present

- runtime/service/roles/prompt/model behavior,
- blackboard persistence/query and integration decision append semantics,
- projections replay,
- artifact filesystem lifecycle,
- state model/store/service/update/project flows,
- north star view rendering/fingerprint/policy behavior,
- state progressor parsing/rendering/model-backed flow,
- game executor/integration models and fake implementations,
- loop orchestration and explicit loop-event recording.

### Why deterministic tests matter here

- the architecture relies on exact boundary contracts and replay/inspection behaviors; deterministic tests prevent hidden drift.

## 11. Architectural Invariants (Enforced)

Only directly enforced invariants are listed:

1. non-empty validation for key ID/string fields across schema families.
2. runtime round count and counters are bounded.
3. role outputs must validate via schema + semantic checks.
4. blackboard writes are append-only by API shape.
5. state artifact IDs are unique within each group and disjoint across north star vs ordinary artifacts.
6. state adapter registry rejects empty/duplicate kinds and unknown kind resolution.
7. `validate_state_artifacts` forbids adapter mutation of artifact `id`/`kind`.
8. `project_state` rejects empty adapter projection strings.
9. `apply_state_update` supports only `replace_artifact`; replacement must preserve target ID and kind.
10. north star renderer currently only accepts `ProjectionPolicy.VERBATIM` at render time.
11. north star fingerprinting is deterministic SHA-256 over canonical JSON (`sort_keys=True`).
12. `StateView`/`NorthStarView` are frozen (immutable model fields).
13. `run_loop` itself performs no blackboard writes; recording is explicit via `record_loop_result`.

## 12. Current Architectural Direction

### Implemented

- bounded adversarial runtime with durable event traces,
- state-centric typed loop with deterministic fakes,
- explicit state/view/update/store boundaries,
- explicit blackboard recording boundaries.

### Conceptual/future (inferred from module layout and constraints)

- integrate state-centric loop outputs with real state mutation decisions,
- unify old and new integration surfaces (`integrator.py` vs `integration.py`),
- bridge event-replay projections and north star view rendering,
- add richer tool-enabled and multi-role orchestration.

## 13. Current Limitations

Concrete current limits:

- `apply_state_update` only implements `replace_artifact` and no artifact-specific edit semantics.
- `DocumentArtifactAdapter` and `GitRepositoryArtifactAdapter` in `state.py` are stubs.
- no runtime/planner/game_service integration with `StateService` update flow.
- no persistence/versioning beyond simple JSON state file for `JsonStateStore`.
- no automatic coupling between accepted integration decisions and durable state mutation.
- no summarization/filtering behavior in north star rendering despite policy enum values.
- two integration model surfaces coexist (`integrator.py` runtime-governance models vs `integration.py` state-loop models).

## 14. Suggested Next Milestones (Additive, based on current code)

1. Add a narrow adapter-based `replace_artifact` specialization path keyed by `kind` while keeping `apply_state_update` pure.
2. Add a bridge module that maps `LoopResult` + `IntegrationDecision` into `StateUpdateProposal` generation (still explicit, no implicit mutation).
3. Add explicit read-model adapters from blackboard event types (`state_progression_proposed`, `game_executed`, `integration_decided`) into projections.
4. Add conformance tests for cross-slice ID linkage consistency (input -> proposal -> execution -> decision).
5. Add explicit human-approval state for north star-targeted state updates.
6. Define and test a single integration facade to reconcile `integrator.py` and `integration.py` semantics.

## 15. Developer Workflow

### Running tests

```bash
uv run pytest
```

### Typical additive workflow in this repository

1. add or extend typed model/protocol boundary.
2. add deterministic tests (success + failure paths).
3. implement narrow behavior slice.
4. keep side-effecting integration explicit (store/blackboard/runtime calls).
5. run full suite.

### Commit/iteration style currently reflected

- small narrow milestones,
- boundary hardening before integration,
- documentation updates after each architectural slice.

### Contributor expectations

- preserve established terms and module boundaries,
- document inconsistencies as observations,
- avoid hidden side effects in pure model/transform modules.

## 16. Glossary

- **Game**: bounded adversarial runtime execution under `GameContract`.
- **Role**: callable participant (`blue`, `red`, `referee`) in runtime loop.
- **Move**: Blue role output.
- **Finding**: Red role critique output.
- **Decision**: Referee output controlling round continuation/termination.
- **State**: authoritative project condition (`baps.state.State`).
- **NorthStar**: dedicated authoritative target artifact group inside `State`.
- **StateArtifact**: minimal state artifact identity (`id`, `kind`).
- **StateView / NorthStarView**: immutable rendered view artifact from north star projection inputs.
- **Blackboard**: append-only durable process-memory event log.
- **StateProgressor**: component producing a `StateProgressionProposal` from `StateProgressorInput`.
- **GameProposal**: proposed execution candidate from progressor output.
- **GameExecutor**: component producing `GameExecutionResult` from `GameProposal`.
- **Integrator**: component producing `IntegrationDecision` from execution result.
- **LoopResult**: tuple model of proposal + execution result + decision.
- **PromptRenderer**: prompt template rendering utility for role/prompt paths.
- **ModelClient**: model generation interface (`FakeModelClient`, `OllamaClient`).

## Observations and Ambiguities

1. Two integration surfaces coexist with different schemas:
   - `baps.integrator` (runtime `GameResponse` -> `schemas.IntegrationDecision` + blackboard append helpers),
   - `baps.integration` (state-loop `GameExecutionResult` -> `integration.IntegrationDecision`).
2. Two projection systems coexist:
   - event replay projection (`projections.py`),
   - north star deterministic view rendering (`northstar_projection.py`).
   No canonical bridge currently exists.
3. Two artifact concepts coexist:
   - filesystem artifact lifecycle (`artifacts.py`),
   - minimal authoritative state artifacts (`state.py`).
   Integration contract is not yet implemented.
4. `ProjectionPolicy` defines four enum values, but renderer behavior currently supports only `VERBATIM` and rejects others.
5. `StateService` persists via JSON file store, but there is no transaction/locking mechanism for concurrent writers.
