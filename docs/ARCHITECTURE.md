# Bounded Adversarial Production (`baps`) Architecture

## 1. Project Overview

### Purpose
`bounded-adversarial-production` (`baps`) is an experimental Python framework for bounded adversarial game execution over a target artifact/problem. A game is executed through three roles:
- Blue: proposes a candidate move.
- Red: critiques the Blue move and reports findings.
- Referee: returns a structured decision and rationale.

### Current Project Philosophy
- Keep boundaries explicit and narrow.
- Validate structured data at boundaries with Pydantic v2 models.
- Prefer additive evolution over architectural rewrites.
- Keep runtime traces append-only and inspectable.
- Keep tests deterministic and offline.

### Current Architectural Direction
The codebase is organized into separable layers:
- Schema layer: typed contracts (`schemas.py`).
- Execution layer: runtime orchestration (`runtime.py`) + invocation guard (`roles.py`).
- Trace persistence layer: append-only event log (`blackboard.py`).
- Artifact lifecycle layer: adapter + document filesystem implementation (`artifacts.py`).
- Prompt/model layer: prompt rendering and model clients (`prompt_assembly.py`, `prompts.py`, `models.py`).
- Game-definition layer: built-in and file-loaded game prompt sections (`game_types.py`).
- CLI/demo layer: deterministic and Ollama-backed entry points (`demo.py`, `adversarial_demo.py`, `ollama_adversarial_demo.py`, `play_game.py`).

### What “Bounded Adversarial Production” Means in Practice
In current code:
- Bounded: runtime loops at most `contract.max_rounds` and only continues when referee decides `revise`.
- Adversarial: Red critiques Blue; referee arbitrates accept/revise/reject.
- Production (current scope): explicit contracts, append-only event trace, deterministic test harnesses. Not autonomous production deployment.

### Current Implementation vs Future Aspirations
Implemented now:
- Bounded revise-loop runtime.
- Role validation + retry wrapper.
- Append-only JSONL event trace.
- Prompt-driven and deterministic example role callables.
- Ollama model boundary and CLI wiring.
- File-based `GameDefinition` loading.

Not implemented now:
- Dynamic role/tool ecosystems.
- Multi-agent orchestration runtime.
- Persistent run-id counters.
- Artifact-runtime integration in game loop.
- Decision parsing from strict structured model outputs.

## 2. Current System Capabilities

### Schemas (`src/baps/schemas.py`)
Purpose:
- Canonical data contracts for runtime, events, artifacts, and reporting.

Important classes/functions:
- Core: `Target`, `GameContract`, `Move`, `Finding`, `Decision`.
- Runtime state: `GameRound`, `GameState`, `GameRecord`.
- Reporting: `RoundSummary`, `GameResult`.
- Artifacts: `Artifact`, `ArtifactVersion`, `ArtifactChange`, `ArtifactAdapterResult`.
- Trace: `Event`.

Current limitations:
- Most semantic policy rules are in runtime/roles, not deeply encoded in schemas.
- Timestamp fields in `GameRecord` are strings, not datetime-typed.

Relationships:
- Used across runtime, blackboard, artifacts, demos, tests.

### Blackboard (`src/baps/blackboard.py`)
Purpose:
- Append-only event persistence in JSONL.

Important classes/functions:
- `Blackboard.append(event)`
- `Blackboard.read_all()`
- `Blackboard.query(event_type)`

Current limitations:
- No locking/concurrency coordination.
- No indexes/compaction/rotation.

Relationships:
- Runtime writes events. Tests and CLI validation read them.

### Artifacts (`src/baps/artifacts.py`)
Purpose:
- Adapter boundary for artifact lifecycle operations.

Important classes/functions:
- `ArtifactAdapter` base contract.
- `ArtifactHandler` type-based delegation.
- `DocumentArtifactAdapter` implementation:
  - `create`
  - `snapshot`
  - `propose_change`
  - `apply_change`
  - `rollback`

