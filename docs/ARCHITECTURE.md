# Bounded Adversarial Production (`baps`) Architecture

## 1. Project Overview

### Purpose
`bounded-adversarial-production` (`baps`) is a Python framework for bounded adversarial game execution over a target problem or artifact. A single game run executes three roles in sequence:
- Blue proposes a candidate move.
- Red critiques Blue’s move and emits a structured finding.
- Referee emits a structured decision (`accept` / `revise` / `reject`) and rationale.

Beyond the runtime loop, the repository now includes additive governance and orchestration layers:
- Integration decisions as durable acceptance authority.
- Append-only blackboard history and projected read models.
- Deterministic and LLM-backed planners.
- Bounded autonomous step execution helpers.

### Current Project Philosophy
The codebase consistently applies:
- Explicit subsystem boundaries.
- Pydantic v2 validation at boundaries.
- Additive evolution instead of core-loop redesign.
- Append-only trace history for inspectability.
- Deterministic, offline tests where possible.

### Current Architectural Direction
Current implementation direction is:
- Keep runtime semantics bounded and deterministic.
- Separate local game completion semantics from durable integration semantics.
- Derive read models from append-only events.
- Keep planner/autonomous execution bounded and controllable.

### What “Bounded Adversarial Production” Means in Practice
In current code:
- Bounded: runtime loops at most `contract.max_rounds` and only continues on `revise` while budget remains.
- Adversarial: Blue and Red are opposed contributors; Referee arbitrates.
- Production scope: validated contracts, append-only events, integration event recording, projected-state helpers, deterministic tests.

### Current Implementation vs Future Aspirations
Implemented now:
- `GameRequest -> GameService.play(...) -> GameResponse` flow.
- Runtime loop + role guard + event trace.
- Integration decision policy + event append helpers.
- Event-derived projected-state read models.
- Deterministic and LLM-backed planners.
- Bounded autonomous one-step and multi-step execution helpers.

Not implemented now:
- Full integrator conflict-resolution workflows.
- Automatic artifact mutation from accepted integration outcomes.
- Autonomous daemon/scheduler/recursive planning.
- Runtime-owned tool ecosystem.

## 2. Current System Capabilities

### Schemas (`src/baps/schemas.py`)
Purpose:
- Canonical contracts for runtime, reporting, governance, artifacts, and event payloads.

Important classes and types:
- Core game/request: `GameRequest`, `GameContract`, `Target`.
- Role outputs: `Move`, `Finding`, `Decision`.
- Runtime state/reporting: `GameRound`, `GameState`, `RoundSummary`, `GameResponse`.
- Governance/integration: `IntegrationDecision`, `GoalAmendmentProposal`, `AgentProfile`.
- Projected state models: `ProjectedState`, `AcceptedAccomplishment`, `AcceptedArchitectureItem`, `AcceptedCapability`, `UnresolvedDiscrepancy`, `ActiveGameSummary`.
- Lifecycle records: `DiscrepancyResolution`, `DiscrepancySupersession`, `AcceptedStateSupersession`, `AcceptedStateRevocation`.
- Artifact contracts: `Artifact`, `ArtifactVersion`, `ArtifactChange`, `ArtifactAdapterResult`, `ArtifactProposalRecord`.
- Event envelope: `Event`.

Current limitations:
- Some semantics are policy-layer concerns (runtime/integrator/projection helpers), not purely schema-enforced.
- `GameRecord` exists but is not currently persisted by runtime.

Relationships:
- Shared across runtime, blackboard, projections, integrator, planner, game service, and tests.

### Blackboard (`src/baps/blackboard.py`)
Purpose:
- Append-only JSONL event history.

Important API:
- `append`, `read_all`, `query`, `query_by_run`, `query_completed_runs`.
- Event append helpers:
  - `append_integration_decision`
  - `append_discrepancy_resolution`
  - `append_discrepancy_supersession`
  - `append_accepted_state_supersession`
  - `append_accepted_state_revocation`
  - `append_artifact_proposal_record`

Current limitations:
- No indexing/compaction/retention.
- No explicit concurrency controls.

