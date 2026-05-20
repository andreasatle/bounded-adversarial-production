# Bounded Adversarial Production (`baps`) Architecture

## 1. Project Overview
### Purpose of the framework
`baps` is a Python framework for bounded adversarial reasoning and controlled state evolution.

The repository currently contains:
- a runtime adversarial game pipeline (`blue` -> `red` -> `referee`) with append-only blackboard event persistence,
- a state-centric mutation pipeline (`State` + `StateService`) with explicit `StateUpdateProposal` boundaries,
- a product-shaped CLI (`baps-run`) that executes lifecycle commands (`init`, `run`, `init_and_run`) over persisted `State`.

### Current project philosophy
The implemented code enforces:
- explicit contracts at boundaries using Pydantic models,
- bounded loops (`max_rounds`, `max_attempts`, `max_iterations`),
- deterministic testability with fake model clients and deterministic fakes,
- append-only process history for runtime path (`Blackboard`),
- explicit mutation boundary for authoritative state (`StateService.apply_update`).

### Current architectural direction
The codebase is currently dual-path, not single-path:
- runtime/event path: `runtime.py`, `game_service.py`, `runtime_integration.py`, `blackboard.py`, `projections.py`, `schemas.py`.
- state/product path: `run.py`, `state.py`, `state_service.py`, `state_store.py`, `northstar_projection.py`, `integration.py`, `loop.py`.

`baps-run` is the most product-shaped executable surface and currently owns the canonical CLI lifecycle.

### What “bounded adversarial production” means in practice
In implemented behavior:
- **bounded**: all loops have explicit caps,
- **adversarial**: Blue proposes, Red critiques, Referee adjudicates,
- **production**: persistence boundaries and schema validation are explicit and test-covered.

### Current implementation vs future aspirations
Implemented now:
- strict schema validation and deterministic tests,
- runtime engine with blackboard history,
- state service with fingerprint checks and update validation,
- LLM-backed `CreateGame` and `PlayGame` stages in `baps-run`.

Not yet implemented as one unified architecture:
- single ontology for integration decisions (there are parallel models),
- full unification of runtime event pipeline and `baps-run` product path,
- tool-call execution framework or generalized multi-agent topology.

## 2. Current System Capabilities
### Schemas (`src/baps/schemas.py`)
Purpose:
- Define runtime/event/replay/gov contracts.

Important classes:
- game contract/execution: `GameRequest`, `GameContract`, `GameState`, `GameRound`, `GameResponse`.
- role outputs: `Move`, `Finding`, `Decision`.
- runtime integration decision: `schemas.IntegrationDecision`.
- replay/read models: `ProjectedState` and accepted/discrepancy records.
- event envelope: `Event`.

Current limitations:
- Runtime schema ontology and state-centric ontology are separate.

Relationships:
- Used by runtime engine, blackboard persistence, runtime integration, projections, and planner/autonomous modules.

### Blackboard (`src/baps/blackboard.py`)
Purpose:
- Append-only event log persisted as JSONL.

Important methods:
- `append`, `read_all`, `query`, `query_by_run`, `query_completed_runs`.
- typed append helpers for integration/discrepancy/accepted-state/artifact proposal events.

Current limitations:
- simple file-backed storage; no indexing/locking/concurrency controls.

Relationships:
- Runtime path and runtime integration append events; projections consume events.

### Artifacts (`src/baps/artifacts.py`)
Purpose:
- Filesystem lifecycle operations for `schemas.Artifact`.

Important classes/functions:
- `ArtifactAdapter` interface,
- `ArtifactHandler` delegator,
- `DocumentArtifactAdapter` implementing `create`, `snapshot`, `propose_change`, `apply_change`, `rollback`.

Current limitations:
- only document adapter implemented,
- not integrated into `baps-run` state mutation path.

Relationships:
- Separate from `state.py` authoritative state models.

### Runtime (`src/baps/runtime.py`)
Purpose:
- Execute bounded adversarial games and emit ordered events.