Current limitations:
- Only `artifact.type == "document"` implemented.
- No merge/conflict resolution or diff application engine; `apply_change` copies `proposed.md` into `current/main.md`.

Relationships:
- Standalone subsystem currently; runtime does not call artifact handlers.

### Runtime (`src/baps/runtime.py`)
Purpose:
- Execute a bounded game run with event emission.

Important classes/functions:
- `RuntimeEngine.run_game(...)`
- `generate_run_id()`
- `build_game_result(...)`

Current limitations:
- Single Blue/Red/Referee sequence per round; no parallel branches.
- No persistence for run counters/engine state.
- No direct artifact mutation orchestration.

Relationships:
- Uses `Blackboard`, `RoleInvocationGuard`, and schema models.

### Roles (`src/baps/roles.py`, `src/baps/example_roles.py`)
Purpose:
- Guarded role invocation and example role implementations.

Important classes/functions:
- `RoleInvocationGuard.invoke(...)`
- `RoleInvocationError`
- Deterministic roles: `blue_role`, `red_role`, `referee_role`
- Prompt-driven factories:
  - `make_prompt_blue_role`
  - `make_prompt_red_role`
  - `make_prompt_referee_role`

Current limitations:
- Prompt-driven parsing is intentionally lightweight (Red materiality text protocol).
- No strict structured LLM parsing contract yet.

Relationships:
- Runtime accepts any callable matching expected signatures.

### Prompt Rendering (`src/baps/prompts.py`, `src/baps/prompt_assembly.py`)
Purpose:
- Assemble sectioned prompts and render with context.

Important classes/functions:
- `PromptSection`, `PromptSpec`, `assemble_prompt(...)`
- `PromptRenderer.render(...)`, `render_prompt(...)`

Current limitations:
- Uses `str.format`; no template file loader or advanced templating.

Relationships:
- Used by prompt-driven role factories and `play_game` prompt composition.

### Model Abstraction (`src/baps/models.py`)
Purpose:
- Model-client boundary independent of runtime internals.

Important classes/functions:
- `ModelClient` base.
- `FakeModelClient` deterministic test client.
- `OllamaClient` (`POST /api/generate`, non-streaming).

Current limitations:
- No streaming/chat/tools endpoints.
- No retry/backoff or circuit behavior.

Relationships:
- Consumed by prompt-driven role factories and CLI demos.

### Ollama Integration
Purpose:
- Optional real model execution via `OllamaClient`.

Current state:
- Used in `ollama_adversarial_demo.py` and `play_game.py`.
- Configured by env vars or CLI args.

### Deterministic Testing
Purpose:
- Keep CI/local tests stable and network-free.

Current state:
- Uses fake roles and `FakeModelClient`.
- Uses monkeypatch to replace Ollama client in CLI tests.

### Demo Game Execution
Entry points (`pyproject.toml` scripts):
- `baps-demo`
- `baps-adversarial-demo`
- `baps-ollama-adversarial-demo`
- `baps-play-game`

## 3. Repository Structure

```text
src/baps/
  __init__.py
  schemas.py
  blackboard.py
  artifacts.py
  roles.py
  runtime.py
  prompt_assembly.py
  prompts.py
  models.py
  game_types.py
  example_roles.py
  demo.py
  adversarial_demo.py
  ollama_adversarial_demo.py
  play_game.py
examples/
  game_definitions/
    documentation_refinement.json
tests/
  test_*.py
docs/
  ARCHITECTURE.md
  TODO-v1.md
  TODO-v2.md
  TODO-v3.md
```

Module boundaries:
- `schemas.py`: contracts only, no I/O.
- `blackboard.py`: JSONL append/query, no orchestration logic.
- `artifacts.py`: filesystem artifact lifecycle only.
- `roles.py`: invocation retry/validation policy.
- `runtime.py`: game loop + events + summary projection.
- `game_types.py`: game-definition data and loading.
- `example_roles.py`: deterministic and prompt-driven role factories.
- `play_game.py`: configurable CLI wiring.

