# Code Quality Audit — PlayGame/CreateGame Transition

## 1. Executive summary
The codebase is in a legitimate mid-transition state: the recent `HEAD` commit adds blackboard auditability for PlayGame attempts, but the transition is only partially integrated into architecture and tests. The core execution spine still works (`ReadUserInput -> CreateState -> CreateGame -> PlayGame -> IntegrateState`), but `run.py` continues to absorb orchestration, role wiring, fallback construction, blackboard persistence, and retry policy concerns in one module/function cluster. The highest-risk quality issues are (a) oversized orchestration surfaces in `run.py`, (b) drift between intended integrate-state abstraction and actual `apply_delta` runtime path, and (c) brittle test strategy dominated by prompt-string lock tests with weaker coverage on new blackboard behaviors introduced in `HEAD`.

## 2. Current product path assessment
The active product path is present and executable:
- `resolve_run_config` / CLI parsing in `src/baps/run.py`
- `create_state(...)`
- `create_game(...)`
- `play_game(...)`
- state mutation via `StateService.apply_delta(...)` inside `_solve_gap(...)`

Assessment:
- The runtime path is coherent and deterministic enough for current use.
- Architectural authority is mostly preserved around `StateService` and typed `DeltaState`.
- However, the “IntegrateState” concept is currently represented by direct `apply_delta` usage (`src/baps/run.py:2275-2277`) rather than a distinct integration boundary object/function. This is workable, but leaves boundary semantics implicit.

## 3. Last-commit impact
`HEAD` (`0968cdd`) introduces:
- New blackboard game event type (`BlackboardEvent.GAME`) in `src/baps/model_output.py:15`.
- New PlayGame telemetry capture and persistence (`_append_game_to_blackboard`, `_summarize_verification_result`, `attempt_records`) in `src/baps/run.py:1594-2027`.
- New `depth` threading from `_solve_gap` into `play_game` (`src/baps/run.py:2269`).
- New committed workspace artifacts and report snapshots under `.baps-workspace-*`.

Impact quality assessment:
- Positive: auditability of per-attempt behavior is improved.
- Risk: integration is partial because tests do not directly assert the new `games.jsonl` schema/write behavior, and commit includes generated workspace artifacts that increase repository noise.

## 4. Code quality findings

### Finding 1
- severity: high
- evidence: `src/baps/run.py:1594-1901` (`play_game`)
- why it matters: `play_game` now combines too many responsibilities: role client resolution, fallback chain wiring, tool-session orchestration, prompt construction glue, model invocation, parse/validation retries, candidate verification, feedback propagation, and blackboard persistence. This increases change risk and makes partial transitions (like current one) harder to harden safely.
- recommended correction: split `play_game` into focused internal units with explicit contracts (for example: role client preparation, one-attempt execution, attempt feedback update, and attempt telemetry persistence) while keeping external behavior unchanged.

### Finding 2
- severity: high
- evidence: `src/baps/run.py:2275-2277`, `src/baps/run.py:1921-1924`, `tests/test_run.py:438`
- why it matters: the runtime spine mutates state through `apply_delta`, while `_derive_state_update_from_delta(...)` exists but is not used in execution, and test naming still suggests “apply_update” while patching `apply_delta`. This creates boundary ambiguity between PlayGame and IntegrateState and can mislead future changes.
- recommended correction: align naming and usage around one explicit integration path in runtime, then align tests with that chosen authority path (including renaming misleading tests).

### Finding 3
- severity: medium
- evidence: `src/baps/run.py:1657-1672`, `src/baps/run.py:437-559` (model client construction family), `src/baps/run.py:1306-1353` (create_game client selection path)
- why it matters: model-client selection logic is distributed across several builders (`_build_model_client`, `_build_planner_model_client`, `_build_role_client`, `_build_client_for_role`, fallback helpers), increasing duplication and precedence complexity. Mid-transition code paths become error-prone when role precedence rules evolve.
- recommended correction: centralize role/backend/model resolution into one canonical resolver and make all builders thin wrappers around it.

