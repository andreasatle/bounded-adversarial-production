# Bounded Adversarial Production (`baps`) Architecture

## 1. Project Overview

### Purpose of the framework
`bounded-adversarial-production` is a Python framework for running bounded Blue/Red/Referee game loops and recording execution traces to an append-only JSONL blackboard.

Current end-to-end path:
1. Build a `GameRequest`.
2. Resolve a `GameDefinition` (built-in or file-backed).
3. Build prompt-driven roles.
4. Execute bounded runtime rounds.
5. Derive a `GameResponse`.
6. Append deterministic integration-decision events.

### Current project philosophy in code
The codebase currently emphasizes:
- Pydantic boundary validation for contracts and records.
- Explicit runtime boundaries (`GameService` orchestration vs `RuntimeEngine` execution).
- Append-only event persistence (`Blackboard.append`).
- Deterministic behavior in tests (fake models, local role callables, no network dependencies in unit tests).
- Additive layering (runtime + integration + projection + planner/autonomous modules).

### Current architectural direction
The architecture is currently split into:
- Execution path: `game_service.py` + `runtime.py` + prompt role/model adapters.
- Governance path: `integrator.py` + blackboard integration-decision events.
- Read model path: `projections.py` replaying events into `ProjectedState`.
- Next-step planning path: `planner.py` + `autonomous.py`.

### Meaning of “bounded adversarial production” in practice
In current implementation:
- Bounded: runtime loop is capped by `GameContract.max_rounds`; continuing only when decision is `revise` and budget remains.
- Adversarial: Blue produces candidate, Red critiques, Referee decides.
- Production-oriented: emits structured events, projects current state from replay, and records explicit integration decisions.

### Implemented vs future aspiration distinction
Implemented now:
- Single sequential role chain per round.
- Deterministic integration policy.
- Event replay projection for accepted items/discrepancies.
- Optional state-source context injection.
- Prompt-driven role wrappers and Ollama model client.

Conceptual/future indicated by code shape but not fully implemented:
- Richer multi-role/multi-move adversarial orchestration.
- Tool-calling boundary and action execution.
- Automated artifact integration loop from accepted outcomes.
- Strong policy/authority checks over planner outputs.

## 2. Current System Capabilities

### Schemas (`src/baps/schemas.py`)
Purpose:
- Defines all runtime contracts, event envelopes, integration records, projected-state records, planner metadata, and artifact records.

Important models:
- Runtime contracts: `GameRequest`, `GameContract`, `Target`.
- Role outputs: `Move`, `Finding`, `Decision`.
- Runtime state/response: `GameRound`, `GameState`, `RoundSummary`, `GameResponse`, `PlannedExecutionResult`.
- Governance/projection: `IntegrationDecision`, `ProjectedState`, accepted/discrepancy lifecycle models.
- Artifacts: `Artifact`, `ArtifactVersion`, `ArtifactChange`, `ArtifactProposalRecord`.
- Event envelope: `Event`.

Limitations:
- Many cross-model semantic policies are enforced outside schemas (runtime/integrator/projection logic).
- `GameRecord` exists but is not written by runtime/game service.

Relationships:
- Imported across runtime, blackboard, integrator, projections, planner, game service, artifacts.

### Blackboard (`src/baps/blackboard.py`)
Purpose:
- Append/read/query JSONL event log.

Important functions:
- `append`, `read_all`, `query`, `query_by_run`, `query_completed_runs`.
- Typed append helpers for integration/discrepancy/accepted-state/artifact-proposal records.

Limitations:
- No locking, no transactional writes, no index.
- Query operations replay entire file each call.

Relationships:
- Runtime appends game lifecycle events.
- Integrator/projection lifecycle helpers append governance events.
- Projection functions consume `read_all()` results.

### Artifacts (`src/baps/artifacts.py`)
Purpose:
- Filesystem artifact lifecycle abstraction and document adapter.

Important classes/functions:
- `ArtifactAdapter` protocol-style base class.
- `ArtifactHandler` adapter delegator by `artifact.type`.
- `DocumentArtifactAdapter`: `create`, `snapshot`, `propose_change`, `apply_change`, `rollback`.

Limitations:
- Only `document` artifact type implemented.
- No integration gating in `apply_change` (can apply locally without integration decision).
- No merge/conflict model.

