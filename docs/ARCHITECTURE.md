# Bounded Adversarial Production: Technical Architecture

## 1. Project Overview

### Purpose
`bounded-adversarial-production` (`baps`) is an experimental framework for running bounded adversarial "games" over a target. In current code, a game is a deterministic single-cycle interaction among three roles:

- Blue: proposes a move.
- Red: critiques/finds issues.
- Referee: issues a decision.

The system emphasizes explicit state models, strict validation, deterministic tests, and append-only runtime event logs.

### Current Project Philosophy

- Keep boundaries explicit and small.
- Validate all structured data with Pydantic models.
- Prefer deterministic behavior for reproducible testing.
- Keep runtime state auditable via append-only logs.
- Add capabilities incrementally without breaking existing APIs.

### Current Architectural Direction

Current architecture is layered:

1. **Schemas** define all contracts/state/events/artifacts.
2. **Execution primitives** (runtime engine + role invocation guard).
3. **Persistence boundaries** (blackboard, artifact adapter system).
4. **Prompt/model boundaries** (prompt renderer + model clients).
5. **Demo wiring** (CLI execution path).

### What "Bounded Adversarial Production" Means in Practice (Current)

In this codebase today:

- "Bounded" means fixed one-round execution (`round_number=1`, `max_rounds` exists in contract but runtime currently executes exactly one round).
- "Adversarial" means Blue/Red/Referee role structure and outcome evaluation.
- "Production" means explicit output artifacts/state/logging boundaries (event log + artifact adapter abstraction), not autonomous deployment behavior.

### Current Implementation vs Future Aspirations

Implemented:

- Deterministic game run path with run IDs.
- Role output validation + retry guard.
- File-backed append-only events.
- File-backed document artifact lifecycle.
- Prompt rendering and model abstraction boundaries.

Not implemented:

- Multi-round orchestration.
- Dynamic role spawning/tooling.
- Prompt-driven runtime role orchestration.
- Persistent run counter.
- Integrated production workflow automation.

---

## 2. Current System Capabilities

### Schemas (`src/baps/schemas.py`)

- **Purpose**: canonical data contracts.
- **Key models**: `GameContract`, `Move`, `Finding`, `Decision`, `GameState`, `Event`, artifact models.
- **Limitations**: timestamp fields are strings (no datetime coercion policy); semantic cross-field constraints are mostly enforced in runtime, not schemas.
- **Relationships**: used by all modules.

### Blackboard (`src/baps/blackboard.py`)

- **Purpose**: append-only JSONL event log.
- **Key API**: `append`, `read_all`, `query`.
- **Limitations**: no concurrency locks, no compaction, no schema migration, no partitioning.
- **Relationships**: runtime writes events, tests inspect event order/content.

### Artifacts (`src/baps/artifacts.py`)

- **Purpose**: adapter boundary + document filesystem implementation.
- **Key classes**: `ArtifactAdapter`, `ArtifactHandler`, `DocumentArtifactAdapter`.
- **Capabilities**: create/snapshot/propose_change/apply_change/rollback.
- **Limitations**: only `document` type implemented; no merge/conflict logic; version/change IDs derived from directory scan.
- **Relationships**: independent from runtime for now.

### Runtime (`src/baps/runtime.py`)

- **Purpose**: execute one bounded game run and emit events.
- **Key class**: `RuntimeEngine`.
- **Capabilities**: one run -> one round, role calls via guard, run_id generation (`run-0001`, ... per engine instance).
- **Limitations**: single-round only; no artifact integration; run counter is in-memory only.
- **Relationships**: depends on `Blackboard`, `RoleInvocationGuard`, schema models.

### Roles (`src/baps/roles.py`, `src/baps/example_roles.py`)

- **Purpose**: invoke roles safely; provide example role implementations.
- **Key classes/functions**:
  - `RoleInvocationGuard`, `RoleInvocationError`
  - deterministic roles: `blue_role`, `red_role`, `referee_role`
  - prompt-driven factory: `make_prompt_blue_role`
