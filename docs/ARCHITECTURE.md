# Bounded Adversarial Production (`baps`) Architecture

## 1. Project Overview

### Purpose
`bounded-adversarial-production` (`baps`) is a Python framework for bounded adversarial game execution over a target problem/artifact. A game executes three roles:
- Blue proposes a candidate move.
- Red critiques the move and emits a finding.
- Referee issues an accept/revise/reject decision.

The codebase now also includes additive governance layers around runtime execution:
- Integration decisions (durable acceptance authority).
- Projected state derivation from append-only blackboard events.
- Minimal planning/autonomous-step orchestration.

### Current Project Philosophy
The implemented code reflects these explicit constraints:
- Narrow boundaries between layers (schemas, runtime, prompt/model, persistence, orchestration).
- Pydantic model validation at boundaries.
- Append-only event history (no in-place history mutation).
- Deterministic testability with fake model clients.
- Additive extension (new modules/helpers) over core loop redesign.

### Current Architectural Direction
Current direction in code is:
- Keep runtime semantics bounded and deterministic.
- Push durable-state authority into integration events and projections.
- Keep planner/autonomous components small and bounded.
- Keep read models derived from blackboard history.

### What “Bounded Adversarial Production” Means in Practice
Implemented semantics:
- Bounded: runtime loop continues only while `decision == "revise"` and `round <= max_rounds`.
- Adversarial: Blue/Red are opposed; Referee arbitrates.
- Production scope: validated contracts, append-only events, integration decisions, projected read models, deterministic tests.

### Current Implementation vs Future Aspirations
Implemented now:
- `GameRequest -> GameService.play(...) -> GameResponse` protocol.
- Runtime event emission + response projection.
- Integration decision generation + event recording.
- Projected state derived from events.
- Minimal planners and bounded autonomous helpers.

Not implemented now:
- Full Integrator conflict-resolution workflows.
- Automated discrepancy matching/resolution logic.
- Autonomous daemon/scheduler or recursive planning.
- Runtime-level artifact mutation orchestration.
- Tool-execution ecosystem.

## 2. Current System Capabilities

### Schemas (`src/baps/schemas.py`)
Purpose:
- Canonical contracts for request/response, runtime state, events, governance records, artifacts.

Important classes/types:
- Request/runtime: `GameRequest`, `GameContract`, `GameRound`, `GameState`.
- Role outputs: `Move`, `Finding`, `Decision`.
- Response: `RoundSummary`, `GameResponse`.
- Integration/governance: `IntegrationDecision`, `GoalAmendmentProposal`, `AgentProfile`.
- Projection models: `ProjectedState`, `AcceptedAccomplishment`, `AcceptedArchitectureItem`, `AcceptedCapability`, `UnresolvedDiscrepancy`, `ActiveGameSummary`.
- Lifecycle records: `DiscrepancyResolution`, `DiscrepancySupersession`, `AcceptedStateSupersession`, `AcceptedStateRevocation`.
- Trace/artifacts: `Event`, `Artifact*`.

Current limitations:
- Some semantics remain runtime/policy-layer concerns instead of schema-level constraints.
- `GameRecord` exists but runtime does not persist/use it.

Relationships:
- Used by runtime, blackboard, integrator, projections, game service, planner, CLI, tests.

### Blackboard (`src/baps/blackboard.py`)
Purpose:
- Append-only JSONL persistence for execution/governance events.

Important API:
- `append`, `read_all`, `query`, `query_by_run`, `query_completed_runs`.
- Event helper methods for integration and discrepancy/accepted-state lifecycle events.

Current limitations:
- No indexing/locking/retention/compaction.
- Query is linear scan over file.

Relationships:
- Runtime/integration helpers append events.
- Projections/read models consume history.

### Artifacts (`src/baps/artifacts.py`)
Purpose:
- Local filesystem artifact adapter boundary.

Important classes/functions:
- `ArtifactAdapter`, `ArtifactHandler`, `DocumentArtifactAdapter`.
- Operations: `create`, `snapshot`, `propose_change`, `apply_change`, `rollback`.