Relationships:
- Uses artifact schemas; currently not coupled to runtime event flow by default.

### Runtime (`src/baps/runtime.py`)
Purpose:
- Executes bounded rounds and appends runtime events.

Important functions/classes:
- `RuntimeEngine.run_game`.
- `generate_run_id`.
- `build_game_response`.
- `_derive_terminal_semantics`.
- `_supports_revision_context` (inspection-based optional second arg to blue role).

Limitations:
- Exactly one blue move and one red finding per round.
- No role scheduling abstraction.
- No tool invocation subsystem.

Relationships:
- Uses `RoleInvocationGuard` for validation/retries.
- Uses `Blackboard` for durable event stream.
- `GameService` wraps runtime and post-processing.

### Roles (`src/baps/roles.py`, `src/baps/example_roles.py`, `src/baps/prompt_roles.py`)
Purpose:
- Role invocation safety and deterministic/prompt-driven role implementations.

Important components:
- `RoleInvocationGuard` with bounded retries and failure classification.
- Deterministic example roles: `blue_role`, `red_role`, `referee_role`.
- Prompt role factories: `make_prompt_blue_role`, `make_prompt_red_role`, `make_prompt_referee_role`.
- `build_prompt_roles` with optional `AgentProfile` injection.

Limitations:
- No role sandbox/tool API.
- Referee decision is currently derived deterministically from finding fields in prompt role implementation.

Relationships:
- Runtime treats roles as callables; prompt/model concerns are encapsulated in factories.

### Prompt rendering and assembly (`src/baps/prompts.py`, `src/baps/prompt_assembly.py`)
Purpose:
- Prompt section schema + deterministic assembly + `str.format` rendering.

Important components:
- `PromptSection`, `PromptSpec`, `assemble_prompt`.
- `PromptRenderer.render`, `render_prompt`.

Limitations:
- Uses Python format templates; missing keys raise `KeyError`.
- No automatic escaping/templating policy layer.

Relationships:
- Used by prompt role factories and game-type prompt definition path.

### Model abstraction (`src/baps/models.py`)
Purpose:
- Model-client boundary for runtime/planner prompt generation.

Important classes:
- `ModelClient` interface.
- `FakeModelClient` (deterministic queue-based responses + prompt capture).
- `OllamaClient` (`POST /api/generate`, non-streaming).

Limitations:
- No chat/tool schema abstraction.
- No backoff/retry strategy in client.

Relationships:
- Used by prompt roles, game service wiring, and `LLMPlanner`.

### Ollama integration
Current behavior:
- `OllamaClient` validates non-empty model/base URL and prompt.
- Sends JSON `{model, prompt, stream: false}`.
- Raises `RuntimeError` on HTTP/URL errors or missing `response` field.
- Used by CLI flows and Ollama demo modules.

### Deterministic testing
Current behavior:
- Extensive `pytest` suite validates schemas, runtime semantics, event replay, planners, adapters, prompts, and CLIs.
- Determinism comes from fake model responses and deterministic role outputs.

### Demo game execution
Current demo entry points:
- `demo.py`: deterministic one-round cycle.
- `adversarial_demo.py`: deterministic rejection example.
- `ollama_adversarial_demo.py`: prompt roles + Ollama.
- `play_game.py`: full CLI orchestration with run specs and state sources.

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
  state_sources.py
examples/
  game_definitions/documentation_refinement.json
  runs/fake_goal_audit.yaml
  state_manifests/baps_project_state.json
tests/
  test_*.py