- **Limitations**: prompt-driven path exists only for Blue factory; runtime demo still uses deterministic hardcoded roles.

### Prompt Rendering (`src/baps/prompts.py`)

- **Purpose**: minimal template rendering boundary.
- **Key API**: `PromptRenderer.render`, `render_prompt`.
- **Limitations**: no template engine beyond `str.format`; no file templates; no schema for prompt context.

### Model Abstraction (`src/baps/models.py`)

- **Purpose**: model provider boundary.
- **Key classes**: `ModelClient`, `FakeModelClient`, `OllamaClient`.
- **Capabilities**: deterministic fake responses; minimal Ollama `/api/generate` call.
- **Limitations**: no streaming/chats/tool calls/retries/backoff; Ollama integration not wired to runtime.

### Deterministic Testing

- Uses `pytest` with direct object assertions.
- Fake roles and `FakeModelClient` keep tests deterministic and local.
- Network calls are mocked for Ollama tests.

### Demo Execution (`src/baps/demo.py`)

- `uv run baps-demo` runs one hardcoded contract.
- Writes five events to `blackboard/events.jsonl`.
- Prints `game_id`, `run_id`, `final_decision`, `blackboard_path`.

---

## 3. Repository Structure

```text
src/baps/
  __init__.py
  artifacts.py
  blackboard.py
  demo.py
  example_roles.py
  models.py
  prompts.py
  roles.py
  runtime.py
  schemas.py
tests/
  test_artifacts.py
  test_blackboard.py
  test_demo.py
  test_example_roles.py
  test_models.py
  test_prompts.py
  test_roles.py
  test_runtime.py
  test_schemas.py
docs/
  ARCHITECTURE.md
```

### Module Map

#### `schemas.py`
- **Purpose**: shared contracts and validation rules.
- **Dependencies**: `pydantic`.
- **Boundary**: no I/O, no runtime orchestration.

#### `blackboard.py`
- **Purpose**: JSONL event persistence.
- **Dependencies**: `json`, `pathlib`, `Event`.
- **Boundary**: append/read/query only.

#### `artifacts.py`
- **Purpose**: artifact adapter interface + concrete document adapter + handler delegation.
- **Dependencies**: `json`, `shutil`, `difflib`, `pathlib`, artifact schemas.
- **Boundary**: filesystem artifact lifecycle, separate from runtime.

#### `roles.py`
- **Purpose**: guarded role invocation with retries.
- **Dependencies**: `pydantic.ValidationError`, `BaseModel`.
- **Boundary**: validation/retry wrapper only.

#### `runtime.py`
- **Purpose**: bounded game execution orchestration.
- **Dependencies**: `Blackboard`, `RoleInvocationGuard`, game schemas.
- **Boundary**: no prompt rendering, no model client usage, no artifacts.

#### `example_roles.py`
- **Purpose**: deterministic role examples + additive prompt-driven Blue-role factory.
- **Dependencies**: schemas; optional prompt/model boundaries.
- **Boundary**: no side effects except optional model client call in prompt-driven factory.

#### `prompts.py`
- **Purpose**: `str.format` rendering boundary.
- **Dependencies**: stdlib only.

#### `models.py`
- **Purpose**: model client abstraction + fake + Ollama.
- **Dependencies**: stdlib `urllib`/`json`.
- **Boundary**: no runtime integration currently.

#### `demo.py`
- **Purpose**: executable wiring for a single deterministic run.
- **Dependencies**: runtime + blackboard + deterministic roles + schemas.

---

## 4. Core Runtime Flow

Current runtime flow in `RuntimeEngine.run_game`:

1. Increment in-memory counter, compute `run_id` (`run-0001`, `run-0002`, ...).
2. Append `game_started` event:
   - ID: `{game_id}:{run_id}:game_started`
   - Payload: `{game_id, run_id}`
3. Invoke Blue role through `RoleInvocationGuard.invoke(...)`:
   - args: `(contract,)`
   - model: `Move`
   - semantic checks: `move.game_id == contract.id`, `move.role == "blue"`