Current limitations:
- Only `document` type implemented.
- No merge/conflict engine.
- Not yet wired into runtime loop.

Relationships:
- Standalone subsystem with schema alignment (`Artifact*` models).

### Runtime (`src/baps/runtime.py`)
Purpose:
- Execute bounded adversarial rounds and emit events.

Important classes/functions:
- `RuntimeEngine.run_game`.
- `generate_run_id`.
- `build_game_response`.
- `_derive_terminal_semantics`, `_validate_state_for_response`.

Current limitations:
- Single-threaded linear round flow.
- No branching/multi-agent orchestration.
- No artifact mutations inside runtime.

Relationships:
- Uses `RoleInvocationGuard` and `Blackboard`.
- `GameService` projects runtime output to `GameResponse` and then integrates.

### Roles (`src/baps/roles.py`, `src/baps/example_roles.py`, `src/baps/role_output_parsing.py`)
Purpose:
- Enforce role output validation/retry and provide deterministic/prompt-driven role implementations.

Important classes/functions:
- `RoleInvocationGuard`, `RoleInvocationError`.
- Deterministic roles: `blue_role`, `red_role`, `referee_role`.
- Prompt-driven factories: `make_prompt_blue_role`, `make_prompt_red_role`, `make_prompt_referee_role`.
- Shared parse helpers in `role_output_parsing.py`.

Current limitations:
- Parsing is JSON-first with fallback, but still lightweight text-based fallback semantics.
- No tool protocol in role outputs.

Relationships:
- Runtime consumes role callables; prompt/model usage encapsulated in prompt-driven roles.

### Prompt Rendering (`src/baps/prompt_assembly.py`, `src/baps/prompts.py`, `src/baps/prompt_roles.py`)
Purpose:
- Build and render role prompts from sectioned specs and optional agent profiles.

Important classes/functions:
- `PromptSection`, `PromptSpec`, `assemble_prompt`.
- `PromptRenderer`, `render_prompt`.
- `build_prompt_roles`, `default_blue_profile`, `default_red_profile`, `default_referee_profile`.

Current limitations:
- `str.format` templates only.
- No external templating engine.

Relationships:
- `GameService` and CLI pathways build prompt roles through this layer.

### Model Abstraction (`src/baps/models.py`)
Purpose:
- Isolate model invocation from orchestration logic.

Important classes:
- `ModelClient` interface.
- `FakeModelClient` deterministic responses and prompt capture.
- `OllamaClient` local HTTP `/api/generate`.

Current limitations:
- No streaming/tools/chat API abstraction.
- No retry/backoff in client.

Relationships:
- Used by prompt roles and LLM planner.

### Ollama Integration
Current state:
- Concrete client in `models.py`.
- Used by `play_game.py` and `ollama_adversarial_demo.py`.
- Tests avoid real network calls.

### Deterministic Testing
Current state:
- Extensive offline test suite with `FakeModelClient` and deterministic stubs.
- Coverage spans schemas, runtime, projections, planner, autonomous, integrator, CLI parsing/wiring.

### Demo Game Execution
Entry points include:
- `baps-demo`
- `baps-adversarial-demo`
- `baps-ollama-adversarial-demo`
- `baps-play-game`

## 3. Repository Structure

```text
src/baps/
  schemas.py              # canonical Pydantic contracts
  runtime.py              # bounded execution and response projection
  roles.py                # role guard + retry classification
  example_roles.py        # deterministic and prompt-driven role implementations
  role_output_parsing.py  # shared JSON/text parsing helpers
  prompt_assembly.py      # prompt section/spec assembly and validation
  prompts.py              # template rendering boundary
  prompt_roles.py         # prompt-role wiring + default agent profiles
  models.py               # model client abstraction + fake/ollama clients
  blackboard.py           # append-only event persistence + query helpers
  integrator.py           # integration policies + decision recording helpers
  projections.py          # read-model derivation from event history
  planner.py              # deterministic and LLM-based planners
  autonomous.py           # bounded one-step/multi-step autonomous helpers
  game_service.py         # request-to-runtime-to-response orchestration
  game_types.py           # built-in/file-loaded game definitions
  state_sources.py        # state manifests + read-only source adapters
  run_specs.py            # YAML run-spec contracts and loader
  play_game.py            # CLI and config merging
  artifacts.py            # artifact adapters (filesystem)
  demo.py
  adversarial_demo.py
  ollama_adversarial_demo.py
examples/
  game_definitions/
  state_manifests/
  runs/
tests/
  test_*.py
docs/
  ARCHITECTURE.md
  ROADMAP.md
  FAKE-*.md
```

