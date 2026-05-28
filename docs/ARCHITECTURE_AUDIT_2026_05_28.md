# Architecture Audit

## Executive Summary

The repository is in a meaningful hardening phase and has improved semantic structure (adapter boundaries, recursive decomposition, explicit stop reasons). The most urgent issues are now around authority semantics and contract coherence: some runtime paths currently blur boundaries the architecture explicitly claims to enforce.

## Most Urgent Findings

### 1) Referee `revise` currently has effective integration authority

**Why it matters**

The system defines Referee as game-local adjudication and Integrator as final state authority. Right now, that boundary is blurred: a non-accepted candidate can still become the integrated delta.

**Evidence from current code structure**

- `apply_referee_decision_to_runtime` promotes both `accept` and `revise` to `current_best_delta` ([state.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/state/state.py#L409)).
- `play_game` returns `runtime.current_best_delta` regardless of whether final disposition was `accept` or only `revise` fallback ([game.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/game/engine.py#L802), [game.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/game/engine.py#L818)).
- `_solve_gap` applies any non-`None` delta directly to state (`state_service.apply_delta`) ([orchestration.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/core/orchestration.py#L166), [orchestration.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/core/orchestration.py#L171)).
- Prompt text explicitly says Referee does not decide final integration ([prompts.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/core/prompts.py#L312)).

**Risk if ignored**

Authority semantics become non-auditable: logs and prompts say one thing, mutation behavior does another. This will make future correctness bugs look like model quality issues instead of boundary bugs.

**Recommended direction (NOT implementation details)**

Make runtime integration eligibility explicit and first-class (separate from candidate quality progression). Preserve `revise` as search guidance, not implicit integration authority.

### 2) Integration contract is split between two mutation pathways, with runtime using only one

**Why it matters**

The codebase carries both `DeltaState -> apply_delta` and `DeltaState -> StateUpdateProposal -> apply_update` as “canonical” integration narratives. Only one is operational in orchestration, while the other remains heavily modeled and tested.

**Evidence from current code structure**

- Runtime path applies delta directly (`StateService.apply_delta`) in orchestration ([orchestration.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/core/orchestration.py#L171)).
- Adapter `delta_to_state_update` mapping exists across adapters and shared helper `_derive_state_update_from_delta` still exists ([game.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/game/engine.py#L150), [document_adapter.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/adapters/document_adapter.py#L249), [coding_adapter.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/adapters/coding_adapter.py#L541)).
- Test corpus still has strong coverage for proposal-based mutation semantics (`tests/test_state_delta.py`, `tests/test_state_service.py`, sections of `tests/test_integration.py`).
- Architecture doc spine still describes `DeltaState -> StateUpdateProposal -> StateService` as canonical ([ARCHITECTURE.md](/Users/andreasatle/Projects/bounded-adversarial-production/docs/ARCHITECTURE.md#L17)).

**Risk if ignored**

Long-term drift: contributors will harden both paths differently, creating semantic skew and duplicated bug-fix surfaces. Auditability degrades because “official path” depends on where you read.

**Recommended direction (NOT implementation details)**

Declare one integration contract as authoritative in runtime semantics and demote the other to either compatibility or explicit non-runtime tooling scope.

### 3) `play_game` is becoming an orchestration compression point

**Why it matters**

`play_game` now coordinates role client resolution, research loops, tool-use capture, prompt rendering, parse/retry/fallback handling, candidate verification, feedback shaping, and blackboard event assembly. This density raises change coupling and boundary regression risk.

**Evidence from current code structure**

- Single function spans Blue/Red/Referee lifecycle, research sessions, tool context enforcement, fallback orchestration, candidate verification, and event recording ([game.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/game/engine.py#L506)).
- Role-specific behavior is partly adapter-owned and partly core-owned (e.g., supplements in adapters, but enforcement text and session wiring in core prompts flow).
- Attempt record schema and blackboard write logic are also embedded in the same function ([game.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/game/engine.py#L587), [game.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/game/engine.py#L809)).

**Risk if ignored**

Future local hardening patches will continue to accumulate in one high-risk function, making authority and retry behavior harder to reason about and increasing accidental behavioral regressions.

**Recommended direction (NOT implementation details)**

Stabilize `play_game` around explicit phase boundaries with narrow contracts between phases (candidate generation, adversarial evaluation, adjudication, integration eligibility, and telemetry emission).

### 4) Prompt contracts and parser behavior are intentionally asymmetric, but the asymmetry is now semantically significant

**Why it matters**

Prompts demand strict JSON-only/exact shapes; parsers are permissive (strip keys, rescue wrappers, truncate/repair decompose outputs, fallback escalation). This is pragmatic, but now affects boundedness semantics (not only robustness).

**Evidence from current code structure**

- Prompts enforce “Return only JSON”, “No extra fields”, and exact shape narratives ([prompts.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/core/prompts.py#L112), [prompts.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/core/prompts.py#L116)).
- `parse_model_output` strips unexpected keys and proceeds ([model_output.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/models/model_output.py#L142)).
- CreateGame parser silently filters empty sub-gaps and truncates over-limit lists instead of hard rejection ([parsers.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/core/parsers.py#L109), [parsers.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/core/parsers.py#L132)).
- Tests validate this permissive behavior as expected behavior (`tests/test_parsers.py`).

**Risk if ignored**

Boundedness and audit semantics become dependent on hidden parser correction behavior rather than explicit role contracts, making it hard to distinguish “model complied” vs “runtime salvaged.”

**Recommended direction (NOT implementation details)**

Keep permissive recovery, but elevate parse-recovery outcomes to first-class semantic signals in the orchestration decision layer (not only low-level parsing behavior).

### 5) StateView/projection architecture has two parallel representations with partial duplication

**Why it matters**

There is a generic NorthStar projection system and adapter-specific StateView builders with duplicated delimiter/content conventions. They currently coexist without a single authoritative projection contract.

**Evidence from current code structure**

- Generic projection models and renderer exist in `northstar_projection.py` with projection policies and structured items ([northstar_projection.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/northstar/northstar_projection.py#L24)).
- Adapters build their own textual StateViews directly, including duplicated framing logic (`STATE_VIEW_START/END`, section/file rendering) ([document_adapter.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/adapters/document_adapter.py#L54), [coding_adapter.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/adapters/coding_adapter.py#L111)).
- All views are labeled `ProjectionType.NORTH_STAR` even when semantics are role-specific artifact views, reducing projection-type meaning ([document_adapter.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/adapters/document_adapter.py#L101), [coding_adapter.py](/Users/andreasatle/Projects/bounded-adversarial-production/src/baps/adapters/coding_adapter.py#L159)).

**Risk if ignored**

Projection semantics will drift adapter-by-adapter; future hardening (sanitization, boundedness, provenance) will be duplicated and inconsistently applied.

**Recommended direction (NOT implementation details)**

Define one explicit projection contract level (schema + semantics) that adapters implement, rather than parallel ad-hoc rendering and generic rendering both evolving.

## Things That Are Actually Going Well

- Recursive decomposition semantics are now explicit and bounded (`max_depth`, `max_sub_gaps`, ordered sub-gap execution), with good stop-reason clarity in orchestration.
- Adapter boundary direction is stronger: project-specific view/prompt/delta/export/verification logic is mostly adapter-owned, reducing core branching by project type.
- LLM output hardening is materially improved: structured parsing with retries/fallback, JSON extraction, size caps, and sanitization before prompt re-embedding.
- Blackboard/event logging has become richer and more useful for audit trails (create-game, play-game attempts, integration, northstar proposal events).
- Tests are broad and intentionally organized by runtime concepts after the recent split, which supports ongoing transition work.

## Things NOT To Do Yet

- Do not introduce another abstraction layer over adapters “for cleanliness” while authority semantics are still in flux.
- Do not collapse Blue/Red/Referee into a generic role pipeline yet; that would hide unresolved role-authority semantics.
- Do not replace permissive parser recovery with strict-fail-only behavior right now; recovery is currently carrying real model variance.
- Do not modularize projection rendering into many micro-components before projection contract authority is decided.

---

Files inspected (representative set):
- `src/baps/game/engine.py`
- `src/baps/core/orchestration.py`
- `src/baps/core/run.py`
- `src/baps/core/prompts.py`
- `src/baps/core/parsers.py`
- `src/baps/models/model_output.py`
- `src/baps/state/state.py`
- `src/baps/state/state_service.py`
- `src/baps/northstar/northstar_projection.py`
- `src/baps/adapters/project_adapter.py`
- `src/baps/adapters/document_adapter.py`
- `src/baps/adapters/coding_adapter.py`
- `tests/test_play_game.py`
- `tests/test_orchestration.py`
- `tests/test_prompts.py`
- `tests/test_parsers.py`
- `tests/test_state_view.py`
- `tests/test_integration.py`
- `docs/ARCHITECTURE.md`

Tests run:
- Not run for this audit (static architectural/code-structure review only).

Remaining uncertainty:
- Low-to-moderate. The main uncertainty is intent around the active transition between `apply_delta` and proposal-based integration semantics; code and docs currently indicate both narratives.


## Added by Chat-GPT

1. Fix integration eligibility semantics
Separate current_best_delta from “eligible for integration.”
revise may preserve candidate progress, but must not imply integration readiness.
Highest priority because Referee/game authority is currently blurred.

2. Clarify the canonical integration path
Decide whether runtime authority is apply_delta or DeltaState -> StateUpdateProposal -> apply_update.
Update code/docs/tests so only one path is canonical.

3. Decompose play_game without behavior changes
Extract narrow internal phases:
build context
run one attempt
apply referee decision
record telemetry
retry loop
Goal: reduce compression, not redesign.

4. Make parser recovery visible in telemetry
Keep permissive recovery.
But record when output was repaired/filtered/truncated/fence-unwrapped.
This protects audit truthfulness.

5. Unify StateView projection contract
Avoid parallel ad-hoc adapter views.
Define what a StateView means and require adapters to implement that contract.