4. Append `blue_move_recorded` event with serialized `move`.
5. Invoke Red role via guard:
   - args: `(contract, blue_move)`
   - model: `Finding`
   - semantic check: `finding.game_id == contract.id`
6. Append `red_finding_recorded` with serialized `finding`.
7. Invoke Referee role via guard:
   - args: `(contract, blue_move, red_finding)`
   - model: `Decision`
   - semantic check: `decision.game_id == contract.id`
8. Append `referee_decision_recorded` with serialized `decision`.
9. Build `GameRound(round_number=1, ...)`.
10. Build `GameState(game_id, run_id, current_round=1, rounds=[...], final_decision=...)`.
11. Append `game_completed` with serialized `state`.
12. Return `GameState`.

### Prompt Rendering and Model Calls in Runtime

Current runtime does **not** render prompts or call model clients directly.

- Prompt/model boundaries exist for future role composition.
- Runtime accepts injected callables and treats them as opaque role providers.

### Runtime State Persistence

- Persisted state today is the blackboard event log (`blackboard/events.jsonl` in demo).
- `GameState` object is returned in memory and embedded in `game_completed` payload.
- No dedicated game-state storage backend exists yet.

### Artifacts and Runtime Interaction

- No direct runtime-artifact integration currently.
- Artifact system is implemented in parallel as a separate boundary.

---

## 5. Schema Documentation

All models are in `src/baps/schemas.py`.

### Target
- `kind: str` (non-empty)
- `ref: str | None = None`
- **Why**: identifies domain/object under analysis.

### GameContract
- `id, subject, goal: str` (non-empty)
- `target: Target`
- `active_roles: list[str]` (must be non-empty)
- `max_rounds: int = 3` (>= 1)
- `scope_allowed, scope_forbidden: list[str]` (isolated defaults)
- **Why**: execution input contract.

### Move
- `game_id, role, summary: str` (non-empty)
- `payload: dict = {}`
- **Why**: Blue output artifact.

### Finding
- `game_id, severity, confidence, claim: str` (non-empty)
- `evidence: list[str] = []`
- `block_integration: bool = False`
- **Why**: Red output artifact.

### Decision
- `game_id, decision, rationale: str` (non-empty)
- **Why**: Referee output.

### GameRecord
- `game_id: str` (non-empty)
- `contract: GameContract`
- `status: str` in `{pending, running, completed, failed}`
- `created_at, updated_at: str` (non-empty)
- `metadata: dict = {}`
- **Why**: lifecycle record schema (not yet persisted by runtime).

### GameRound
- `round_number: int` (>=1)
- `moves: list[Move] = []`
- `findings: list[Finding] = []`
- `decision: Decision | None = None`
- **Why**: per-round aggregation container.

### GameState
- `game_id: str` (non-empty)
- `run_id: str` (non-empty)
- `current_round: int = 1` (>=1)
- `rounds: list[GameRound] = []`
- `final_decision: Decision | None = None`
- **Why**: runtime return object and completed-state event payload.

### Artifact
- `id, type: str` (non-empty)
- `current_version: str | None = None`
- `metadata: dict = {}`
- **Why**: adapter input/identity.

### ArtifactVersion
- `artifact_id, version_id, path: str` (non-empty)
- `metadata: dict = {}`
- **Why**: immutable snapshot descriptor.

### ArtifactChange
- `artifact_id, change_id, base_version, description: str` (non-empty)
- `diff: str | None = None`
- `metadata: dict = {}`
- **Why**: proposed change descriptor.

### ArtifactAdapterResult
- `artifact_id: str` (non-empty)
- `version_id: str | None`
- `change_id: str | None`
- `message: str` (non-empty)
- **Why**: generic adapter response envelope.

### Event
- `id, type: str` (non-empty)
- `payload: dict = {}`
- **Why**: append-only runtime log item.

---

## 6. Blackboard/Event System

### Append-Only Philosophy

