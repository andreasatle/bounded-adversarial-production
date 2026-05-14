# Bounded Adversarial Production (`baps`) Architecture

## 1. Project Overview

### Purpose
`bounded-adversarial-production` (`baps`) is a Python framework for running bounded adversarial games over a target problem/artifact. A game is executed by three roles:
- Blue proposes a candidate move.
- Red critiques the Blue move and emits a structured finding.
- Referee emits a structured accept/revise/reject decision and rationale.

### Current Project Philosophy
- Keep boundaries explicit and narrow.
- Use validated data contracts (Pydantic v2) at subsystem boundaries.
- Evolve additively (new layers/facades/adapters) instead of redesigning runtime core.
- Keep execution traces append-only and inspectable.
- Keep tests deterministic and network-independent by default.

### Current Architectural Direction
Current architecture is layered:
- Schema contracts: `src/baps/schemas.py`
- Runtime loop + response projection: `src/baps/runtime.py`
- Role invocation guard: `src/baps/roles.py`
- Prompt-driven role factories: `src/baps/example_roles.py`
- Prompt assembly/rendering: `src/baps/prompt_assembly.py`, `src/baps/prompts.py`
- Model client boundary: `src/baps/models.py`
- Game-type/game-definition data: `src/baps/game_types.py`
- Request->response facade: `src/baps/game_service.py`
- Read-only state source system: `src/baps/state_sources.py`
- Run configuration data model: `src/baps/run_specs.py`
- CLI orchestration: `src/baps/play_game.py`

### What “Bounded Adversarial Production” Means in Practice
In the implemented code:
- Bounded: rounds stop at `GameContract.max_rounds`; `revise` can continue only while budget remains.
- Adversarial: Blue and Red are intentionally opposed; Referee arbitrates.
- Production (current scope): validated contracts + deterministic tests + persistent append-only trace. It is not autonomous deployment automation.

### Current Implementation vs Future Aspirations
Implemented:
- Round-based bounded runtime (`RuntimeEngine.run_game`).
- Prompt-driven and deterministic role implementations.
- `GameRequest -> GameService.play(...) -> GameResponse` protocol boundary.
- Built-in and JSON-loaded `GameDefinition`.
- Read-only state manifests and adapter routing into shared context.
- YAML run specs with CLI override semantics.

Not implemented:
- Tool/action execution protocol.
- Multi-agent orchestration runtime beyond injected callables.
- Artifact mutation integrated into runtime game loop.
- Sponsor/Integrator/StateTransition systems.

## 2. Current System Capabilities

### Schemas (`src/baps/schemas.py`)
Purpose:
- Canonical request/contract/state/response/event/artifact models.

Important models:
- Core game: `GameRequest`, `GameContract`, `Move`, `Finding`, `Decision`.
- Runtime: `GameRound`, `GameState`, `GameRecord`.
- Reporting: `RoundSummary`, `GameResponse`.
- Artifact: `Artifact`, `ArtifactVersion`, `ArtifactChange`, `ArtifactAdapterResult`.
- Trace: `Event`.

Current limitations:
- Many policy semantics are enforced in runtime/roles (not fully encoded in schema types).
- `GameRecord` exists but is not currently persisted by runtime.

Relationships:
- Used by runtime, game service, CLI, artifact subsystem, blackboard, tests.

### Blackboard (`src/baps/blackboard.py`)
Purpose:
- Append-only JSONL event persistence.

Key API:
- `append(event)`
- `read_all()`
- `query(event_type)`

Current limitations:
- No lock/index/rotation/compaction.

Relationships:
- Runtime writes; tests and CLI workflows inspect.

### Artifacts (`src/baps/artifacts.py`)
Purpose:
- Filesystem adapter boundary for artifact lifecycle.

Key components:
- `ArtifactAdapter` interface.
- `ArtifactHandler` dispatcher by `artifact.type`.
- `DocumentArtifactAdapter` implementation (`create`, `snapshot`, `propose_change`, `apply_change`, `rollback`).

Current limitations:
- Only `document` artifact type implemented.
- No merge/conflict semantics.
- Runtime game loop does not orchestrate artifact adapters yet.

### Runtime (`src/baps/runtime.py`)
Purpose:
- Execute bounded rounds and emit events.

Key functions/classes:
- `RuntimeEngine.run_game(...)`
- `generate_run_id()`
- `build_game_response(...)`

Current limitations:
- Single sequential Blue->Red->Referee path per round.
- No branching/parallel round execution.

Relationships:
- Consumes role callables + `RoleInvocationGuard`; writes to `Blackboard`; outputs `GameState`, optionally projected into `GameResponse`.