Important classes/functions:
- `RuntimeEngine.run_game`,
- `build_game_response`,
- terminal semantics derivation (`_derive_terminal_semantics`).

Current limitations:
- fixed role order (`blue`, `red`, `referee`),
- no tool execution protocol,
- not the active orchestration path for `baps-run`.

Relationships:
- Uses `RoleInvocationGuard`, `Blackboard`, `schemas` contracts.

### Roles (`src/baps/roles.py`, `src/baps/example_roles.py`, `src/baps/prompt_roles.py`)
Purpose:
- role invocation guardrails and deterministic/prompt-backed role implementations.

Important classes/functions:
- `RoleInvocationGuard.invoke` with schema + semantic retries,
- deterministic role factories in `example_roles.py`,
- prompt role assembly in `prompt_roles.py`.

Current limitations:
- no dynamic role graph or tool calls.

Relationships:
- consumed by runtime/game-service path.

### Prompt rendering (`src/baps/prompts.py`, `src/baps/prompt_assembly.py`)
Purpose:
- structured prompt assembly and rendering.

Important classes/functions:
- `PromptRenderer`,
- `PromptSpec`, `PromptSection`, `assemble_prompt`.

Current limitations:
- simple template composition only.

### Model abstraction (`src/baps/models.py`)
Purpose:
- abstract generation API and provider implementations.

Important classes:
- `ModelClient`,
- `FakeModelClient`,
- `OllamaClient`.

Current limitations:
- no built-in retries/streaming/backpressure management.

### Ollama integration
- Implemented by `OllamaClient.generate` via `/api/generate` with `stream=False`.
- Raises runtime errors when HTTP fails or response shape is invalid.

### Deterministic testing
- Test suite uses `FakeModelClient` and explicit fakes extensively.
- Assertions cover schema validation failures, orchestration boundaries, event ordering, and lifecycle conditions.

### Demo game execution
Current scripts in `pyproject.toml`:
- `baps-demo`, `baps-adversarial-demo`, `baps-ollama-adversarial-demo`,
- `baps-play-game`, `baps-state-loop-demo`,
- `baps-run`.

`baps-run` is the active product-shaped command for lifecycle/state mutation/export.

## 3. Repository Structure
```text
src/baps/
  run.py                   # product CLI lifecycle and adapter-dispatched loop
  state.py                 # authoritative state + deltas + update application
  state_store.py           # state persistence adapter (JSON)
  state_service.py         # validation + apply_update boundary
  northstar_projection.py  # StateView/NorthStarView projection models and renderer
  loop.py                  # state-centric loop composition helpers
  integration.py           # state-centric integration models/derivation

  runtime.py               # runtime adversarial engine + event emission
  game_service.py          # request -> runtime engine -> integration append
  runtime_integration.py   # runtime-side integration policy

  schemas.py               # runtime/replay/event schema surface
  blackboard.py            # append-only JSONL event store
  projections.py           # replay projections from events
  artifacts.py             # filesystem artifact lifecycle adapters

  roles.py                 # role invocation guard
  prompt_roles.py          # prompt-backed role construction
  prompts.py               # prompt renderer
  prompt_assembly.py       # structured prompt assembly
  models.py                # Fake/Ollama model clients

tests/
  comprehensive unit tests for runtime/state/run/blackboard/projections/artifacts
```

Module responsibilities and boundaries:
- `run.py` owns CLI lifecycle orchestration (`init`, `run`, `init_and_run`) for active path.
- `state_service.py` is the mutation boundary for authoritative state.
- `runtime.py`/`game_service.py` define an alternate, older runtime orchestration path with blackboard-first persistence.
- `schemas.py` and `state.py` intentionally represent different domains (runtime process vs authoritative state), but overlap terms.

## 4. Core Runtime Flow
This section describes the runtime-engine path (`runtime.py` + `game_service.py`).