Responsibility boundaries:
- Runtime does bounded execution, not planning/integration authority.
- Integrator decides durable acceptance semantics.
- Projections derive read models from append-only events.
- Planner chooses next request; autonomous helper only orchestrates bounded calls.

## 4. Core Runtime Flow

Execution sequence for `RuntimeEngine.run_game(contract, blue_role, red_role, referee_role)`:
1. Generate `run_id`.
2. Append `game_started` event.
3. For each round:
   - Invoke Blue through `RoleInvocationGuard` (`Move` + semantic checks).
   - Append `blue_move_recorded`.
   - Invoke Red through guard (`Finding` + checks).
   - Append `red_finding_recorded`.
   - Invoke Referee through guard (`Decision` + checks).
   - Append `referee_decision_recorded`.
   - Persist round in memory.
   - Stop on `accept`/`reject`, or continue on `revise` within budget.
4. Build `GameState`.
5. Derive terminal semantics for response projection.
6. Append `game_completed` with serialized state and terminal semantics.
7. Return `GameState`.

Prompt/model call path:
- Prompt construction and model generation happen inside role callables, not runtime core.

Persistence path:
- Runtime writes append-only events to blackboard JSONL.
- `GameState` is returned in memory.

Artifacts and runtime:
- No direct artifact lifecycle calls from runtime loop currently.

## 5. Schema Documentation

### Core request/contract/state
- `GameRequest`: `game_type`, `subject`, `goal`, `target_kind`, `target_ref`, `state_source_ids`.
  - Non-empty validation for required strings.
  - `state_source_ids` enforces non-empty IDs.
- `GameContract`: runtime envelope (`id`, goal/subject/target, roles, max rounds, scope lists).
  - `active_roles` non-empty.
  - `max_rounds >= 1`.
- `GameRound`: per-round move/finding/decision aggregation; round >= 1.
- `GameState`: runtime output (`game_id`, `run_id`, `current_round`, rounds, final decision).

### Role output contracts
- `Move`: blue output (`summary`, `payload`).
- `Finding`: red output (`claim`, severity/confidence, evidence, payload, block flag).
- `Decision`: referee output (`decision`, `rationale`).

### Response-layer semantics
- `GameResponse`: compact run response including constrained:
  - `terminal_outcome` (`accepted_locally`, `rejected_locally`, `revision_budget_exhausted`)
  - `integration_recommendation` (`integration_recommended`, `do_not_integrate`)

### Governance/integration
- `IntegrationDecision`: durable integration authority record with constrained outcome/target kind.
- `GoalAmendmentProposal`: proposal-only goal amendment schema with status (`proposed|approved|rejected`).
- `AgentProfile`: explicit role behavior profile (`role`, `critique_level`, instructions).

### Projection/read-model contracts
- `ProjectedState` with lists:
  - accepted accomplishments/architecture/capabilities
  - unresolved discrepancies
  - active games
  - projection metadata counts
- `UnresolvedDiscrepancy` includes kind/severity/status and optional artifact linkage.
- Discrepancy lifecycle records:
  - `DiscrepancyResolution`
  - `DiscrepancySupersession`
- Accepted-state lifecycle records:
  - `AcceptedStateSupersession`
  - `AcceptedStateRevocation`

### Artifact/event contracts
- `Artifact`, `ArtifactVersion`, `ArtifactChange`, `ArtifactAdapterResult`.
- `Event` (id/type/payload) for append-only blackboard records.

Why these schemas exist:
- Enforce explicit boundary contracts for runtime, governance, and read models while preserving additive evolution.

## 6. Blackboard/Event System

Append-only philosophy:
- `Blackboard.append` always writes one JSON object per line in append mode.
- No event rewrite or deletion API.