### Finding 4
- severity: medium
- evidence: `src/baps/run.py:1967-1980` (`_append_northstar_proposal_to_blackboard`) and `src/baps/run.py:2003-2027` (`_append_game_to_blackboard`)
- why it matters: blackboard event writing logic is duplicated with separate event-shape construction. As event types grow, schema drift and inconsistent sanitization become likely.
- recommended correction: introduce one blackboard append helper with typed event payload models (or a shared serializer), then call it from specific event constructors.

### Finding 5
- severity: medium
- evidence: `src/baps/run.py:1983-1991` and use-site `src/baps/run.py:1862-1877`
- why it matters: verification is stored twice with different fidelity (full details in feedback loop, truncated summaries in persisted blackboard). The truncation cap is hardcoded (`_VERIFICATION_SUMMARY_CAP = 500`) with no test coverage for truncation behavior or schema expectation.
- recommended correction: define and document a stable persisted verification schema (full vs summarized), and add tests specifically for summary truncation and field presence.

### Finding 6
- severity: medium
- evidence: `tests/test_run.py` size and style (9k+ lines; many exact prompt text assertions), e.g. prompt lock checks around early sections and model-output verbiage
- why it matters: tests are brittle against wording changes and can discourage safe prompt quality improvements. This is especially risky during transition work where prompt composition is expected to evolve.
- recommended correction: keep a minimal set of contract-string assertions and shift the rest to semantic assertions (required fields/sections/guardrails, schema shape, decision behavior) to reduce implementation-noise coupling.

### Finding 7
- severity: medium
- evidence: `HEAD` changed blackboard game auditing (`src/baps/run.py:1890-2027`), but no direct tests assert `games.jsonl` write path or `BlackboardEvent.GAME` event content shape
- why it matters: the new feature is exactly the incomplete transition surface; lack of direct tests increases regression risk and weakens confidence in auditability claims.
- recommended correction: add focused tests for `_append_game_to_blackboard` output schema and play_game write conditions (`accepted`/`rejected`/`no_delta` branches).

### Finding 8
- severity: low
- evidence: `HEAD` includes committed generated workspace artifacts: `.baps-workspace-dry-audit/*`, `.baps-workspace-security/*`
- why it matters: generated run outputs in commits introduce noise, increase diff volume, and can obscure genuine architectural changes when auditing history.
- recommended correction: keep generated workspace artifacts out of normal commits (unless explicitly curating fixtures), and document that policy.

## 5. Highest-risk drift points
1. `play_game` complexity growth without corresponding boundary extraction (`src/baps/run.py:1594+`).
2. Integration boundary ambiguity (`apply_delta` runtime path vs dormant proposal derivation helpers and misleading test names).
3. New blackboard auditability feature merged without direct schema/assertion tests.
4. Model-role resolution and fallback precedence spread across many helper functions.

## 6. Concrete next hardening tasks
1. Add targeted tests for `games.jsonl` blackboard events:
   - `accepted`, `rejected`, and `no_delta` final_disposition.
   - `depth`, `context_chain`, and verification summary fields.
   - truncation behavior for stdout/stderr summaries.
2. Decide and document the canonical IntegrateState boundary for runtime:
   - either keep `apply_delta` as explicit authority and remove unused integration indirection,
   - or route runtime through one integrate function and enforce it by test.
3. Break `play_game` into internal, testable units without changing external behavior.
4. Consolidate model-role resolution/fallback precedence into one canonical resolver and remove overlapping pathways.
5. Reduce prompt-lock brittleness in `tests/test_run.py` by converting non-contract string checks to semantic behavior checks.

## 7. Things not to do yet
- Do not rewrite orchestration architecture wholesale.
- Do not introduce speculative new subsystems (event bus, plugin infra, etc.) not required by current pain.
- Do not refactor adapters/state models broadly while the PlayGame/CreateGame hardening is still incomplete.
- Do not expand schema surface area beyond what is needed to stabilize the current transition.