Relationships:
- Runtime and governance helpers write events.
- Projections and query helpers read them.

### Artifacts (`src/baps/artifacts.py`)
Purpose:
- Filesystem-backed artifact lifecycle operations.

Important classes/functions:
- `ArtifactAdapter` interface.
- `ArtifactHandler` dispatch.
- `DocumentArtifactAdapter` (`create`, `snapshot`, `propose_change`, `apply_change`, `rollback`).

Current limitations:
- Only document artifact type implemented.
- No merge/conflict resolution.
- Not wired into runtime or integration workflows yet.

Relationships:
- Uses artifact schemas; currently mostly independent of runtime execution.

### Runtime (`src/baps/runtime.py`)
Purpose:
- Execute bounded Blue/Red/Referee loop and emit events.

Important classes/functions:
- `RuntimeEngine.run_game`
- `generate_run_id`
- `build_game_response`
- `_derive_terminal_semantics`
- `_validate_state_for_response`

Current limitations:
- Linear role sequence per round.
- No branch/parallel gameplay.
- No runtime artifact mutation.

Relationships:
- Uses role guard and blackboard.
- `GameService` uses runtime output to create `GameResponse` and trigger integration.

### Roles (`src/baps/roles.py`, `src/baps/example_roles.py`, `src/baps/role_output_parsing.py`)
Purpose:
- Role invocation validation/retry plus deterministic and prompt-driven role implementations.

Important classes/functions:
- `RoleInvocationGuard`, `RoleInvocationError`.
- Demo roles: `blue_role`, `red_role`, `referee_role`.
- Prompt-driven factories:
  - `make_prompt_blue_role`
  - `make_prompt_red_role`
  - `make_prompt_referee_role`
- Shared parse helpers in `role_output_parsing.py`.

Current limitations:
- Parsing is lightweight JSON-first with fallback, not strict end-to-end schema extraction protocol.
- No tool request/response subsystem.

Relationships:
- Runtime consumes role callables; prompt/model details are encapsulated here.

### Prompt Rendering (`src/baps/prompt_assembly.py`, `src/baps/prompts.py`, `src/baps/prompt_roles.py`)
Purpose:
- Prompt section composition and rendering.

Important classes/functions:
- `PromptSection`, `PromptSpec`, `assemble_prompt`.
- `PromptRenderer`, `render_prompt`.
- `build_prompt_roles` and built-in default profile helpers.

Current limitations:
- Template system is `str.format` based only.

Relationships:
- Used by game service and CLI pathways when building prompt-driven role callables.

### Model Abstraction (`src/baps/models.py`)
Purpose:
- Isolate model inference calls behind a boundary.

Important classes:
- `ModelClient` interface.
- `FakeModelClient` (deterministic tests and prompt capture).
- `OllamaClient` (local `/api/generate`).

Current limitations:
- No streaming/tools/chat abstractions.
- No internal retry/backoff policy in client layer.

Relationships:
- Consumed by prompt roles and `LLMPlanner`.

### Ollama Integration
Current implementation:
- Implemented by `OllamaClient`.
- Used in CLI/demo flows.
- Network avoided in tests via fake model + monkeypatching.

### Deterministic Testing
Current implementation:
- Large deterministic suite spanning runtime, integration, projections, planners, autonomous helpers, schemas, and CLI wiring.
- Uses fake/stub role/model behavior for predictability.

### Demo Game Execution
CLI/demo entry points:
- `baps-demo`
- `baps-adversarial-demo`
- `baps-ollama-adversarial-demo`
- `baps-play-game`

## 3. Repository Structure

