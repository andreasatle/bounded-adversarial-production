# Bounded Adversarial Production (`baps`) Architecture

## 1. Project Overview

### Purpose of the framework
`bounded-adversarial-production` (`baps`) implements a bounded adversarial execution pattern around three roles (`blue`, `red`, `referee`) and records durable runtime/governance traces in an append-only blackboard. The repository provides:

- a runtime loop for bounded game execution,
- typed contracts (Pydantic) for requests, moves, findings, decisions, and outcomes,
- integration-policy recording,
- replay-based projected state,
- planner/autonomous orchestration helpers,
- artifact lifecycle primitives,
- and a separate in-memory `State` model boundary (`src/baps/state.py`) for authoritative project condition.

### Current project philosophy
Observed code-level philosophy:

- strict typed boundaries at module edges,
- deterministic tests preferred over nondeterministic integration tests,
- append-only event history for durable replay,
- additive layering (new modules added without replacing core runtime),
- explicit separation between execution semantics and integration semantics.

### Current architectural direction
Current code is split into layers:

- Execution: `game_service.py` + `runtime.py` + role/model/prompt modules.
- Durable memory: `blackboard.py` event log + append helpers.
- Governance: `integrator.py` and lifecycle events.
- Replay/read model: `projections.py`.
- Planning: `planner.py` and `autonomous.py`.
- Artifact lifecycle: `artifacts.py`.
- State boundary slice: `state.py` (pure typed authoritative state + adapter dispatch skeletons).

### What “bounded adversarial production” means in practice
In current implementation:

- **Bounded**: execution rounds are limited by `max_rounds`; revision loops stop at budget.
- **Adversarial**: Blue proposes, Red critiques, Referee decides.
- **Production-oriented**: outputs are persisted as structured events; replay derives projected state; integration decision events establish durable acceptance/defer outcomes.

### Current implementation vs future aspirations
Implemented now:

- deterministic/game-loop execution with retry-guarded role invocation,
- append-only event logging and replay projection,
- integration decision policies and idempotent append behavior,
- state-source ingestion for context,
- pure `State`/adapter/projection/update-boundary APIs in `baps.state`.

Conceptual/future (not implemented end-to-end):

- tool-execution boundaries inside runtime roles,
- richer multi-role adversarial orchestration,
- automatic artifact mutation from accepted decisions,
- full human-approval workflow for NorthStar updates,
- broader convergence between `baps.state` projection/update APIs and runtime/planner pipelines.

## 2. Current System Capabilities

### Schemas (`src/baps/schemas.py`)
Purpose:
- canonical contracts for runtime inputs/outputs, event payloads, integration records, projection records, planner metadata, and artifact records.

Important classes/functions:
- runtime contracts: `GameRequest`, `GameContract`, `Target`.
- role outputs: `Move`, `Finding`, `Decision`.
- run/result: `GameRound`, `GameState`, `GameResponse`, `RoundSummary`, `PlannedExecutionResult`.
- governance: `IntegrationDecision`, discrepancy/accepted-state lifecycle models.
- projection models: `ProjectedState`, accepted/discrepancy summaries.
- artifact models: `Artifact`, `ArtifactVersion`, `ArtifactChange`, `ArtifactProposalRecord`.
- envelope: `Event`.

Current limitations:
- cross-object policies are often enforced in service/runtime/integrator modules, not entirely in schemas.
- `GameRecord` exists but is not persisted by runtime/service.

Relationships:
- shared by runtime, blackboard, integrator, projections, planner, artifacts, and tests.

### Blackboard (`src/baps/blackboard.py`)
Purpose:
- append/read/query JSONL event store.

Important classes/functions:
- `Blackboard.append`, `read_all`, `query`, `query_by_run`, `query_completed_runs`.
- typed append helpers for integration/discrepancy/accepted-state/artifact-proposal events.

Current limitations:
- no locking, no indexing, no compaction.
- queries scan full file.