Event persistence:
- UTF-8 JSONL at configured path.
- Parent directories are created on append.

Read/query:
- `read_all()` returns parsed/validated `Event` list.
- `query(event_type)` filters by type with non-empty validation.
- `query_by_run(run_id)` filters on payload `run_id`.
- `query_completed_runs()` returns `game_completed` events.

Current event lifecycle families:
- Runtime: `game_started`, `blue_move_recorded`, `red_finding_recorded`, `referee_decision_recorded`, `game_completed`.
- Integration: `integration_decision_recorded`.
- Discrepancy lifecycle: `discrepancy_resolution_recorded`, `discrepancy_supersession_recorded`.
- Accepted-state lifecycle: `accepted_state_supersession_recorded`, `accepted_state_revocation_recorded`.

Intended role:
- Durable append-only audit history from which read models are derived.

## 7. Artifact System

Adapter model:
- `ArtifactAdapter` defines artifact operations.
- `ArtifactHandler` delegates by artifact type.

Filesystem structure (`DocumentArtifactAdapter`):
```text
<root>/<artifact_id>/
  current/main.md
  versions/vNNN/...
  changes/cNNN/
    proposed.md
    change.json
  metadata.json
```

Lifecycle operations:
- `create`: initialize directories/files.
- `snapshot`: copy current state to version directory.
- `propose_change`: write change proposal with unified diff.
- `apply_change`: promote proposed content to current + snapshot.
- `rollback`: restore `current/` from chosen version.

Current constraints:
- Local synchronous filesystem only.
- No runtime orchestration of these operations yet.

## 8. Runtime Engine

Runtime responsibilities:
- Enforce bounded game execution.
- Validate role outputs and semantics via guard callbacks.
- Emit ordered events per round and completion.
- Return `GameState`; support `GameResponse` projection.

Role invocation guard:
- `RoleInvocationGuard.invoke(...)` validates output model + semantic validator.
- Retries bounded by `max_attempts`.
- Raises `RoleInvocationError` with failure classification.

Retry behavior:
- Default guard attempts = 2.
- Retries on schema/semantic failures according to guard logic.

Game model:
- Single linear Blue->Red->Referee cycle per round.
- Continue only on revise + remaining budget.

Determinism:
- Runtime deterministic given role callable outputs.
- Non-determinism limited to run-id generation and model-backed role calls.

## 9. Roles and Prompt System

Deterministic roles:
- Fixed baseline role functions in `example_roles.py`.

Prompt-driven roles:
- Blue/Red/Referee factories render prompts and call `ModelClient.generate`.
- Blue/Red/Referee parse JSON-first with safe fallback to text semantics.
- Referee decision remains deterministic from finding semantics; model output influences rationale text only.

Prompt assembly:
- `PromptSection`/`PromptSpec` validation (non-empty content, duplicate section-title checks).
- Assembly preserves section order.

Prompt renderer:
- `PromptRenderer` validates non-empty template and non-empty rendered output.

Fake/Ollama clients:
- `FakeModelClient` deterministic list-responses for tests.
- `OllamaClient` local HTTP generate API.

Current limitations:
- No tool invocation system.
- No multi-agent runtime orchestration.
- Parsing remains intentionally lightweight.

## 10. Testing Strategy

Current philosophy:
- Boundary-first tests for schemas, runtime flow, and event/read-model semantics.
- Deterministic offline tests by default.

Implemented strategy:
- `FakeModelClient` for planner and prompt-driven roles.
- Runtime and integrator behavior tested with deterministic stubs.
- Projections tested with explicit event streams.
- CLI parsing/override behavior tested without external dependencies.

Why determinism matters:
- The architecture relies on strict mappings from role outputs -> events -> projections.
- Deterministic tests make regressions in semantics/event ordering observable.

## 11. Architectural Invariants

Enforced invariants visible in code/tests:
- Blackboard history is append-only.
- Runtime round count is bounded by `contract.max_rounds`.
- Role outputs are validated against explicit schemas.
- Response terminal semantics are constrained and derived from validated state.
- Integration decisions are explicit records, not implicit runtime side effects.
- Projected state is derived from events, not mutable canonical storage.
- Mutable default fields use `default_factory` isolation.
- Planner/autonomous helpers are bounded and explicit (no hidden loops).