```text
src/baps/
  schemas.py                # Core contracts and constrained types
  runtime.py                # Bounded game loop + GameResponse projection
  roles.py                  # Role guard and retry policy
  example_roles.py          # Deterministic + prompt-driven role callables
  role_output_parsing.py    # Shared role output parsing utilities
  prompt_assembly.py        # Prompt section/spec validation and assembly
  prompts.py                # PromptRenderer and render helper
  prompt_roles.py           # Prompt role wiring + default built-in profiles
  models.py                 # Model abstraction (fake + Ollama)
  blackboard.py             # Append-only event persistence + helpers
  integrator.py             # Integration policies and recording helpers
  projections.py            # Read-model builders and event-level filters
  planner.py                # Planner protocol + DefaultPlanner + LLMPlanner
  autonomous.py             # Bounded autonomous step runners
  game_service.py           # Request->runtime->response orchestration
  game_types.py             # Built-in/file game-definition resolution
  state_sources.py          # Read-only state source manifest/adapters/router
  run_specs.py              # YAML run-spec contracts and loader
  play_game.py              # CLI argument/run-spec/state-source wiring
  artifacts.py              # Filesystem artifact adapter layer
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
- Runtime: bounded execution semantics.
- Integrator: durable integration authority generation.
- Projections: read models from event history.
- Planner/autonomous: bounded next-step orchestration only.
- Artifacts: filesystem lifecycle primitives, not yet runtime-owned.

## 4. Core Runtime Flow

`RuntimeEngine.run_game(contract, blue_role, red_role, referee_role)` sequence:
1. Generate run id (`generate_run_id`).
2. Append `game_started` event.
3. For each round up to `max_rounds`:
   1. Invoke Blue through `RoleInvocationGuard` and validate semantics.
   2. Append `blue_move_recorded`.
   3. Invoke Red through guard and validate semantics.
   4. Append `red_finding_recorded`.
   5. Invoke Referee through guard and validate semantics.
   6. Append `referee_decision_recorded`.
   7. Add `GameRound` to in-memory list.
   8. Stop on `accept`/`reject`, continue on `revise` with remaining budget.
4. Construct `GameState`.
5. Project to `GameResponse` via `build_game_response`.
6. Append `game_completed` event including state and terminal semantics.
7. Return `GameState`.

Prompt/model execution path:
- Runtime does not directly render prompts or call model APIs.
- Prompt rendering and model generation happen inside role callables.

Persistence path:
- Append-only event writes to blackboard.
- Runtime returns in-memory state.

Artifact interaction:
- Runtime does not call artifact adapters or mutate files.

## 5. Schema Documentation

### Request/contract/runtime
- `GameRequest`
  - Fields: `game_type`, `subject`, `goal`, `target_kind`, `target_ref`, `state_source_ids`.
  - Invariants: non-empty key strings; state source ids non-empty.
  - Why: formal external request envelope.
- `GameContract`
  - Fields: id/subject/goal/target/roles/max_rounds/scopes.
  - Invariants: non-empty ids/text; non-empty roles; `max_rounds >= 1`.
  - Why: explicit runtime boundary contract.
- `GameRound`, `GameState`, `GameRecord`
  - Runtime round aggregation and lifecycle record schema.
  - Why: consistent runtime state shape and external lifecycle placeholder.

### Role outputs
- `Move`: Blue output envelope (`summary`, `payload`).
- `Finding`: Red critique (`claim`, severity/confidence, flags, payload).
- `Decision`: Referee decision + rationale.

### Response semantics
- `GameResponse`
  - Includes constrained local terminal semantics:
    - `terminal_outcome`: `accepted_locally|rejected_locally|revision_budget_exhausted`
    - `integration_recommendation`: `integration_recommended|do_not_integrate`
  - Authority note:
    - `integration_recommendation` is non-authoritative guidance.
    - Durable acceptance authority is represented by recorded `IntegrationDecision` events.
  - Why: stable response projection boundary for downstream governance.

### Governance and planning-related schemas
- `IntegrationDecision`: durable integration outcome and rationale.
- `GoalAmendmentProposal`: explicit proposal-only goal amendment contract.
- `AgentProfile`: explicit prompt role-behavior profile.

### Projected-state schemas
- `ProjectedState`: accepted lists + discrepancy list + active games + projection metadata.
- `UnresolvedDiscrepancy`: includes kind, severity, status, optional artifact linkage.
- `Accepted*` item models and `ActiveGameSummary`.
  - Current implementation note:
    - In architecture projections, `AcceptedArchitectureItem.source_run_id` is populated from the integration decision `run_id`.
    - `source_event_id` remains accepted as a backward-compatible input alias during transition.

### Lifecycle event payload schemas
- `DiscrepancyResolution`, `DiscrepancySupersession`.
- `AcceptedStateSupersession`, `AcceptedStateRevocation`.
- `ArtifactProposalRecord`:
  - Fields: proposal identity, artifact/change linkage, source run, optional integration decision id, status, summary.
  - Why: append-only record for artifact proposal lifecycle, independent of immediate file mutation.

### Artifact schemas
- `Artifact`, `ArtifactVersion`, `ArtifactChange`, `ArtifactAdapterResult`.

### Event schema
- `Event`: generic append-only trace unit (`id`, `type`, `payload`).

## 6. Blackboard/Event System

Append-only philosophy:
- `append` writes newline-delimited JSON in append mode.
- No mutating/rewrite API for existing entries.

Persistence details:
- Parent dirs are created on append.
- `read_all` validates each line as `Event`.

Query behaviors:
- `query(event_type)` with non-empty validation.
- `query_by_run(run_id)` with non-empty validation.
- `query_completed_runs()` convenience for completion events.

Current event categories:
- Runtime: start/move/finding/decision/completed.
- Integration decisions.
- Discrepancy lifecycle events.
- Accepted-state lifecycle events.
- Artifact proposal record events.

Intended role:
- Durable append-only history used for replay, inspection, and projected read-model derivation.

## 7. Artifact System

Adapter boundary:
- `ArtifactAdapter` interface defines lifecycle methods.
- `ArtifactHandler` dispatches by artifact type.

Document adapter layout:
```text
<root>/<artifact_id>/
  current/main.md
  versions/vNNN/
  changes/cNNN/
    proposed.md
    change.json
  metadata.json