### Roles (`src/baps/roles.py`, `src/baps/example_roles.py`)
Purpose:
- Role invocation validation/retry and role implementations.

Key items:
- `RoleInvocationGuard`, `RoleInvocationError`
- Deterministic demo roles: `blue_role`, `red_role`, `referee_role`
- Prompt-driven factories: `make_prompt_blue_role`, `make_prompt_red_role`, `make_prompt_referee_role`

Current limitations:
- Red parsing uses lightweight line protocol (`MATERIAL:` / `CLAIM:`), not strict structured extraction.

Relationships:
- Runtime consumes arbitrary compatible callables; factories encapsulate prompt rendering + model calls.

### Prompt Rendering (`src/baps/prompt_assembly.py`, `src/baps/prompts.py`)
Purpose:
- Structured prompt composition and rendering.

Key items:
- `PromptSection`, `PromptSpec`, `assemble_prompt(...)`
- `PromptRenderer.render(...)`

Current limitations:
- String template rendering via `str.format` only.

Relationships:
- Used by role factories and CLI/game service prompt construction.

### Model Abstraction (`src/baps/models.py`)
Purpose:
- Isolate model provider calls from runtime semantics.

Key items:
- `ModelClient` interface
- `FakeModelClient` deterministic tests
- `OllamaClient` (`POST /api/generate`)

Current limitations:
- No streaming/chat/tools/retry logic in client.

### Ollama Integration
Current implementation:
- `OllamaClient` in `models.py`
- Used in `play_game.py` and Ollama demos.

### Deterministic Testing
Current implementation:
- Extensive unit tests under `tests/`
- `FakeModelClient` and monkeypatching isolate from network.

### Demo Game Execution
Scripts:
- `baps-demo`
- `baps-adversarial-demo`
- `baps-ollama-adversarial-demo`
- `baps-play-game`

## 3. Repository Structure

```text
src/baps/
  schemas.py                # core contracts
  runtime.py                # bounded game execution + response projection
  roles.py                  # invocation guard/retry/validation
  example_roles.py          # deterministic + prompt-driven role factories
  game_service.py           # GameRequest -> GameResponse facade
  game_types.py             # game definitions and built-in resolvers
  state_sources.py          # state manifest models + read-only adapters
  run_specs.py              # YAML run spec models + loader
  prompt_assembly.py        # prompt section/spec assembly
  prompts.py                # PromptRenderer
  models.py                 # model client boundary + Ollama/Fake clients
  blackboard.py             # append-only JSONL events
  artifacts.py              # artifact adapters
  play_game.py              # CLI wiring and resolution logic
  demo.py
  adversarial_demo.py
  ollama_adversarial_demo.py
examples/
  game_definitions/documentation_refinement.json
  state_manifests/baps_project_state.json
  runs/fake_goal_audit.yaml
docs/
  ARCHITECTURE.md
  ROADMAP.md
  FAKE-GOALS.md
  FAKE-CURRENT-STATE.md
tests/
  test_*.py
```

Responsibility boundaries:
- `runtime.py` does orchestration only, not prompt/model internals.
- `game_service.py` composes request, prompt roles, runtime, response.
- `play_game.py` resolves CLI/run-spec/state-manifest inputs.
- `state_sources.py` is read-only context loading only.

## 4. Core Runtime Flow

Runtime sequence (`RuntimeEngine.run_game`):
1. Create `run_id` (`run-YYYYMMDD-HHMMSS-<8hex>`).
2. Append `game_started` event.
3. For each round up to `max_rounds`:
   1. Invoke Blue through `RoleInvocationGuard` (validate `Move`, semantic checks).
   2. Append `blue_move_recorded` event.
   3. Invoke Red via guard (validate `Finding`, semantic checks).
   4. Append `red_finding_recorded` event.
   5. Invoke Referee via guard (validate `Decision`, semantic checks).
   6. Append `referee_decision_recorded` event.
   7. Store `GameRound` and revision context.
   8. Stop on `accept`/`reject`; continue only for `revise` with remaining budget.
4. Build `GameState`.
5. Append `game_completed` event containing serialized state.
6. Return `GameState`.

Prompt/model path:
- Runtime does not render prompts nor call model APIs.
- Role callables (created by factories) render prompts and call `ModelClient.generate`.

Persistence:
- Only event trace is persisted by runtime (`Blackboard` JSONL).
- `GameState` is in-memory return value.

Artifact interaction:
- No runtime artifact operations currently.

## 5. Schema Documentation