## 4. Core Runtime Flow

Sequence for `RuntimeEngine.run_game(contract, blue_role, red_role, referee_role)`:
1. Generate `run_id` via UTC timestamp + short UUID:
   - format: `run-YYYYMMDD-HHMMSS-xxxxxxxx`.
2. Append `game_started` event with round marker `r0001`.
3. Initialize loop at round 1; continue while `current_round <= contract.max_rounds`.
4. Invoke Blue through `RoleInvocationGuard`:
   - expected output model: `Move`
   - semantic checks: `game_id` matches contract, role is `"blue"`.
   - if later round and Blue callable supports second arg, pass revision context from prior round.
5. Append `blue_move_recorded` event.
6. Invoke Red through guard:
   - expected model: `Finding`
   - semantic check: `finding.game_id` matches contract.
7. Append `red_finding_recorded` event.
8. Invoke Referee through guard:
   - expected model: `Decision`
   - semantic check: `decision.game_id` matches contract.
9. Append `referee_decision_recorded` event.
10. Store `GameRound(round_number, moves=[...], findings=[...], decision=...)`.
11. Build revision context from the round:
   - previous blue summary
   - previous red claim
   - previous referee rationale
12. Stop conditions:
   - decision `accept` or `reject`: stop immediately.
   - decision `revise` and rounds remain: next round.
   - decision `revise` at max budget: stop.
13. Build `GameState` and append `game_completed` event.
14. Return `GameState`.

Prompt/model path integration:
- Runtime itself does not render prompts or call model APIs.
- Prompt rendering/model calls happen inside injected role callables.

Runtime persistence:
- Append-only events in blackboard JSONL.
- In-memory `GameState` returned to caller.

Artifact interaction:
- Currently none in runtime loop. Artifact system remains separate.

## 5. Schema Documentation

### `Target`
- Fields: `kind`, `ref`.
- Invariant: `kind` non-empty.
- Use: target descriptor in `GameContract`.

### `GameContract`
- Fields: `id`, `subject`, `goal`, `target`, `active_roles`, `max_rounds`, `scope_allowed`, `scope_forbidden`.
- Invariants:
  - `id/subject/goal` non-empty.
  - `active_roles` non-empty.
  - `max_rounds >= 1`.
- Why: explicit runtime input contract and future policy scope container.

### `Move`
- Fields: `game_id`, `role`, `summary`, `payload`.
- Invariants: required strings non-empty.
- Why: Blue output envelope.

### `Finding`
- Fields: `game_id`, `severity`, `confidence`, `claim`, `evidence`, `payload`, `block_integration`.
- Invariants: required strings non-empty.
- Why: Red critique container, includes semantic flags (`block_integration`, payload materiality).

### `Decision`
- Fields: `game_id`, `decision`, `rationale`.
- Invariants: required strings non-empty.
- Why: referee output with structured decision and textual rationale.

### `GameRecord`
- Fields: `game_id`, `contract`, `status`, `created_at`, `updated_at`, `metadata`.
- Invariants:
  - required strings non-empty.
  - `status` in `{pending, running, completed, failed}`.
- Why: schema for external lifecycle tracking (not yet persisted by runtime).

### `GameRound`
- Fields: `round_number`, `moves`, `findings`, `decision`.
- Invariants: `round_number >= 1`.
- Why: per-round state aggregation.

### `GameState`
- Fields: `game_id`, `run_id`, `current_round`, `rounds`, `final_decision`.
- Invariants:
  - `game_id/run_id` non-empty.
  - `current_round >= 1`.
- Why: runtime return model and terminal game state snapshot.

### `RoundSummary`
- Fields: `round_number`, `blue_summary`, `red_claim`, `referee_decision`, `referee_rationale`.
- Invariants: round >= 1, required strings non-empty.
- Why: compact reporting projection for CLI/higher-level summaries.