```

Important module responsibilities and boundaries:
- `schemas.py`: canonical contracts and value constraints only.
- `runtime.py`: bounded round loop and runtime event emission.
- `roles.py`: invocation retries/classified errors.
- `example_roles.py`: deterministic and prompt-driven callable implementations.
- `prompt_assembly.py` + `prompts.py`: section-level prompt assembly/rendering.
- `prompt_roles.py`: role-construction orchestration around prompt sections + profiles.
- `game_types.py`: built-in and file-loaded game definitions.
- `game_service.py`: request orchestration; state-source context resolution; integration append.
- `integrator.py`: local acceptance-to-integration policy translation.
- `blackboard.py`: append-only event storage and query.
- `projections.py`: replay-driven projected state and query helpers.
- `planner.py`: deterministic and LLM planner implementations.
- `autonomous.py`: bounded repeated plan/play loop.
- `state_sources.py`: manifest schemas and source adapters.
- `run_specs.py`: YAML run spec schema/loader.
- `play_game.py`: CLI glue for run spec, context loading, and game execution.
- `artifacts.py`: filesystem document artifact lifecycle and adapter dispatch.

## 4. Core Runtime Flow

### Sequence: game execution (`RuntimeEngine.run_game`)
1. Generate `run_id` with UTC timestamp + UUID suffix.
2. Append `game_started` event.
3. For each round (1..`max_rounds`):
4. Resolve blue-role invocation args.
5. Invoke blue role through `RoleInvocationGuard` with schema + semantic validation.
6. Append `blue_move_recorded` event.
7. Invoke red role through guard; append `red_finding_recorded`.
8. Invoke referee role through guard; append `referee_decision_recorded`.
9. Materialize `GameRound` and update `previous_context` for possible blue revision.
10. Exit on `accept` or `reject`.
11. Continue only when decision is `revise` and round budget remains.
12. Build `GameState`; derive terminal semantics; append `game_completed` event.

### Sequence: role invocation guard
1. Call role callable.
2. Validate output against target Pydantic model.
3. Apply optional semantic validator.
4. Retry up to `max_attempts` on `ValidationError` or `ValueError`.
5. Raise `RoleInvocationError` with failure kind when exhausted.

### Sequence: prompt rendering + model call for prompt roles
1. Build template using assembled sections.
2. Build render context (contract fields + additional context).
3. `PromptRenderer.render` via `str.format`.
4. Call `ModelClient.generate`.
5. Parse role-specific output (`JSON object` path or text fallback).
6. Emit schema model (`Move`/`Finding`/`Decision`).

### Runtime state persistence and blackboard recording
Persistence in current code means event persistence, not DB state storage.
- State object is returned in-memory.
- Events are persisted line-by-line to blackboard JSONL.
- `game_completed` payload embeds serialized `GameState`.

### Artifact interaction with runtime
Current runtime flow does not invoke `ArtifactHandler` or artifact adapters.
Artifact lifecycle is separate and explicitly callable from artifact module APIs.

### Example runtime event IDs
```text
game-1:run-20260515-120000-deadbeef:r0001:game_started
game-1:run-20260515-120000-deadbeef:r0001:blue_move_recorded
game-1:run-20260515-120000-deadbeef:r0001:red_finding_recorded
game-1:run-20260515-120000-deadbeef:r0001:referee_decision_recorded
game-1:run-20260515-120000-deadbeef:game_completed
```

## 5. Schema Documentation

### Core request/contract schemas
- `Target(kind, ref=None)`.
- `GameRequest(game_type, subject, goal, target_kind, target_ref="", state_source_ids=[], planner_grounding=None)`.
- `GameContract(id, subject, goal, target, active_roles, max_rounds=3, scope_allowed=[], scope_forbidden=[])`.

Why they exist:
- `GameRequest`: external orchestration/API request object.
- `GameContract`: runtime-local executable contract.
- `Target`: normalized target reference.

Validation/invariants:
- Required strings must be non-empty (trim-aware).
- `active_roles` non-empty.
- `max_rounds >= 1`.
- `state_source_ids` entries non-empty.

### Runtime output/state schemas
- `Move(game_id, role, summary, payload={})`.
- `Finding(game_id, severity, confidence, claim, evidence=[], payload={}, block_integration=False)`.
- `Decision(game_id, decision, rationale)`.
- `GameRound(round_number>=1, moves, findings, decision)`.
- `GameState(game_id, run_id, current_round>=1, rounds, final_decision)`.
- `RoundSummary(round_number, blue_summary, red_claim, referee_decision, referee_rationale)`.
- `GameResponse(...)` with terminal semantics fields.

Why they exist:
- Capture role-by-role outputs and create a deterministic, inspectable terminal response object.

Validation behavior:
- String non-empty validators on key fields.
- `TerminalOutcome` and `IntegrationRecommendation` constrained by `Literal` types.

### Projection/governance schemas
- `IntegrationDecision`, `ProjectedState`, `AcceptedAccomplishment`, `AcceptedArchitectureItem`, `AcceptedCapability`, `UnresolvedDiscrepancy`, `ActiveGameSummary`.
- Lifecycle: `DiscrepancyResolution`, `DiscrepancySupersession`, `AcceptedStateSupersession`, `AcceptedStateRevocation`.

Why they exist:
- Represent durable integration and replayed project state that is not identical to raw runtime traces.

### Artifact schemas
- `Artifact`, `ArtifactVersion`, `ArtifactChange`, `ArtifactAdapterResult`, `ArtifactProposalRecord`.

Why they exist:
- Provide normalized records for local artifact lifecycle and blackboard proposal tracking.

### Event schema
- `Event(id, type, payload={})`.

Why it exists:
- Uniform append-only envelope for runtime, integration, discrepancy, and artifact proposal events.

## 6. Blackboard/Event System

### Append-only philosophy
`Blackboard.append` only appends newline-delimited JSON events; no in-place update/delete APIs are provided.

### Event persistence
- Path parent is created as needed.
- Each event is serialized via `event.model_dump(mode="json")`.
- Stored format: one JSON object per line.

### Event querying
- `read_all()` parses all events as `Event` models.
- `query(type)` filters by `event.type`.
- `query_by_run(run_id)` filters by `event.payload.run_id`.
- `query_completed_runs()` maps to `query("game_completed")`.

### Event lifecycle in current architecture
1. Runtime appends gameplay events.
2. Game service appends integration decision event.
3. Optional lifecycle events (resolution/supersession/revocation/artifact proposal) can be appended via helper methods.
4. Projections replay entire history to derive current state.

### Intended future role (inferred from modules)
Blackboard is treated as the durable source for:
- State projection.
- Integration review queues.
- Discrepancy lifecycle transitions.
- Artifact proposal tracking.

Observation:
- There is no explicit event versioning/migration layer yet; projection code is tolerant of malformed payloads by skipping invalid records.

## 7. Artifact System

### Implemented artifact lifecycle
For `DocumentArtifactAdapter`:
1. `create(artifact)` creates directory structure and metadata.
2. `snapshot(artifact)` copies `current/` to next `versions/vNNN`.
3. `propose_change(...)` writes `changes/cNNN/proposed.md` + `change.json` + unified diff.
4. `apply_change(...)` copies proposed content to `current/main.md` and snapshots.
5. `rollback(...)` replaces `current/` from selected version.

### Adapter/handler delegation
`ArtifactHandler` selects adapter by `artifact.type` and delegates all operations (`create`, `snapshot`, `propose_change`, `apply_change`, `rollback`).

### Filesystem structure
```text
<root>/<artifact_id>/
  metadata.json
  current/
    main.md
  versions/
    v001/
    v002/
  changes/
    c001/
      proposed.md
      change.json