Sequence:
1. `GameService.play(request)` receives `GameRequest`.
2. Resolve `GameDefinition` and optional state context (`state_sources.py`).
3. Build prompt-backed roles (`build_prompt_roles`).
4. Construct `GameContract`.
5. `RuntimeEngine.run_game(contract, blue_role, red_role, referee_role)` executes rounds:
   - append `game_started` event,
   - invoke Blue via `RoleInvocationGuard` and append `blue_move_recorded`,
   - invoke Red and append `red_finding_recorded`,
   - invoke Referee and append `referee_decision_recorded`,
   - continue while `revise` and round budget remains.
6. Build `GameState` and append `game_completed`.
7. Build `GameResponse` (`build_game_response`).
8. Runtime integration decision is produced and appended once (`integrate_response` + `append_integration_decision_once`).

Prompt/render/model call flow in runtime path:
- prompt text assembled in `prompt_roles.py` and `prompt_assembly.py`,
- rendered strings passed to `ModelClient.generate`,
- outputs parsed into schema models through role factories/guard.

Runtime persistence:
- all runtime history is persisted as `Event` records in blackboard JSONL.

Artifacts interaction in runtime path:
- runtime path does not automatically mutate filesystem artifacts via `artifacts.py`.

## 5. Schema Documentation
### Runtime/replay schemas (`schemas.py`)
- `GameContract`: bounded game definition; validates non-empty IDs/goal and `max_rounds >= 1`.
- `Move`/`Finding`/`Decision`: role output units.
- `GameRound`/`GameState`/`GameResponse`: execution summaries with terminal semantics.
- `Event`: append-only envelope for blackboard persistence.
- `ProjectedState`: replay-derived read model (accepted/discrepancies/active games), not authoritative `State`.
- `schemas.IntegrationDecision`: runtime governance integration decision.

Why these exist:
- enforce typed runtime IO and enable deterministic replay/projection.

### Authoritative state schemas (`state.py`)
- `StateArtifact` base artifact identity (`id`, `kind`).
- `DocumentArtifact(StateArtifact)` with `sections: tuple[Section, ...]`.
- `State(northstar, artifacts)` with invariants:
  - unique IDs inside each artifact tuple,
  - no overlap between `northstar.artifacts` and `artifacts` IDs.
- `StateUpdateProposal` + `StateUpdateTarget`: explicit mutation request envelope.
- `DeltaState`/`DeltaDocumentState`: proposed game-level state delta (non-authoritative).
- `GameSpec`: atomic game contract for `CreateGame` output.
- `RedFinding`, `RefereeDecision`, `PlayGameRuntime` for play-stage runtime semantics.

Validation behavior:
- non-empty constraints via field validators,
- artifact coercion supports dict->typed artifact conversion,
- update operations validated in `apply_state_update`.

Relationships:
- `StateService` validates and persists `State` transitions.
- `run.py` uses `GameSpec`, deltas, and `StateUpdateProposal` conversion.

## 6. Blackboard/Event System
### Append-only philosophy
- `Blackboard.append` writes JSON line events; no in-place editing API exists.

### Event persistence
- file-backed JSONL at configured path.
- each event is validated on read using `Event.model_validate`.

### Event querying
- `query(event_type)`, `query_by_run(run_id)`, `query_completed_runs()`.
- helper append APIs exist for specific typed records.

### Event lifecycle
- runtime/game service emits game start/round/decision/completion,
- runtime integration appends integration decisions,
- projections consume and fold event history into replay/read models.

### Intended future role (observed in code comments/tests/docs context)
- blackboard is process/history memory and replay basis.
- authoritative project condition is not blackboard itself.

## 7. Artifact System
### Artifact lifecycle
`DocumentArtifactAdapter` filesystem structure per artifact ID:
```text
<root>/<artifact_id>/
  metadata.json
  current/main.md
  versions/vNNN/...
  changes/cNNN/
    proposed.md
    change.json
```

Operations:
- `create`: bootstrap directories and metadata,
- `snapshot`: copy `current` to next version directory,
- `propose_change`: write proposed content and unified diff metadata,
- `apply_change`: update `current/main.md` from proposal then snapshot,
- `rollback`: replace `current` from chosen version.