### `GameResult`
- Fields: `game_id`, `run_id`, `rounds_played`, `max_rounds`, `final_decision`, `terminal_reason`, `final_blue_summary`, `final_red_claim`, `trace_event_ids`, `round_summaries`.
- Invariants:
  - required strings non-empty.
  - `rounds_played/max_rounds >= 1`.
- Why: post-run summary object independent from runtime execution semantics.

### Artifact models
- `Artifact`: identity/type/current_version/metadata.
- `ArtifactVersion`: snapshot descriptor (`artifact_id`, `version_id`, `path`).
- `ArtifactChange`: proposed change descriptor (`change_id`, `base_version`, `description`, `diff`).
- `ArtifactAdapterResult`: normalized adapter operation result envelope.
- Why: stable adapter boundary for filesystem-backed artifacts.

### `Event`
- Fields: `id`, `type`, `payload`.
- Invariants: `id/type` non-empty.
- Why: append-only runtime trace unit.

## 6. Blackboard/Event System

Append-only philosophy:
- `append()` always writes one newline-delimited JSON object with file mode `"a"`.
- No mutation/rewrite of previous entries.

Persistence behavior:
- Path type is `Path`.
- Parent directories auto-created on append.
- Serialization uses `model_dump(mode="json")`.

Read/query behavior:
- `read_all()` returns `[]` when file is absent.
- Every line is parsed as JSON and validated back into `Event`.
- Invalid JSON or invalid schema raises exceptions from parsing/validation.
- `query(event_type)` filters `read_all()` and rejects blank `event_type`.

Current event lifecycle from runtime:
- `game_started`
- `blue_move_recorded`
- `red_finding_recorded`
- `referee_decision_recorded`
- `game_completed`

Event ID shape (current runtime):
- start: `{game_id}:{run_id}:r0001:game_started`
- per-round: `{game_id}:{run_id}:r{round:04d}:<event_type>`
- completion: `{game_id}:{run_id}:game_completed`

Intended future role (from code direction):
- system trace/audit log for runtime executions with replay/debug value.

## 7. Artifact System

Adapter model:
- `ArtifactAdapter` defines method boundary.
- `ArtifactHandler` dispatches by `artifact.type` and raises on missing adapter.