`Blackboard.append` opens file in append mode (`"a"`), writing one JSON object per line. Existing lines are not modified.

### Event Persistence

- Storage format: JSONL.
- Serialization: `event.model_dump(mode="json")`.
- Parent directory auto-created.

Example line:

```json
{"id":"demo-game-001:run-0001:game_started","type":"game_started","payload":{"game_id":"demo-game-001","run_id":"run-0001"}}
```

### Reading and Querying

- `read_all()`:
  - returns `[]` if file missing.
  - parses each line with `json.loads`.
  - validates each object as `Event`.
- `query(event_type)`:
  - rejects blank types.
  - filters `read_all()` by exact `event.type`.

### Event Lifecycle (Current)

Runtime emits exactly five events per run, in order:

1. `game_started`
2. `blue_move_recorded`
3. `red_finding_recorded`
4. `referee_decision_recorded`
5. `game_completed`

### Intended Future Role (Observed Direction)

Based on existing boundaries, blackboard is positioned to be the execution trace/audit ledger for future richer orchestration, but currently remains a simple per-file event list.

---

## 7. Artifact System

### Lifecycle

Implemented document lifecycle:

1. `create`
2. `snapshot`
3. `propose_change`
4. `apply_change`
5. `rollback`

### Adapter and Handler

- `ArtifactAdapter`: base class with `NotImplementedError` methods.
- `ArtifactHandler`: dispatches by `artifact.type`.
  - raises `ValueError` if no adapter registered.

### Document Filesystem Layout

For artifact `doc-1` under root:

```text
<root>/doc-1/
  current/
    main.md
  versions/
    v001/
    v002/
  changes/
    c001/
      proposed.md
      change.json
  metadata.json
```

### Snapshot and Versioning

- Snapshot copies `current/` -> `versions/vNNN` via `shutil.copytree`.
- Version ID uses directory scan count (`v001`, `v002`, ...).

### Change Proposal

- `propose_change` reads `current/main.md`, computes unified diff against proposed content, stores `ArtifactChange` + proposed file.
- Base version is `artifact.current_version` or `"unversioned"` when missing.

### Apply and Rollback

- `apply_change`: copy `changes/<id>/proposed.md` into `current/main.md`, then snapshot.
- `rollback`: replace `current/` with selected `versions/<version_id>` directory.

### Current Assumptions/Constraints

- Single-node local filesystem.
- No transactional guarantees.
- No merge/conflict workflow.
- IDs depend on current directory contents.

---

## 8. Runtime Engine

### Responsibilities

- Generate per-run ID.
- Invoke three injected roles in sequence.
- Enforce semantic constraints on role outputs.
- Emit canonical event sequence.
- Return `GameState`.

### RoleInvocationGuard Integration

Runtime delegates role execution to `RoleInvocationGuard`, which:

- validates raw role output with Pydantic model.
- executes optional semantic validator.
- retries on `ValidationError` or `ValueError` up to `max_attempts`.
- raises `RoleInvocationError` on exhaustion.

### Retry Behavior

Default max attempts is `2` (unless custom guard injected).
Runtime tests confirm:

- first-failure then success path works.
- persistent failure raises `RoleInvocationError`.

### Execution Model

- Single threaded.
- Single round.
- Deterministic given deterministic role callables and same runtime instance state.

### Deterministic Execution Approach

- Example roles are deterministic.
- Run IDs are deterministic **within a runtime instance**: `run-0001`, `run-0002`, ...
- New runtime instances restart counter at `run-0001`.

---

## 9. Roles and Prompt System

### Deterministic Example Roles

`example_roles.py` provides:

- `blue_role(contract) -> Move`
- `red_role(contract, blue_move) -> Finding`
- `referee_role(contract, blue_move, red_finding) -> Decision`

These are hardcoded and deterministic.

### Prompt-Driven Role Support (Additive)

`make_prompt_blue_role(model_client, template, extra_context=None)` returns a Blue role callable that:

1. Builds context from `GameContract` (`game_id`, `subject`, `goal`, `target_kind`, `target_ref`) plus optional overrides.
2. Renders prompt via `PromptRenderer`.
3. Calls `model_client.generate(prompt)`.
4. Uses model output as `Move.summary`.

### PromptRenderer

- Uses Python `str.format`.
- Raises:
  - `ValueError` for empty template.
  - `KeyError` for missing variables.
  - `ValueError` for whitespace-only rendered output.

### Model Clients

- `FakeModelClient`: deterministic response queue; records prompts.
- `OllamaClient`: HTTP POST to `/api/generate`, returns `"response"` field.

### Current Limitations

- Runtime does not yet use prompt-driven role factory.
- No tool invocation boundary in role outputs.
- No multi-agent autonomous control loop.
- No prompt libraries/files/versioning.

---

## 10. Testing Strategy

### Philosophy

- Validate behavior through deterministic, isolated unit tests.
- Keep external dependencies mocked/faked.
- Assert explicit invariants (ordering, validation, IDs, filesystem effects).

### Deterministic Testing Techniques

- `FakeModelClient` for predictable model outputs.
- Function-level fake roles in runtime tests.
- `tmp_path` for isolated filesystem tests.
- Mocked `urllib.request.urlopen` for Ollama client tests.

### Coverage Areas

- **Schemas**: construction, invalid inputs, mutable default isolation.
- **Blackboard**: append/read/query, invalid JSON handling, ordering.
- **Artifacts**: lifecycle paths + handler dispatch + failure cases.
- **Roles guard**: retry semantics and error propagation.
- **Runtime**: event order, run IDs, semantic validation failures.
- **Prompts**: rendering and failure modes.
- **Demo**: end-to-end one-run verification.
- **Models**: fake + Ollama request/response/error handling.

### Why Deterministic Tests Matter Here

Architecture intentionally isolates orchestration boundaries before introducing live model/agent complexity. Deterministic tests preserve confidence while interfaces expand incrementally.

---

## 11. Architectural Invariants (Enforced in Code)

1. **Schema validation is mandatory at boundaries**  
   Role outputs and persisted events are validated against Pydantic models.

2. **Blackboard writes are append-only**  
   `Blackboard.append` never truncates existing log files.

3. **Runtime emits fixed ordered event sequence per run**  
   Five event types in fixed order are tested.

4. **Runtime event identity includes game and run**  
   Event IDs are `{game_id}:{run_id}:{event_type}`.

5. **Role invocation failures are bounded by retry policy**  
   Guard retries up to `max_attempts`; then raises `RoleInvocationError`.

6. **Artifact handler delegates strictly by type**  
   Unknown type fails with `ValueError`.

7. **Document artifact operations are filesystem-based and explicit**  
   Create/snapshot/change/apply/rollback semantics are tested.

8. **Mutable default fields are isolated**  
   Models with list/dict defaults use `default_factory` and are tested for non-sharing.

---

## 12. Current Architectural Direction

### Implemented Direction

- Structured adversarial game primitives (contract/move/finding/decision/state).
- Guarded role invocation with retry semantics.
- Auditable event logging.
- Adapter boundary for artifacts.
- Prompt/model boundaries for future role evolution.

### Conceptual/Future Direction (Inferred from Existing Interfaces)

- Move from deterministic roles to prompt/model-driven roles.
- Expand bounded single-round runtime to richer game loops.
- Integrate artifact outputs with runtime decisions.
- Possibly add richer tool or pipeline boundaries.

This is inferred from existing abstractions (`ModelClient`, `PromptRenderer`, artifact adapters), not from implemented orchestration.

---

## 13. Current Limitations

- Runtime executes exactly one round; `max_rounds` is not enforced by loop logic.
- Run IDs are per-runtime-instance, in-memory only (no persistence, no cross-process uniqueness).
- No concurrency controls for blackboard or artifact filesystem operations.
- No tool calling interface for roles.
- No referee policy logic beyond injected callable output.
- Prompt-driven role path currently exists only as a Blue-role factory helper.
- No runtime linkage to artifact lifecycle.
- `GameRecord` schema exists but has no storage/service implementation.
- Ollama client exists but is not wired into runtime/demo flow.