### Adapters and handler delegation
- `ArtifactHandler` dispatches by `artifact.type`.
- errors are explicit when no adapter is registered.

### Current assumptions/constraints
- only `document` adapter currently implemented.
- this lifecycle is distinct from authoritative `state.py` mutation lifecycle.

## 8. Runtime Engine
Runtime responsibilities (`runtime.py`):
- execute bounded rounds,
- validate role outputs via guard,
- append ordered events,
- compute terminal semantics,
- return consistent `GameState` for response construction.

Role invocation guard:
- `RoleInvocationGuard(max_attempts=2)` retries on:
  - schema validation failures (`ValidationError`),
  - semantic validation failures (`ValueError`).
- raises `RoleInvocationError` with explicit failure kind when exhausted.

Retry behavior:
- runtime round-loop continues on Referee `revise` until round budget is exhausted.

Current deterministic execution approach:
- deterministic roles + fake model clients are extensively test-covered.
- runtime semantics are deterministic given deterministic role outputs.

## 9. Roles and Prompt System
Deterministic roles:
- supplied in `example_roles.py` and tests; used for stable validation of orchestration.

Prompt-driven roles:
- built by `build_prompt_roles` combining:
  - structured prompt sections,
  - optional built-in agent profiles,
  - shared context,
  - model client.

`PromptRenderer`:
- strict non-empty template and rendered output checks.

`FakeModelClient`:
- records prompts and returns pre-seeded responses in order,
- fails when responses are exhausted.

`OllamaClient`:
- direct local HTTP generation client with strict response key checks.

Role execution flow:
- prompt role call -> model output text -> schema validation in guard -> semantic validation -> event persistence.

Current limitations:
- no tool-calling protocol,
- no dynamic team composition,
- no generalized multi-agent planning/execution scheduler.

## 10. Testing Strategy
Current philosophy:
- typed-boundary and orchestration invariants are first-class test targets.

Deterministic approach:
- `FakeModelClient` and deterministic fakes minimize nondeterminism,
- tests assert exact control-flow and error behavior.

Coverage themes:
- validation tests: schema constraints and rejection paths,
- runtime tests: event ordering, role retries, terminal semantics,
- blackboard tests: append/query/read behavior,
- artifact tests: filesystem lifecycle correctness,
- state tests: artifact invariants, update semantics, fingerprint checks,
- run tests: lifecycle commands, config precedence, adapter dispatch, play/integration/export flow.

Why deterministic tests matter here:
- architecture relies on strict contract boundaries,
- behavior needs to remain stable while refactoring parallel paths,
- deterministic seams isolate model non-determinism from orchestration correctness.

## 11. Architectural Invariants
Only code-enforced invariants are listed.

1. **Append-only blackboard writes**
- Implemented by `Blackboard.append` writing JSONL append operations.

2. **Explicit bounded loops**
- `max_rounds >= 1`, `max_attempts >= 1`, `max_iterations >= 1` enforced.

3. **Validated typed boundaries**
- Pydantic validators enforce non-empty and structural constraints for runtime/state artifacts.

4. **State mutation boundary is explicit**
- authoritative updates pass through `StateService.apply_update` and validation/fingerprint checks.

5. **State artifact identity invariants**
- uniqueness and disjointness between northstar and ordinary artifacts enforced in `State` model.

6. **Lifecycle preconditions for `baps-run`**
- `init` requires state file absent,
- `run` requires state file present,
- `init_and_run` requires state file absent.

## 12. Current Architectural Direction
### Implemented now
- adapter-dispatched `baps-run` lifecycle,
- LLM-backed `CreateGame` and `PlayGame` with strict JSON parsing,
- deterministic Red/Referee schema boundaries in play loop,
- state integration through `StateService` and export through adapter.

### Conceptual/future (inferred from module set and tests)
- stronger convergence between runtime event path and product run path,
- richer adversarial teams and critique policy,
- possible tool integration boundaries,
- stronger replay/projection use in product path.