Document adapter storage layout:
```text
<root>/<artifact_id>/
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

Lifecycle operations:
- `create(artifact)`:
  - validates `artifact.type == "document"`.
  - creates directories and empty `current/main.md`.
  - writes serialized `metadata.json`.
  - raises `FileExistsError` if artifact dir already exists.
- `snapshot(artifact)`:
  - requires artifact/current dirs.
  - assigns next `vNNN` from directory scan.
  - copies `current` to version dir using `shutil.copytree`.
- `propose_change(artifact, description, new_content)`:
  - requires current `main.md`.
  - creates next `cNNN` change dir.
  - computes unified diff (`difflib.unified_diff`).
  - uses `artifact.current_version` or `"unversioned"` as base version.
  - writes `proposed.md` and `change.json`.
- `apply_change(artifact, change_id)`:
  - reads change `proposed.md`.
  - overwrites `current/main.md`.
  - snapshots and returns new `ArtifactVersion`.
- `rollback(artifact, version_id)`:
  - replaces `current/` by copying from `versions/version_id`.

Assumptions/constraints:
- File operations are local and synchronous.
- No concurrency control.
- No cross-artifact transactional semantics.

## 8. Runtime Engine

Runtime responsibilities:
- Manage one bounded execution run.
- Enforce semantic role outputs.
- Append execution events.
- Build terminal `GameState`.

Role invocation guard integration:
- All role calls go through `RoleInvocationGuard.invoke(...)`.
- Guard performs:
  - output model validation (`model_validate`).
  - optional semantic validator callback.
  - bounded retries on `ValidationError`/`ValueError`.
  - raises `RoleInvocationError` on exhausted attempts.

Retry behavior:
- default `max_attempts=2`.
- configurable by injecting custom `RoleInvocationGuard` into `RuntimeEngine`.

Game execution model:
- Round-based loop.
- Continue only on `revise` and remaining round budget.
- `accept/reject` are terminal.

Deterministic execution approach:
- Runtime logic itself is deterministic given role outputs.
- Non-determinism only from injected role callables and run-id UUID/timestamp generation.

## 9. Roles and Prompt System

Deterministic example roles:
- `blue_role`: returns fixed move summary and goal payload.
- `red_role`: returns fixed low/high confidence finding referencing blue summary.
- `referee_role`: returns fixed `accept` rationale referencing blue/red content.

Prompt-driven role factories:
- `make_prompt_blue_role(...)`:
  - renders prompt from contract + optional revision context.
  - returns `Move(summary=model.generate(prompt))`.
- `make_prompt_red_role(...)`:
  - renders prompt from contract + blue move.
  - parses generated text for:
    - `MATERIAL: yes|no`
    - `CLAIM: ...`
  - falls back to configured defaults/full text on parse gaps.
- `make_prompt_referee_role(...)`:
  - computes structured decision deterministically:
    - `reject` if `block_integration=True`
    - else `revise` if `finding.payload["material"]` truthy (default True)
    - else `accept`
  - prompts model only for rationale supporting fixed decision.

PromptRenderer:
- `PromptRenderer(template)` validates non-empty template.
- `.render(context)` uses `str.format(**context)`.
- raises `KeyError` for missing keys, `ValueError` for blank rendered output.

FakeModelClient:
- deterministic list-based responses.
- captures prompts in call order.
- useful for stable tests and prompt assertions.

OllamaClient:
- stdlib `urllib` POST to `{base_url}/api/generate`.
- request body: `{model, prompt, stream:false}`.
- returns `response` field.

Role execution flow in practice:
- CLI/demo builds role callables.
- Runtime invokes those callables via guard.
- Prompt/model behavior is encapsulated inside role callables.

Current limitations:
- No tool invocation protocol.
- No plugin registry in loop.
- No true multi-agent orchestration beyond injected callables.
- No strict output parsing schema from model-generated text.

## 10. Testing Strategy

Current philosophy:
- Validate contracts and boundaries first.
- Keep tests deterministic and isolated.
- Test each subsystem directly plus CLI integration paths.

Deterministic approach:
- fake model client responses are fixed.
- monkeypatch replaces `OllamaClient` in CLI tests.
- no external network dependency in tests.

Coverage areas:
- Schema validation and mutable default isolation.
- Blackboard append/read/query and invalid JSON handling.
- Artifact lifecycle operations and filesystem behavior.
- Runtime loop semantics (accept/reject/revise, max rounds, event IDs, run IDs).
- Role guard retries/semantic checks.
- Prompt assembly/render behavior.
- Game definition built-in and file loading.
- Demo and CLI output fields.

Why deterministic tests matter here:
- The architecture depends on strict contracts across role outputs and runtime orchestration.
- Non-deterministic tests would obscure regressions in decision flow, trace IDs, and prompt composition.

## 11. Architectural Invariants (Enforced by Code)

- Event trace is append-only per file (`Blackboard.append` uses append mode).
- Runtime emits validated schema objects for all role outputs (via guard + Pydantic).
- Semantic consistency is enforced at runtime boundaries:
  - role/game_id matching
  - Blue role identity (`role == "blue"`).
- Game loop remains bounded by `max_rounds`.
- `GameState` always includes non-empty `run_id` and `game_id`.
- Prompt sections and templates reject empty values in assembly/rendering layers.
- File-loaded `GameDefinition` must validate as schema before use.

## 12. Current Architectural Direction

Implemented direction:
- Bounded adversarial game execution (`accept/revise/reject`).
- Explicit game-definition data model (`GameDefinition`) and JSON-loading path.
- Configurable single-game CLI with shared context inputs.
- Prompt-driven role behavior with deterministic decision policy.

Conceptual/future direction (inferred from boundaries, not implemented):
- Additional built-in game types beyond documentation refinement.
- Externally generated game definitions (e.g., sponsor-generated) consumed as data.
- Deeper tool integration for evidence gathering.
- Stronger referee convergence and richer multi-round policy controls.

## 13. Current Limitations

- Runtime does not orchestrate artifact lifecycle operations.
- Prompt parsing for Red materiality is line-based text protocol, not robust structured extraction.
- Decision reasoning quality depends on model text quality; only structured decision is deterministic.
- No durable run metadata store beyond blackboard events.
- Blackboard has no indexing/compaction/locking.
- CLI currently uses fixed `contract.id` (`play-game-001`) for `baps-play-game`.
- No authorization/security boundaries around local file context loading.

## 14. Suggested Next Milestones (Additive)

1. Add additional built-in `GameDefinition` types (code hardening, discrepancy investigation) via `game_types.py` only.
2. Introduce stricter structured role output parsing (without changing runtime interface), especially for Red materiality/claim.
3. Add optional runtime hook to project each completed round into a normalized artifact/change record.
4. Add event filtering helpers for per-run replay and compact trace views.
5. Add explicit referee convergence metrics in `GameResult` (e.g., materiality trend across rounds).
6. Add controlled tool-request boundary as role-callable helper (still injected, not runtime-owned).

## 15. Developer Workflow

Environment and tests:
```bash
uv sync
uv run pytest
```

Common runnable demos:
```bash
uv run baps-demo
uv run baps-adversarial-demo
uv run baps-ollama-adversarial-demo
uv run baps-play-game --subject "..." --goal "..." --target-kind "..."
```

Additive development pattern used in repo:
- Add schema/contract first.
- Add thin implementation boundary.
- Add focused tests for success/failure/invariants.
- Keep existing public APIs stable unless extending with optional params.

Expected contribution style:
- Preserve current terms (`GameContract`, `Move`, `Finding`, `Decision`, `GameDefinition`, etc.).
- Prefer explicit behavior and small cohesive modules.
- Keep runtime side effects visible through blackboard events.

## 16. Glossary

- Game: one execution of Blue/Red/Referee rounds under a `GameContract`.
- Run: a concrete execution instance of a game with unique `run_id`.
- GameContract: validated input envelope defining target/goal/role set/round budget.
- Blue role: callable that proposes a `Move`.
- Red role: callable that returns a `Finding` critiquing Blue’s move.
- Referee role: callable that returns a `Decision`.
- Move: Blue output model (`summary`, `payload`).
- Finding: Red output model (`claim`, severity/confidence, evidence, materiality/block flags).
- Decision: referee output model (`decision`, `rationale`).
- GameState: complete runtime output including all rounds and final decision.
- GameResult: compact summary projection from `GameState` + contract.
- Blackboard: append-only JSONL event store for runtime traces.
- Event: one typed trace record with identifier and payload.
- Artifact: typed object managed by artifact adapters.
- Snapshot: versioned copy of artifact `current/` state.
- Change: proposed artifact mutation with diff + proposed content.
- PromptSection/PromptSpec: section-based prompt composition structures.
- PromptRenderer: `str.format` renderer with non-empty checks.
- ModelClient: abstract model text generation boundary.
- FakeModelClient: deterministic test model client.
- OllamaClient: concrete local model client using Ollama `/api/generate`.
- GameDefinition: data model describing game-level prompt semantics (`prompt_sections`).
- Built-in game type: named resolver path (currently `documentation-refinement`).

## Observations and Ambiguities

- `run_play_game` accepts both `game_type` and `game_definition`; when both are given, explicit `game_definition` wins. This is consistent in code but not fully surfaced in top-level CLI output semantics.
- CLI output always prints `game_type=<arg value>`, even when a file-based definition overrides builtin lookup; this may display a non-resolved/irrelevant game type label.
- `GameRecord` exists but is not currently produced/persisted by runtime.
- Artifact subsystem is feature-complete relative to current tests but remains disconnected from runtime loop orchestration.