---

## 14. Suggested Next Milestones (Additive, Architecture-Compatible)

1. **Introduce optional prompt-driven role wiring in runtime/demo**
   - Keep callable interface unchanged.
   - Add factory wiring path via `make_prompt_blue_role` and model clients.

2. **Add multi-round runtime loop bounded by `GameContract.max_rounds`**
   - Preserve current round schema.
   - Append round-indexed events.

3. **Define explicit referee decision policy contract**
   - Keep `Decision` schema.
   - Add helper for standardized acceptance/block mapping.

4. **Introduce tool request boundary schema (no execution engine redesign)**
   - Add additive schemas and no-op handling paths first.

5. **Connect runtime outcomes to artifact operations**
   - E.g., optional post-decision artifact snapshot/apply path via `ArtifactHandler`.

6. **Add persistent run registry**
   - Keep existing `run_id` format if desired.
   - Persist counters or generate globally unique IDs without breaking event format.

---

## 15. Developer Workflow

### Local Setup and Execution

```bash
uv sync
uv run pytest
uv run baps-demo
```

### Typical Change Pattern (Observed)

- Add/update schema model.
- Add focused tests first/alongside implementation.
- Keep module boundaries narrow.
- Avoid cross-cutting redesign.

### Additive Development Philosophy

Current history and structure favor incremental additions:

- New abstractions are introduced beside existing behavior.
- Existing public APIs are preserved while new helper paths are added.
- Deterministic tests protect backward compatibility.

### Contributor/Agent Expectations

- Maintain strict validation at boundaries.
- Prefer explicit errors over silent coercion.
- Keep runtime side effects observable via blackboard events.
- Add tests for both success and failure paths.

---

## 16. Glossary

- **Game**: one execution of Blue/Red/Referee flow for a `GameContract`, identified by `game_id` + `run_id`.
- **Run**: a specific execution instance (`run-0001`, etc.) within a runtime engine instance.
- **Role**: callable producing structured output (`Move`, `Finding`, `Decision`) for a stage.
- **Move**: Blue role output describing proposed action summary/payload.
- **Finding**: Red role output describing risk/claim/evidence.
- **Decision**: Referee role output with final accept/integrate/etc rationale.
- **GameContract**: input contract defining target, objective, roles, and bounds.
- **GameRound**: per-round aggregation of moves/findings/decision.
- **GameState**: returned state for a run, including rounds and final decision.
- **GameRecord**: schema for game lifecycle metadata/status (not yet runtime-persisted).
- **Blackboard**: append-only JSONL event log backend.
- **Event**: single runtime log record with `id`, `type`, `payload`.
- **Artifact**: typed object managed by adapters (currently document artifacts).
- **Snapshot**: immutable-ish filesystem copy of artifact `current/` content under `versions/`.
- **Change**: proposed content update with diff + metadata stored under `changes/`.
- **ArtifactHandler**: type-based dispatcher to concrete artifact adapters.
- **RoleInvocationGuard**: retrying validator wrapper for role callables.
- **PromptRenderer**: thin `str.format` template renderer with non-empty output enforcement.
- **ModelClient**: abstraction for prompt->text generation.
- **FakeModelClient**: deterministic queue-backed `ModelClient` for tests.
- **OllamaClient**: stdlib HTTP implementation of `/api/generate` model client.

---

## Observations and Ambiguities

1. **Run ID scope**: `run_id` uniqueness is guaranteed only within a `RuntimeEngine` instance, not globally.
2. **`max_rounds` semantics**: present in schema but not enforced in runtime loop yet.
3. **`GameRecord` lifecycle**: schema exists without an implemented persistence/update service.
4. **Artifact/runtime coupling**: both systems are implemented but currently independent.
5. **Event schema openness**: `Event.payload` is untyped `dict`; event-type-specific payload contracts are implicit in runtime code/tests.