## 12. Current Architectural Direction

Implemented direction:
- Bounded adversarial runtime with explicit response semantics.
- Durable governance events (integration + lifecycle records).
- Projection/read-model layer over append-only history.
- Initial planning/autonomous-step orchestration with deterministic and LLM-backed planners.

Conceptual/future direction (inferred from boundaries, not yet implemented):
- Richer integrator arbitration/conflict resolution.
- Expanded discrepancy lifecycle and reconciliation rules.
- Deeper planner sophistication and optional stopping criteria.
- Stronger artifact-state coupling for discrepancy remediation.

## 13. Current Limitations

Concrete current limitations:
- Runtime remains single-threaded and non-branching.
- Artifact subsystem is not connected to runtime loop.
- No autonomous daemon/scheduler; only bounded helper calls.
- LLM planner has single-shot JSON parse + fallback, no multi-candidate deliberation.
- Integration lifecycle currently lacks full revocation/supersession conflict policy semantics beyond metadata marking.
- Blackboard has no indexing/concurrency coordination.

## 14. Suggested Next Milestones

Additive milestones aligned to current architecture:
1. Add projection helpers for goal-amendment proposals/events (without auto-approval).
2. Add explicit integrator conflict-resolution policy variants (still deterministic by default).
3. Add bounded autonomous-run stop conditions based on projected review queue saturation.
4. Add artifact-aware discrepancy remediation request templates in planner prompts.
5. Add richer referee convergence metrics in `GameResponse`/events while preserving runtime loop.
6. Add optional event replay/report utilities for per-run governance trace inspection.

## 15. Developer Workflow

Environment and tests:
```bash
uv sync
uv run pytest
```

Common execution:
```bash
uv run baps-play-game --subject "..." --goal "..." --target-kind "..."
uv run baps-adversarial-demo
uv run baps-ollama-adversarial-demo
```

Contribution style reflected in repo:
- Add schema contract first.
- Add narrow helper/module with explicit boundaries.
- Add deterministic tests for new invariants/semantics.
- Avoid redesign of runtime core unless explicitly requested.

## 16. Glossary

- Game: one bounded Blue/Red/Referee execution under a `GameContract`.
- Run: a concrete game execution instance identified by `run_id`.
- GameRequest: sponsor/planner-facing request describing game intent and target.
- GameContract: runtime-validated execution envelope.
- Move: Blue role output.
- Finding: Red role critique output.
- Decision: Referee output.
- GameState: full in-memory runtime state for a run.
- GameResponse: compact response projection with terminal and integration recommendation semantics.
- IntegrationDecision: durable integrator authority record for accepted/rejected/deferred integration outcomes.
- Blackboard: append-only JSONL event store.
- Event: one typed record in blackboard history.
- ProjectedState: read model derived from event history.
- Discrepancy: unresolved project issue record with kind/severity/status.
- Supersession/Revocation: lifecycle markers that preserve history while changing read-model currentness.
- Planner: component that selects the next bounded `GameRequest` from north star + projected state.
- Autonomous step: one bounded `projected_state -> plan -> play` orchestration cycle.
- PromptSection/PromptSpec: structured prompt composition contracts.
- PromptRenderer: template rendering boundary.
- ModelClient: model generation interface.

## Observations and Ambiguities

1. `AcceptedArchitectureItem.source_event_id` is currently populated with integration decision `run_id` in projections. Naming implies event identity, but current behavior uses run identity.
2. `GoalAmendmentProposal.status` allows `approved`/`rejected`, but no approval authority workflow is implemented yet; status transitions are external.
3. `integrate_many(...)` appends decisions idempotently by decision id, but conflict metadata semantics are policy-specific and currently only encoded by default multi-candidate policy.
4. `TODO-note.md` is present in `docs/`, while roadmap consolidation is centered on `ROADMAP.md`; this may reflect in-progress local notes rather than canonical architecture docs.