Relationships:
- runtime and integrator emit events.
- projections replay events.

### Artifacts (`src/baps/artifacts.py`)
Purpose:
- filesystem artifact lifecycle for document artifacts.

Important classes/functions:
- `ArtifactAdapter` abstract interface.
- `ArtifactHandler` adapter dispatch by `artifact.type`.
- `DocumentArtifactAdapter.create/snapshot/propose_change/apply_change/rollback`.

Current limitations:
- only `document` type implemented.
- no merge/conflict logic.
- no default coupling to runtime or integration acceptance.

Relationships:
- uses `schemas.py` artifact models.
- operationally separate from runtime loop.

### Runtime (`src/baps/runtime.py`)
Purpose:
- execute bounded game loop and persist round events.

Important classes/functions:
- `RuntimeEngine.run_game`.
- `generate_run_id`.
- `build_game_response` + terminal semantics helpers.

Current limitations:
- fixed single blue/red/referee sequence per round.
- no tool system.
- no branching or parallel role execution.

Relationships:
- depends on `Blackboard` and `RoleInvocationGuard`.
- called by `GameService` and demos.

### Roles (`src/baps/roles.py`, `src/baps/example_roles.py`, `src/baps/prompt_roles.py`)
Purpose:
- role invocation guard + deterministic and prompt-driven role implementations.

Important classes/functions:
- `RoleInvocationGuard`, `RoleInvocationError`.
- deterministic role fns: `blue_role`, `red_role`, `referee_role`.
- prompt role factories: `make_prompt_blue_role`, `make_prompt_red_role`, `make_prompt_referee_role`.
- `build_prompt_roles` and default profile builders.

Current limitations:
- no tool invocation protocol.
- referee decision in prompt path is still locally computed from finding properties; model supplies rationale text.

Relationships:
- runtime consumes role callables.
- prompt roles depend on prompt/model modules.

### Prompt rendering (`src/baps/prompts.py`, `src/baps/prompt_assembly.py`)
Purpose:
- compose prompt sections and render string templates.

Important classes/functions:
- `PromptSection`, `PromptSpec`, `assemble_prompt`.
- `PromptRenderer.render`, `render_prompt`.

Current limitations:
- `str.format` rendering only.
- no templating sandbox/escaping layer.

Relationships:
- used by prompt role factories and game type definitions.

### Model abstraction (`src/baps/models.py`)
Purpose:
- model-client abstraction for prompt generation.

Important classes/functions:
- `ModelClient` interface.
- `FakeModelClient`.
- `OllamaClient`.

Current limitations:
- no chat/tool abstraction.
- no client retry/backoff strategy.

Relationships:
- used by prompt roles, `GameService`, and `LLMPlanner`.

### Ollama integration
Purpose:
- local Ollama inference integration via HTTP POST.

Important behavior:
- endpoint: `{base_url}/api/generate`, payload includes `stream=False`.
- validates non-empty model/base_url/prompt.
- raises `RuntimeError` on HTTP/URL errors or malformed response.

Current limitations:
- no stream support.
- no retry/backoff.

Relationships:
- used in CLI + Ollama demo paths.

### Deterministic testing
Purpose:
- verify behavior contracts with reproducible results.

Important behavior:
- fake model responses and deterministic role outputs dominate tests.
- event ordering, validation behavior, projection replay logic are heavily asserted.

Current limitations:
- limited end-to-end nondeterministic/live integration testing.

Relationships:
- all core modules have focused tests.

### Demo game execution
Purpose:
- run narrow deterministic or Ollama-backed examples.

Important entry points:
- `baps-demo`, `baps-adversarial-demo`, `baps-ollama-adversarial-demo`, `baps-play-game`.

Current limitations:
- demos exercise bounded paths, not full autonomous pipelines.

Relationships:
- demos call runtime/service modules with fixed contracts.

## 3. Repository Structure