Observation:
- current code still carries two substantial orchestration families; unification is conceptual, not complete.

## 13. Current Limitations
1. Ontology duplication:
- `integration.py::IntegrationDecision` and `schemas.py::IntegrationDecision` represent different layers with same term.

2. State/read-model split complexity:
- authoritative `state.py::State` and replay `schemas.py::ProjectedState` are both “state-like” and easy to conflate.

3. `run.py` concentration:
- config, prompt rendering, parsing, play orchestration, lifecycle control, and export all live in one module.

4. Runtime path vs product path divergence:
- runtime engine and game service are mature but not the canonical `baps-run` execution path.

5. Tooling/model orchestration gaps:
- no tool API, no generalized multi-agent scheduler, no streaming model orchestration.

6. Artifact lifecycle split:
- filesystem artifact lifecycle (`artifacts.py`) not unified with `StateService` mutation path.

## 14. Suggested Next Milestones
Additive milestones based on current code shape:

1. **Consolidate integration ontology boundaries**
- Keep both models temporarily, but add explicit adapters/mappings and one canonical naming/usage guide in code comments/tests.

2. **Isolate `baps-run` submodules without behavior change**
- split `run.py` into config, adapter registry, prompt/parsing helpers, lifecycle executor.

3. **Unify play-stage and runtime semantics tests**
- add cross-path contract tests proving equivalent Red/Referee decision semantics where applicable.

4. **Introduce explicit tool request boundary models**
- additive schema and no-op runtime support before real tool execution.

5. **Referee behavior hardening**
- extend referee input validation/consistency checks while preserving bounded play loop semantics.

## 15. Developer Workflow
Typical workflow in this repo:
1. Edit a focused module/test pair.
2. Run `uv run pytest`.
3. Keep changes additive and schema-first.
4. Preserve existing boundaries unless intentionally migrating with tests.

Test command:
```bash
uv run pytest
```

Current commit style observed through tests and module topology:
- many narrow, behavior-preserving increments,
- explicit regression tests for lifecycle and parsing boundaries,
- preference for deterministic fakes over integration-only tests.

Contributor expectations:
- do not bypass schema boundaries,
- prefer explicit adapters over hidden behavior branching,
- treat blackboard as history/process memory and `State` as authoritative condition.

## 16. Glossary
- **Game**: bounded adversarial evaluation unit with contract and round budget.
- **Role**: executable participant (`blue`, `red`, `referee`) producing typed outputs.
- **Move**: Blue output artifact in runtime schema (`Move`).
- **Finding**: Red critique artifact in runtime schema (`Finding`).
- **Decision**: Referee output in runtime schema (`Decision`) or play-stage decision (`RefereeDecision` in `state.py`).
- **Artifact**: filesystem lifecycle entity in `schemas.py`/`artifacts.py`.
- **StateArtifact**: authoritative identity artifact in `state.py`.
- **DocumentArtifact**: concrete `StateArtifact` with sectioned document content.
- **State**: authoritative project condition in `state.py`.
- **DeltaState / DeltaDocumentState**: proposed, non-authoritative play output representing candidate state change.
- **StateUpdateProposal**: explicit mutation request consumed by `StateService`.
- **Blackboard**: append-only event history (`blackboard.py`).
- **ProjectedState**: replay/read model derived from blackboard events (`schemas.py`, `projections.py`).
- **StateView / NorthStarView**: bounded textual projection object used as model input surface.
- **PromptRenderer**: deterministic string template renderer.
- **ModelClient**: abstract text generation client; implemented by `FakeModelClient` and `OllamaClient`.

## Observations / Ambiguities
1. The repository currently maintains parallel runtime and product/state execution paths. Both are tested and functional, but authority boundaries across both paths are not yet unified under one ontology.
2. The term `IntegrationDecision` is overloaded across runtime and state-centric layers; this is semantically valid in context but architecturally ambiguous for new contributors.
3. `StateView` is used as a generic bounded model-input projection type, but naming overlap with replay projection concepts (`ProjectedState`) remains a documented source of confusion.