```

### Metadata and assumptions
- Artifact metadata is persisted as JSON from `Artifact` model.
- Change `base_version` falls back to `"unversioned"` when `artifact.current_version` is `None`.
- Version/change IDs are sequential based on existing folder count.

Constraints:
- Adapter enforces `artifact.type == "document"`.
- `propose_change` requires existing `current/main.md`.
- `apply_change` only checks proposed file existence; does not validate blackboard/integration state.

## 8. Runtime Engine

### Responsibilities
- Execute round loop.
- Validate role outputs with guard + semantic checks.
- Emit runtime events.
- Materialize `GameState`.
- Provide terminal semantics via `build_game_response` (called by game service).

### Role invocation guard behavior
- Default `max_attempts=2`.
- Retries on schema validation failures and semantic `ValueError`s.
- Raises `RoleInvocationError` with `failure_kind` when exhausted.

### Retry behavior
- Guard retries per role invocation independently.
- Runtime itself does not retry whole rounds.

### Game execution model
- Sequential: Blue -> Red -> Referee.
- `revise` decision can trigger next round up to `max_rounds`.
- `accept`/`reject` terminate immediately.

### Deterministic execution approach
Determinism is achieved in tests and local demos by:
- deterministic role callables or fake model response queues,
- explicit round bounds,
- append-only event order assertions.

## 9. Roles and Prompt System

### Deterministic example roles
- `blue_role`: emits fixed bounded move.
- `red_role`: emits low-severity finding referencing blue summary.
- `referee_role`: emits accept decision referencing blue/red content.

### Prompt-driven roles
- `make_prompt_blue_role`: renders blue prompt, parses JSON or plain text summary.
- `make_prompt_red_role`: parses either JSON fields or `MATERIAL:`/`CLAIM:` text format.
- `make_prompt_referee_role`: computes decision from finding flags and asks model only for rationale.

### `PromptRenderer`
- Simple `template.format(**context)` renderer.
- Rejects blank template and blank rendered result.

### Model clients
- `FakeModelClient`: deterministic queued responses and prompt capture.
- `OllamaClient`: local HTTP generate endpoint.

### Role execution flow in runtime
1. Game service builds prompt roles.
2. Runtime invokes role callables through guard.
3. Role factory output models become runtime `Move`/`Finding`/`Decision` records.

### Current limitations
- No tool-calling subsystem.
- No parallel/multi-agent arbitration beyond fixed 3-role sequence.
- No autonomous self-healing referee policy beyond deterministic rules in role implementation.

## 10. Testing Strategy

### Current testing philosophy
- High coverage of behavior contracts over implementation internals.
- Deterministic local tests prioritized.
- Network paths monkeypatched for transport validation.

### Deterministic approach
- `FakeModelClient` drives predictable prompt role outputs.
- Blackbox runtime tests assert event sequence and semantic outcomes.
- Projection tests replay explicit event fixtures and assert derived state exactly.

### Main tested areas
- Schema validation and invariants (`test_schemas.py`).
- Runtime loop/terminal semantics (`test_runtime.py`).
- Blackboard persistence/query helper behavior (`test_blackboard.py`).
- Prompt assembly/rendering and role parsing (`test_prompts.py`, `test_prompt_assembly.py`, `test_example_roles.py`, `test_prompt_roles.py`).
- Integration policy/idempotence (`test_integrator.py`).
- Projection lifecycle and helper queries (`test_projections.py`).
- Artifact lifecycle and handler delegation (`test_artifacts.py`).
- CLI/run spec/state source orchestration (`test_play_game.py`, `test_run_specs.py`, `test_state_sources.py`).
- Demo/autonomous/planner behavior (`test_demo.py`, `test_adversarial_demo.py`, `test_ollama_adversarial_demo.py`, `test_autonomous.py`, `test_planner.py`).

### Why deterministic tests matter here
This architecture relies on:
- ordered append-only event traces,
- replay-based state projection,
- bounded decision semantics.

Nondeterminism would undermine repeatable projection and integration assertions, so deterministic test inputs are foundational to trust in runtime/governance behavior.

## 11. Architectural Invariants (Observed/Enforced)

Enforced in code today:
- `GameContract.max_rounds >= 1`.
- Runtime emits `game_started` before per-round events and `game_completed` at end.
- Runtime round loop advances only on `revise` with remaining budget.
- Role outputs must pass schema validation and semantic validator checks.
- Blackboard API is append/read/query; no mutate/delete operations provided.
- Integration decisions are appended at most once per decision ID via `append_integration_decision_once`.
- Projection functions are replay-based and deterministic for ordered equal input events.
- Schema-required strings are non-empty across core models.

Not strictly enforced globally:
- External processes can still overwrite blackboard file directly.
- `active_roles` content is validated non-empty but not used by runtime for role dispatch.

## 12. Current Architectural Direction

### Implemented direction
- Bounded adversarial games with revise loops.
- Separation of local runtime result and integration decision recording.
- Event replay projected state with discrepancy lifecycle support.
- Planner-driven next-game request generation (deterministic and LLM-backed).
- Autonomous bounded step runner around planner + game service.

### Conceptual/future direction inferred from code
- More explicit referee-style governance over accepted architecture/capability/accomplishment streams.
- Tool integration boundary (not implemented yet).
- Pipeline generation from discrepancies and accepted-state transitions.
- Self-inspection loops using projected state and north-star planning.

## 13. Current Limitations

Concrete limitations in current code:
- No tool execution interface in role outputs or runtime.
- No true multi-agent adversarial loop beyond one blue/red/fixed referee chain per round.
- Runtime contract `active_roles` does not dynamically control invocation order.
- `GameContract.id` in service/CLI path is hardcoded to `"play-game-001"`.
- Artifact lifecycle is not integrated into `GameService.play` acceptance path.
- No persistent transactional store beyond JSONL append log.
- LLM planner output validity is schema-checked but strategic grounding policy is limited.
- No explicit event schema version field or migration framework.
- No concurrency controls around blackboard append/read.

What is deterministic/fake:
- Most tests and demos rely on deterministic roles or `FakeModelClient`.
- Integration policy is deterministic and local-rule based.

What would be needed for a fuller adversarial game loop (additive view):
- Multiple blue/red exchanges per round or role graph scheduling.
- Tool request/result schema and guarded executor boundary.
- Referee policy that can evaluate richer evidence sets.
- Runtime hooks to create artifact proposals and lifecycle events from accepted outcomes.

## 14. Suggested Next Milestones (Additive)

1. Add runtime-level `finding`/`decision` trace linkage IDs to strengthen evidence chains.
2. Introduce explicit tool-request schema plus no-op validator/executor boundary (without replacing current role flow).
3. Add additive role-orchestration mode for multi-red or multi-blue within current round bounds.
4. Emit artifact-proposal records from accepted integration outcomes behind an optional feature flag.
5. Extend referee prompt contract to include explicit decision rubric tokens while keeping current fixed decision authority in prompt-role implementation.
6. Add projection helpers for “next actionable discrepancy” and integration review prioritization.

## 15. Developer Workflow

### Running tests
```bash
uv run pytest
```

### Typical execution paths
- Deterministic demo:
```bash
uv run baps-demo
```
- Prompt/Ollama game:
```bash
uv run baps-play-game --subject ... --goal ... --target-kind ...
```
- Run-spec path:
```bash
uv run baps-play-game --run-spec examples/runs/fake_goal_audit.yaml
```

### Development style reflected by repository
- Additive changes are preferred over rewrites.
- New behavior is usually introduced with narrow modules and dedicated tests.
- Validation and replay semantics are treated as hard boundaries.

### Commit/test expectations (inferred from repository shape)
- Tests are granular by module (`tests/test_<module>.py`).
- Behavior additions generally require deterministic test cases.
- Event-level changes require projection/integration test updates.

## 16. Glossary

- Game: a bounded runtime execution defined by `GameContract` and identified by `game_id` + `run_id`.
- Role: callable participant (`blue`, `red`, `referee`) invoked by runtime.
- Move: Blue output (`Move`) for current round.
- Finding: Red critique (`Finding`) with severity/confidence/material payload and optional block flag.
- Decision: Referee output (`Decision`) selecting `accept`, `revise`, or `reject`.
- Round: one blue/red/referee cycle stored as `GameRound`.
- Runtime: `RuntimeEngine` executing rounds and emitting events.
- Blackboard: append-only JSONL event log managed by `Blackboard`.
- Event: `Event` envelope with `id`, `type`, and JSON payload.
- Prompt renderer: `PromptRenderer` that renders templates with context.
- Prompt assembly: `PromptSpec`/`PromptSection` + `assemble_prompt` section composer.
- Model client: abstraction for text generation (`FakeModelClient`, `OllamaClient`).
- Integration decision: durable local acceptance/defer/reject record (`IntegrationDecision`).
- Projection: replay-derived `ProjectedState` view built from event history.
- Discrepancy: unresolved issue in projected state (`UnresolvedDiscrepancy`) derived from event outcomes.
- Artifact: filesystem-managed entity (`Artifact`) with versions and proposed changes.
- State source: external context declaration resolved via adapters into prompt evidence text.

## Observations and Ambiguities

Observed inconsistencies or ambiguous boundaries (documented, not modified):
- `GameContract.active_roles` is validated but runtime invocation order is hardcoded and does not use that list.
- `GameRecord` schema exists but no module currently persists a game-record entity.
- `run_play_game(...)` exists in `play_game.py`, while `main()` uses `GameService.play(...)`; both paths are maintained.
- Projection of accepted state depends on `integration_decision_recorded` events, not directly on `game_completed` acceptance, by design.
- Artifact proposal lifecycle records are queryable/projectable, but no default path currently emits them from game/integration acceptance.