```text
src/baps/
  adversarial_demo.py
  artifacts.py
  autonomous.py
  blackboard.py
  demo.py
  example_roles.py
  game_service.py
  game_types.py
  integrator.py
  models.py
  ollama_adversarial_demo.py
  planner.py
  play_game.py
  prompt_assembly.py
  prompt_roles.py
  prompts.py
  projections.py
  role_output_parsing.py
  roles.py
  run_specs.py
  runtime.py
  schemas.py
  state.py
  state_sources.py
examples/
  game_definitions/
  runs/
  state_manifests/
tests/
  test_*.py
docs/
  ARCHITECTURE.md
  STATE_MODEL.md
  ...
```

Module map (purpose, key APIs, dependencies, boundaries):

- `schemas.py`: Pydantic contracts; central dependency for most modules; no side effects.
- `runtime.py`: game loop + response derivation; depends on `roles.py`, `blackboard.py`, `schemas.py`.
- `roles.py`: invocation guard only; no blackboard logic.
- `example_roles.py`: deterministic and prompt-based role callables; depends on prompts/parsers/models.
- `prompt_assembly.py`: section-level prompt structuring.
- `prompts.py`: rendering wrapper around `str.format`.
- `prompt_roles.py`: assembles role prompts from game-type sections and optional profiles.
- `models.py`: fake and Ollama model clients.
- `blackboard.py`: JSONL event persistence and typed append helpers.
- `integrator.py`: integration policies and idempotent appending.
- `projections.py`: replay from events to projected state and query helpers.
- `planner.py`: deterministic and LLM planner APIs.
- `autonomous.py`: bounded repeated plan+play orchestration.
- `game_types.py`: built-in/file game definitions.
- `game_service.py`: orchestration boundary from `GameRequest` to `GameResponse` + integration decision append.
- `state_sources.py`: state source manifest + adapters (`markdown_doc`, `jsonl_event_log`, `directory`, `git_repo`).
- `run_specs.py`: YAML run spec parsing.
- `play_game.py`: CLI integration layer.
- `artifacts.py`: filesystem artifact lifecycle.
- `state.py`: pure authoritative-state API slice (state models, registry, projection/update dispatch skeletons).

## 4. Core Runtime Flow

### Sequence: game execution
`RuntimeEngine.run_game(contract, blue_role, red_role, referee_role)`:

1. create `run_id`.
2. append `game_started` event.
3. enter round loop (1..`max_rounds`).
4. determine Blue call signature (`contract` only or `contract + revision_context`).
5. invoke Blue via `RoleInvocationGuard` -> `Move`.
6. append `blue_move_recorded`.
7. invoke Red via guard -> `Finding`.
8. append `red_finding_recorded`.
9. invoke Referee via guard -> `Decision`.
10. append `referee_decision_recorded`.
11. append round state to in-memory `rounds`; update previous-context.
12. stop on `accept`/`reject`; continue on `revise` when budget remains.
13. construct `GameState`.
14. derive terminal semantics and append `game_completed`.
15. return `GameState`.

### Role invocation flow
`RoleInvocationGuard.invoke(...)`:

1. call role callable.
2. validate output against target Pydantic model.
3. run optional semantic validator.
4. retry on schema or semantic failure up to `max_attempts`.
5. raise `RoleInvocationError` after exhaustion.

### Prompt rendering flow
Prompt roles call sequence:

1. assemble template sections.
2. build context dict from contract + optional shared context.
3. render via `PromptRenderer.render`.
4. call model client `generate(prompt)`.
5. parse model text (JSON-path or fallback text) into schema models.

### Model call flow
- Fake path: deterministic queue return from `FakeModelClient.responses`.
- Ollama path: HTTP POST via `OllamaClient.generate`.

### Runtime state persistence
- `GameState` is returned in memory.
- durable persistence is event-based (`blackboard/*.jsonl`), not a DB state table.
- completed event payload embeds serialized state.

### Blackboard event recording
Per run, runtime records ordered game events; game service then appends integration decision event through integrator helper.