```

Operations:
- `create`: initialize artifact directory and metadata.
- `snapshot`: copy current to next version directory.
- `propose_change`: create change dir + diff + proposed content.
- `apply_change`: copy proposal to current and snapshot.
- `rollback`: restore current from version.

Current assumptions/constraints:
- Local filesystem, synchronous operations.
- No runtime/integrator automatic mutation path yet.

## 8. Runtime Engine

Runtime responsibilities:
- Execute bounded game loop.
- Validate role outputs semantically and structurally.
- Emit ordered events.
- Return terminal `GameState`.

Role invocation guard:
- `RoleInvocationGuard.invoke(...)` handles schema validation + semantic validation callback + retries.
- Emits classified `RoleInvocationError` on exhaustion.

Retry behavior:
- Bounded by `max_attempts` (default 2).
- No runtime-internal backoff strategy.

Execution model:
- Linear round orchestration.
- Continue only on `revise` within budget.

Determinism:
- Given deterministic roles/model outputs, runtime behavior is deterministic.

## 9. Roles and Prompt System

Deterministic roles:
- Fixed demo role implementations in `example_roles.py`.

Prompt-driven roles:
- Blue/Red/Referee factories render role prompts and call model client.
- Output parsing supports JSON-first + fallback behavior:
  - Blue: summary/payload extraction.
  - Red: materiality/claim and optional structured fields.
  - Referee: rationale extraction while preserving deterministic decision policy.

Prompt rendering:
- `PromptSection` and `PromptSpec` enforce non-empty and duplicate-title constraints.
- `PromptRenderer` rejects empty template/output.

Model clients:
- `FakeModelClient` for deterministic tests.
- `OllamaClient` for local model calls.

Current limitations:
- No tool invocation protocol.
- No true multi-agent runtime branching.
- Parsing robustness is intentionally lightweight.

## 10. Testing Strategy

Testing philosophy:
- Validate contracts and boundaries first.
- Keep behavior deterministic and offline.

What is tested:
- Schema validation and mutable-default isolation.
- Runtime loop semantics and event ordering.
- Integration policy and idempotent recording behavior.
- Projection/read-model derivation semantics.
- Planner and autonomous bounded behavior.
- State-source/run-spec/CLI wiring.
- Artifact adapter filesystem behavior.

Why deterministic tests matter:
- Core correctness depends on strict transformations:
  - role outputs -> runtime state
  - runtime/integration events -> projected read models
  - planner/autonomous control flow

## 11. Architectural Invariants

Code-enforced invariants include:
- Blackboard history is append-only.
- Runtime rounds do not exceed `max_rounds`.
- Role outputs are validated before acceptance.
- `GameResponse` terminal semantics are constrained.
- Integration decisions are explicit records.
- Projected state is event-derived.
- Default mutable fields use isolated `default_factory`.
- Autonomous helpers are bounded (fixed-step, optional bounded early-stop) and non-recursive.

## 12. Current Architectural Direction

Implemented direction:
- Bounded adversarial execution with explicit local terminal semantics.
- Durable integration authority layer with event recording.
- Projection/read-model layer for accepted state and discrepancies.
- Initial planning/autonomous layer with deterministic/LLM options.
- Artifact proposal lifecycle schemas/events/read-model helpers (without automatic mutation).

Conceptual/future direction (inferred from boundaries):
- Explicit integration conflict-resolution workflows.
- Stronger discrepancy remediation linkage to concrete artifacts.
- Optional autonomous orchestration stop heuristics beyond current bounded options.
- Richer tool boundaries for role evidence gathering.

## 13. Current Limitations

Concrete limitations in current code:
- Runtime is linear and single-branch.
- Artifact adapter layer is not integrated with runtime/integrator mutation workflow.
- No automatic application of artifact proposals.
- LLM planner is single-shot JSON parse with optional deterministic fallback.
- Autonomous execution is bounded but not scheduler/daemon based.
- Blackboard query model is linear scan with no indexing/locking.

## 14. Suggested Next Milestones

Additive milestones aligned with current architecture:
1. Add explicit artifact-proposal signal schema in runtime/game response path (instead of inference).
2. Add integration-to-artifact-proposal status transition helpers (accepted/rejected linkage events).
3. Add optional bounded autonomous stop on integration review queue criteria.
4. Add projection helpers for goal-amendment event streams.
5. Add explicit resolver policy variants for multi-candidate integration conflicts.
6. Add event replay/report utilities for governance/audit slices.

## 15. Developer Workflow

Environment and tests:
```bash
uv sync
uv run pytest
```

Common runs:
```bash
uv run baps-play-game --subject "..." --goal "..." --target-kind "..."
uv run baps-adversarial-demo
uv run baps-ollama-adversarial-demo
```

Contribution style reflected in repo:
- Add schema contract first when possible.
- Add narrow helper/module with explicit scope.
- Add deterministic tests for new behavior/invariants.
- Preserve existing public semantics unless explicitly changing them.

## 16. Glossary

- Game: bounded Blue/Red/Referee execution under a `GameContract`.
- Run: concrete game instance with unique `run_id`.
- GameRequest: planner/sponsor request envelope for one game.
- GameContract: runtime execution contract.
- Move: Blue output.
- Finding: Red critique output.
- Decision: Referee output.
- GameState: full runtime state snapshot.
- GameResponse: compact post-run projection with local terminal semantics.
- IntegrationDecision: durable integration authority record.
- Blackboard: append-only JSONL event history.
- ProjectedState: read model derived from events.
- UnresolvedDiscrepancy: discrepancy record with kind/severity/status.
- ArtifactProposalRecord: append-only proposal lifecycle record tied to artifact/change/run context.
- Planner: component that chooses next bounded game request.
- Autonomous step: one bounded cycle: project -> plan -> play.
- PromptRenderer: template rendering boundary.
- ModelClient: model text-generation abstraction.

## Observations and Ambiguities

1. `AcceptedArchitectureItem.source_run_id` is currently populated from integration decision `run_id` in projection logic.
2. `GoalAmendmentProposal.status` includes `approved` and `rejected`, but no approval authority workflow is implemented yet.
3. Artifact proposal records are available as explicit schemas/events/read-model helpers, but there is currently no runtime/service-level explicit proposal signal protocol; automatic inference from local acceptance was intentionally removed.
4. Autonomous multi-step early-stop with `stop_when_no_open_discrepancies=True` rebuilds projected state before each step and may invoke an additional projection build for the final stop check; this is correct but relevant for performance expectations.