Key models and why they exist:
- `GameRequest`: sponsor-facing request intent (`game_type`, subject/goal/target, optional `state_source_ids`).
- `GameContract`: runtime input contract with active roles and max rounds.
- `Move` / `Finding` / `Decision`: normalized role outputs.
- `GameRound` / `GameState`: full in-memory run state.
- `RoundSummary` / `GameResponse`: compact reporting projection.
- `Event`: append-only trace record envelope.
- `Artifact*` models: artifact adapter operation contracts.

Notable validation invariants:
- Non-empty strings across identifiers and core text fields.
- `max_rounds >= 1`, `round_number >= 1`, `rounds_played >= 1`.
- `GameRequest.state_source_ids` must contain non-empty IDs.
- Mutable collections use `default_factory` for isolation.

Schema relationships:
- `GameService` converts `GameRequest` -> `GameContract`.
- Runtime emits `GameState`; `build_game_response` maps to `GameResponse`.

## 6. Blackboard/Event System

Append-only behavior:
- `Blackboard.append()` always opens file in append mode and writes one JSON per line.

Event persistence/query:
- Parent directories are created on append.
- `read_all()` returns `[]` if file is missing.
- Each line is parsed and validated as `Event`.
- `query(event_type)` filters by `Event.type`, requires non-empty type.

Runtime event lifecycle currently used:
- `game_started`
- `blue_move_recorded`
- `red_finding_recorded`
- `referee_decision_recorded`
- `game_completed`

Intended current role:
- Auditable execution trace and debugging artifact.

## 7. Artifact System

Adapter architecture:
- Interface: `ArtifactAdapter`.
- Dispatcher: `ArtifactHandler` resolves by artifact type.
- Concrete adapter: `DocumentArtifactAdapter`.

Filesystem structure:
```text
<root>/<artifact_id>/
  current/main.md
  versions/v001/...
  changes/c001/
    proposed.md
    change.json
  metadata.json
```

Lifecycle summary:
- `create`: initializes artifact directories/files.
- `snapshot`: copies `current/` to next `vNNN`.
- `propose_change`: writes candidate content and diff under `changes/cNNN`.
- `apply_change`: promotes proposed content to `current/main.md`, then snapshots.
- `rollback`: replaces `current/` with selected version.

Constraints:
- Local synchronous filesystem ops.
- No concurrency controls or transactional multi-artifact semantics.

## 8. Runtime Engine

Responsibilities:
- Bounded round execution.
- Semantic role output enforcement.
- Event emission.
- Return terminal state.

Role invocation guard:
- `RoleInvocationGuard.invoke(...)` validates schema output and optional semantic validator.
- Retries on `ValidationError` / `ValueError` up to `max_attempts`.
- Raises `RoleInvocationError` after exhaustion.

Game execution semantics:
- Continue only on `decision == revise` and remaining budget.
- Otherwise terminate.

Determinism:
- Runtime transitions are deterministic given role outputs.
- Non-determinism is injected from model/role outputs and run-id timestamp/UUID.

## 9. Roles and Prompt System

Deterministic roles:
- Fixed `blue_role`, `red_role`, `referee_role` for deterministic demonstrations/tests.

Prompt-driven role factories:
- Blue: renders candidate prompt and returns `Move(summary=model_output)`.
- Red: parses `MATERIAL: yes/no`, `CLAIM: ...`; fallback to defaults/full generated text.
- Referee: decision is computed deterministically from Red output:
  - `reject` if `block_integration`
  - `revise` if material
  - `accept` otherwise
  Rationale text is then generated to support fixed decision.

Prompt infra:
- `PromptSection` + `PromptSpec` + `assemble_prompt` enforce non-empty section model and ordered assembly.
- `PromptRenderer` wraps `str.format` and rejects empty template/rendered prompt.

Model clients:
- `FakeModelClient` deterministic, captures prompt list.
- `OllamaClient` calls `/api/generate` (non-streaming).

Current limitations:
- No tool-call protocol.
- No strict JSON output contract for model-generated role text.
- No multi-agent orchestration runtime.

## 10. Testing Strategy

Testing philosophy:
- Validate contract edges, then module behavior, then integration wiring.

Deterministic approach:
- Extensive use of `FakeModelClient`.
- CLI tests patch model client path to avoid network.

Coverage includes:
- Schemas and validation invariants.
- Runtime semantics and event IDs.
- Response projection (`build_game_response`).
- Prompt assembly/rendering.
- Game definition loading and built-ins.
- Game service request->response behavior.
- State manifest/adapters/router and context resolution.
- Run-spec YAML parsing and CLI merge/override behavior.
- Artifact lifecycle behavior.

Why deterministic tests matter here:
- The project encodes protocol semantics in data contracts and orchestration rules; deterministic tests protect those boundaries from regressions.