### Artifact interaction with runtime
- `src/baps/artifacts.py` is not called in default runtime/service flow.
- artifact proposal events exist in blackboard schema, but automatic artifact mutation flow is not wired.
- `src/baps/state.py` is a separate pure state boundary and is also not wired into runtime/service yet.

## 5. Schema Documentation

Important model groups and rationale:

### Runtime contracts
- `Target(kind, ref)`.
- `GameRequest(game_type, subject, goal, target_kind, target_ref, state_source_ids, planner_grounding)`.
- `GameContract(id, subject, goal, target, active_roles, max_rounds, scope_allowed, scope_forbidden)`.

Why:
- normalize request/contract boundaries and prevent malformed runtime inputs.

Validation behavior:
- non-empty required strings.
- `active_roles` non-empty.
- `max_rounds >= 1`.
- non-empty entries for `state_source_ids`.

### Runtime outputs/state
- `Move`, `Finding`, `Decision`, `GameRound`, `GameState`, `RoundSummary`, `GameResponse`.

Why:
- preserve structured decision trace and terminal semantics with consistent shape.

Validation behavior:
- non-empty key fields.
- bounded numeric fields (`round_number`, `current_round`, etc.).
- terminal semantic literals constrain outcomes.

### Governance/projection records
- `IntegrationDecision`, discrepancy lifecycle records, accepted-state lifecycle records, `ProjectedState` and list item models.

Why:
- represent durable acceptance/discrepancy lifecycle and replay-derived state.

### Artifact records
- `Artifact`, `ArtifactVersion`, `ArtifactChange`, `ArtifactAdapterResult`, `ArtifactProposalRecord`.

Why:
- normalize local artifact lifecycle operations and event records.

### Event envelope
- `Event(id, type, payload)`.

Why:
- common append-only event container for all durable blackboard records.

## 6. Blackboard/Event System

### Append-only philosophy
- `Blackboard.append` only appends new JSONL lines.
- no update/delete API on existing events.

### Event persistence
- persisted as one JSON object per line.
- validated on read through `Event.model_validate`.

### Event querying
- `query(type)` filters by event type.
- `query_by_run(run_id)` filters payload run id.
- `query_completed_runs()` convenience wrapper.

### Event lifecycle
Typical lifecycle for one `GameService.play` run:

1. runtime emits game events (`game_started` -> role events -> `game_completed`).
2. service/integrator emits `integration_decision_recorded`.
3. optional external calls may append discrepancy/accepted-state/artifact-proposal lifecycle events.
4. projections replay all events to compute current projected state.

### Intended future role (as indicated by code organization)
- durable process memory source for replay, review queues, and lifecycle transitions.
- not a replacement for the pure authoritative `State` model in `src/baps/state.py`.

## 7. Artifact System

### Artifact lifecycle
`DocumentArtifactAdapter` flow:

1. `create`: initialize artifact directory and metadata.
2. `snapshot`: copy current state to next version directory.
3. `propose_change`: record diff + proposed content.
4. `apply_change`: copy proposal into `current/main.md` then snapshot.
5. `rollback`: restore `current/` from chosen version.

### Adapters and delegation
- `ArtifactHandler` resolves adapter by `artifact.type` and delegates operations.
- unknown types raise `ValueError`.

### Snapshots and metadata
- version ids are sequential (`v001`, `v002`, ...).
- proposal ids are sequential (`c001`, `c002`, ...).
- metadata serialized to `metadata.json` from artifact model.

### Filesystem structure
```text
<root>/<artifact_id>/
  metadata.json
  current/
    main.md
  versions/
    v001/
  changes/
    c001/
      proposed.md
      change.json
```

### Assumptions/constraints
- only document adapter implemented.
- no durable lock/transaction mechanism.
- apply/rollback do not require integration decision events.

## 8. Runtime Engine

### Runtime responsibilities
- enforce bounded round semantics,
- validate role outputs with schema + semantic checks,
- emit ordered runtime events,
- return structured in-memory `GameState`.