## 11. Architectural Invariants (Code-Enforced)

- Event log append-only writes (`Blackboard.append`).
- Runtime role outputs are schema-validated before acceptance.
- Runtime semantic checks enforce game-id consistency and Blue role identity.
- Runtime cannot exceed `max_rounds`.
- `GameResponse` projection requires non-empty rounds, final decision, and per-round move/finding/decision.
- State manifest source IDs must be unique.
- Read-only state adapters reject unsupported kinds and invalid paths.
- Run-spec and game-definition loaders must validate parsed data before use.

## 12. Current Architectural Direction

Implemented direction:
- Explicit request/response boundary (`GameRequest`, `GameResponse`, `GameService`).
- Game semantics externalized as `GameDefinition` prompt sections.
- Input configuration externalized via JSON (game definitions), JSON (state manifests), YAML (run specs).
- Read-only project-state context composition via adapters and routing.

Conceptual/future direction (suggested by current boundaries, not implemented):
- Additional built-in game types.
- Stronger structured role output parsing.
- More adapter kinds and richer context policy.
- Deeper orchestration around artifacts/tools while preserving runtime core.

## 13. Current Limitations

- Runtime still executes only one linear Blue->Red->Referee path.
- Artifact subsystem is not yet integrated into runtime rounds.
- Red parsing protocol is text-line based, not robust structured extraction.
- CLI still uses fixed contract ID (`play-game-001`).
- Blackboard has no lock/index/retention management.
- `run_play_game(...)` and `GameService.play(...)` duplicate some prompt assembly logic.
- State adapters are read-only text sources only; no schema-aware summarization.

## 14. Suggested Next Milestones (Additive)

1. Consolidate duplicated prompt assembly between `play_game.py` and `game_service.py` behind a shared helper.
2. Add stricter optional structured parsing path for Red/Referee outputs while keeping fallback behavior.
3. Add additional built-in `GameDefinition` variants using existing data-model boundaries.
4. Add richer event-query helpers (per-run filters, concise summaries) without changing event schema.
5. Add optional artifact-runtime hook layer that projects accepted/revise rounds into artifact proposals.
6. Expand state adapter coverage with small, read-only adapters and router tests.

## 15. Developer Workflow

Setup and tests:
```bash
uv sync
uv run pytest
```

CLI usage examples:
```bash
uv run baps-play-game --subject "..." --goal "..." --target-kind "documentation"
uv run baps-play-game --run-spec examples/runs/fake_goal_audit.yaml
uv run baps-play-game --state-manifest examples/state_manifests/baps_project_state.json --state-source architecture
```

Contribution style used by repository:
- Add/extend schema first.
- Add thin implementation layer.
- Add deterministic tests for success/failure/invariant cases.
- Preserve existing semantics and APIs unless extension is explicitly required.

## 16. Glossary

- Game: one bounded run over a contract.
- GameRequest: sponsor-facing request intent.
- GameContract: runtime execution contract.
- GameState: full runtime result including rounds and final decision.
- GameResponse: compact post-run summary projection.
- Blue role: proposes `Move`.
- Red role: emits `Finding` critique.
- Referee role: emits `Decision`.
- Move: Blue output (`summary`, `payload`).
- Finding: Red output (`claim`, severity/confidence, material/block flags).
- Decision: Referee output (`accept`/`revise`/`reject` + rationale).
- GameDefinition: data model for game-level prompt semantics.
- GameTypePromptSections: per-role prompt section collections.
- GameService: facade executing `GameRequest -> GameResponse`.
- Blackboard: append-only JSONL event store.
- Event: one trace record.
- StateManifest: project-specific declared state sources.
- StateSourceDeclaration: one declared state source (`id`, `kind`, `ref`, `authority`).
- StateSourceAdapter: read-only loader boundary for a state-source kind.
- RoutingStateSourceAdapter: kind-based adapter dispatcher.
- RunSpec: YAML run configuration merged with CLI overrides.
- PromptSection / PromptSpec: sectioned prompt assembly structures.
- PromptRenderer: template renderer for prompt text.
- ModelClient: abstract text-generation boundary.
- FakeModelClient: deterministic test model.
- OllamaClient: concrete local model client.

## Observations and Ambiguities

- `run_play_game(...)` remains as a direct runtime path while CLI `main()` now routes through `GameService`; both construct similar prompt templates. This is consistent but duplicates behavior.
- CLI prints `game_type` even when `--game-definition-file` overrides built-in lookup; displayed type may not identify the loaded file definition.
- `GameRecord` is defined but not currently produced/persisted by runtime or service.
- State manifest refs are interpreted relative to current process working directory, not manifest file location.