### Role invocation guard
- configurable `max_attempts` (default 2),
- classifies failures (`schema_validation_failed`, `semantic_validation_failed`, etc.),
- raises explicit `RoleInvocationError`.

### Retry behavior
- retries are local to each role invocation.
- full-run retries are not implemented.

### Game execution model
- linear sequence per round: Blue -> Red -> Referee.
- termination on `accept`/`reject`; controlled continuation for `revise`.

### Deterministic execution approach
- deterministic role functions and fake model responses in tests.
- strict event ordering assertions.

## 9. Roles and Prompt System

### Deterministic example roles
- `blue_role`: fixed bounded proposal.
- `red_role`: finding referencing blue summary.
- `referee_role`: decision/rationale referencing role outputs.

### Prompt-driven roles
- blue: render prompt, parse JSON/text summary.
- red: parse JSON or `MATERIAL/CLAIM` text format.
- referee: compute decision from finding flags, generate rationale text.

### PromptRenderer
- `PromptRenderer(template).render(context)` with non-empty output check.

### FakeModelClient
- returns queued responses in order,
- records prompts for test assertions,
- raises when queue is exhausted.

### OllamaClient
- synchronous non-streamed HTTP generation.

### Role execution flow
- game service builds prompt roles,
- runtime invokes roles through guard,
- validated role models are emitted as game events.

### Current limitations
- no tool system,
- no true multi-agent adversarial topology,
- no external environment action loop.

## 10. Testing Strategy

### Philosophy
- behavior-first tests with deterministic inputs and explicit error-path coverage.

### Deterministic approach
- `FakeModelClient` for predictable role/planner outputs.
- deterministic role stubs in runtime tests.
- no network calls in core unit tests.

### Coverage areas
- schema validation (`test_schemas.py`),
- runtime loop/terminal semantics (`test_runtime.py`),
- role guard (`test_roles.py`),
- prompt rendering/assembly/role parsing,
- blackboard persistence/query,
- integrator policies/idempotence,
- projections replay logic,
- artifacts lifecycle,
- CLI/run-spec/state-source ingestion,
- state-model slice APIs (`test_state.py`).

### Why deterministic tests matter
- replay semantics, event order, and bounded decision logic must remain stable.
- deterministic fixtures prevent false positives from model/network variance.

## 11. Architectural Invariants (Enforced in code)

Only invariants with direct enforcement:

1. required schema fields must be non-empty where validators exist.
2. runtime `max_rounds` and round counters are bounded (`>=1`).
3. role outputs must pass Pydantic + semantic validation.
4. runtime event emission order is deterministic per run path.
5. blackboard API is append/read/query; no in-place mutation API.
6. integration append helper prevents duplicate decision IDs.
7. projection replay is deterministic for identical ordered events.
8. `baps.state` invariants:
   - unique IDs within `NorthStar.artifacts` and `State.artifacts`,
   - no overlap between northstar and ordinary artifact IDs,
   - adapter registry rejects empty/duplicate kinds,
   - `validate_state_artifacts` forbids adapter mutation of `id`/`kind`,
   - `project_state` requires non-empty projection strings,
   - `apply_state_update` validates target existence then refuses application (`NotImplementedError`).

## 12. Current Architectural Direction

### Implemented direction
- bounded adversarial rounds,
- event-first durability,
- deterministic integration recommendation recording,
- replay-driven projected state,
- pure `State` boundary APIs for authoritative-state modeling (currently local module only).

### Conceptual/future direction (inferred from modules/docs/tests)
- tighter coupling of state boundary with planner/runtime flow,
- richer referee/adversarial interaction patterns,
- future tool-boundary and action execution,
- explicit human authority workflows (especially around NorthStar updates),
- broader pipeline generation from discrepancies and accepted outcomes.

## 13. Current Limitations

Concrete gaps:

- `baps.state` is not integrated with runtime/planner/game_service/blackboard.
- no real update application in `apply_state_update`.
- no persistence/materialization layer for `baps.state`.
- document/git adapters in `baps.state` are deterministic stubs.
- `artifacts.py` and `state.py` are separate artifact concepts (operational filesystem lifecycle vs authoritative-state adapter slice).
- no tool execution path in runtime roles.
- no multi-agent concurrent game topology.
- no automatic artifact integration from accepted decisions.

What would be needed for a fuller adversarial loop:

- role/tool request protocol,
- richer round orchestration and role graph,
- explicit state mutation pipeline from accepted integration decisions,
- reconciliation between `baps.state` projection and existing `projections.py` event replay pipeline.

## 14. Suggested Next Milestones (Additive)

1. Add a read-only bridge from runtime/integration outputs to `baps.state` constructor inputs (no mutation yet).
2. Introduce typed adapter-backed artifact subclasses (still side-effect free) to reduce `kind` string ambiguity.
3. Add explicit update-application policy interface in `baps.state` that remains pure but no longer hard-fails all known targets.
4. Add a deferred `NorthStar` update decision record type and explicit human-approval status transitions.
5. Add adapter conformance checks (runtime typing/shape checks) in `StateArtifactRegistry`.
6. Add integration tests that compare `project_state` output with selected replay projections to prevent drift.

## 15. Developer Workflow

### Running tests
```bash
uv run pytest
```

### Typical development pattern in this repository
1. add or adjust schema/types.
2. add deterministic tests for success + failure paths.
3. implement narrow additive behavior in one module.
4. avoid redesigning unrelated subsystems.
5. run full test suite.

### Commit style observed in current iteration
- small, additive slices,
- explicit boundary hardening before integration,
- documentation updated to match implemented APIs.

### Contributor expectations
- preserve current terminology (`blue`, `red`, `referee`, `blackboard`, `integration`, `projection`, `state`).
- avoid silent behavior changes; document observations when inconsistencies are found.
- keep side effects in explicit service/adapter layers, not core schema/state models.

## 16. Glossary

- **Game**: one bounded runtime execution under a `GameContract`.
- **Role**: callable participant (`blue`, `red`, `referee`) invoked by runtime.
- **Move**: Blue output (`Move`) for a round.
- **Finding**: Red critique output (`Finding`).
- **Decision**: Referee output (`Decision`) controlling termination/continuation.
- **Artifact (runtime/artifacts module)**: filesystem-managed object in `src/baps/artifacts.py`.
- **StateArtifact (`baps.state`)**: minimal authoritative-state artifact reference (`id`, `kind`).
- **Blackboard**: append-only JSONL durable process memory.
- **Runtime**: bounded execution engine (`RuntimeEngine`).
- **PromptRenderer**: string template renderer used by prompt-driven roles.
- **ModelClient**: interface for text generation (`FakeModelClient`, `OllamaClient`).
- **Projection (event replay)**: `src/baps/projections.py` replay of blackboard events into `ProjectedState`.
- **StateProjection (`baps.state`)**: pure adapter-projected view of authoritative state artifacts.
- **Integration decision**: durable accepted/deferred/rejected record appended to blackboard.

## Observations and Ambiguities

1. `GameContract.active_roles` is validated but runtime invocation order is fixed and does not consult that list.
2. `GameRecord` schema exists without runtime/service persistence usage.
3. Two projection concepts now coexist:
   - event-replay projection (`src/baps/projections.py`),
   - authoritative-state adapter projection (`src/baps/state.py`).
   No integration bridge exists yet.
4. Two artifact systems coexist:
   - filesystem artifact lifecycle (`src/baps/artifacts.py`),
   - minimal authoritative-state artifact references (`src/baps/state.py`).
   Their integration contract is not yet implemented.
5. `apply_state_update` validates target existence but intentionally raises `NotImplementedError` for known targets; update pipeline is boundary-only at this stage.
