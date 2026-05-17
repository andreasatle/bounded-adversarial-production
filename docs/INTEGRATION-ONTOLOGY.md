# INTEGRATION-ONTOLOGY

## Purpose
This document audits integration ontology across the current `baps` implementation and docs.

Scope:

- documentation only,
- no code changes,
- no renames,
- no migrations,
- no behavior changes.

Sources inspected:

- `src/baps/runtime_integration.py`
- `src/baps/integration.py`
- `src/baps/game_service.py`
- `src/baps/loop.py`
- `src/baps/state_service.py`
- `docs/ARCHITECTURE.md`
- `docs/SYSTEM.md`
- `docs/NORTH-STAR.md`
- `docs/ONTOLOGY-MAPPING.md`

## 1. Integration Lifecycle Stages

Canonical lifecycle requested:

```text
runtime outcome
  ->
integration evidence
  ->
IntegrationDecision
  ->
StateUpdateProposal
  ->
State mutation
```

### Stage A: Runtime outcome
Current producers:

- Runtime path: `GameService.play()` produces `schemas.GameResponse` from `RuntimeEngine.run_game(...)`.
- State-centric loop path: `run_loop(...)` produces `LoopResult` with `GameExecutionResult`.

### Stage B: Integration evidence
Current evidence inputs:

- Runtime path (`runtime_integration.py`): evidence is embedded in `GameResponse` fields and copied into `schemas.IntegrationDecision.metadata`.
  - examples: `terminal_outcome`, `integration_recommendation`, `final_decision`.
- State-centric path (`integration.py`): evidence is `GameExecutionResult` (`summary`, `state_delta`, `risks`) transformed into `StateChange`.

### Stage C: IntegrationDecision
Two active decision models:

- Runtime compatibility decision: `schemas.IntegrationDecision` (via `runtime_integration.py`).
- State-centric decision: `integration.IntegrationDecision` (via `integration.py`).

### Stage D: StateUpdateProposal
Current bridge:

- `derive_state_update_from_decision(...)` in `integration.py`.
- `accepted=False` => `None`.
- `accepted=True` => `StateUpdateProposal` with deterministic ID, target from `state_change.id`, summary from `state_change.summary`, and payload fields:
  - `applied_delta`
  - `execution_result_id`
  - `integration_decision_id`

Optional fingerprinted bridge:

- `derive_state_update_from_decision_for_state(state, decision)` sets `base_state_fingerprint=fingerprint_state(state)`.

### Stage E: State mutation
Current mutator boundary:

- `StateService.apply_update(...)` in `state_service.py`.
- flow:
  1. load current state,
  2. validate artifacts,
  3. validate `base_state_fingerprint` (if present),
  4. apply `apply_state_update(...)`,
  5. validate updated state,
  6. save.

Mutation remains explicit:

- not called from `run_loop(...)` implicitly,
- not called from runtime `game_service.py` path implicitly.

## 2. Model Comparison: `schemas.IntegrationDecision` vs `integration.IntegrationDecision`

### 2.1 Structural intent

- `schemas.IntegrationDecision` is runtime/event-governance oriented.
- `integration.IntegrationDecision` is state-centric decision oriented and designed to bridge into `StateUpdateProposal`.

### 2.2 Field-by-field classification

| Field / Concept | `schemas.IntegrationDecision` | `integration.IntegrationDecision` | Classification |
|---|---|---|---|
| `id` | yes | yes | same meaning (decision identity) |
| `run_id` | yes | no | specialization in runtime model |
| `outcome` (accepted/deferred/rejected style) | yes | no | specialization in runtime model |
| `target_kind` | yes | no | specialization in runtime model |
| `summary` | yes | no (summary is nested in `state_change.summary`) | adapter/specialization |
| `rationale` | yes | yes | same meaning |
| `metadata` | yes | no | specialization in runtime model |
| `accepted` (bool) | no | yes | specialization in state-centric model |
| `satisfaction` | no | yes | specialization in state-centric model |
| `state_change` | no | yes | specialization in state-centric model |
| `state_change.execution_result_id` | no | yes | specialization in state-centric model |
| `state_change.applied_delta` | no | yes | specialization in state-centric model |
| `state_change.materiality` | no | yes | specialization in state-centric model |
| `state_change.risks` | no | yes | specialization in state-centric model |

### 2.3 Duplicate vs obsolete assessment

- Duplicate: concept-level duplication exists only at decision identity/rationale layer (`id`, `rationale`).
- Obsolete: neither model is obsolete in current code; each is active in different lifecycle paths.
- Adapter need: a compatibility adapter is needed to map runtime integration outcomes into state-centric decision/update semantics if unification is desired.

## 3. Authority Clarifications

### Authoritative integration decision
Current authoritative decision depends on lifecycle path:

- Runtime path authority: `schemas.IntegrationDecision` appended by `runtime_integration.py` and used for event governance.
- State mutation authority: `integration.IntegrationDecision` is authoritative for deriving `StateUpdateProposal` in the state-centric bridge.

Operationally, for **state mutation**, `integration.IntegrationDecision` is the authoritative decision type.

### Runtime compatibility layer
`src/baps/runtime_integration.py` currently acts as the runtime compatibility layer:

- consumes `GameResponse`,
- applies deterministic integration policy,
- emits/appends `schemas.IntegrationDecision` for blackboard lifecycle.

### Future merge target
Merge target is a canonical integration ontology with explicit compatibility mapping between:

- runtime/event decision records,
- state-centric decision records used for update derivation.

No such unification layer is implemented yet.

## 4. Concept Ownership Table

| Concept | Owner Module | Authority Class | Lifecycle Stage | Merge Target |
|---|---|---|---|---|
| Runtime outcome (`GameResponse`) | `src/baps/game_service.py` + `src/baps/runtime.py` | execution-authoritative (ephemeral) | runtime outcome | map into canonical integration evidence model |
| Runtime integration policy | `src/baps/runtime_integration.py` | process-authoritative (event governance) | integration evidence -> decision | unify with state-centric decision semantics |
| Runtime integration decision (`schemas.IntegrationDecision`) | `src/baps/schemas.py` / `src/baps/runtime_integration.py` | process-authoritative | IntegrationDecision | adapter to canonical integration decision |
| State-centric execution result (`GameExecutionResult`) | `src/baps/game_executor.py` | execution-authoritative (ephemeral) | runtime outcome / evidence | map into canonical evidence model |
| State-centric integration decision (`integration.IntegrationDecision`) | `src/baps/integration.py` | state-mutation-authoritative | IntegrationDecision | candidate canonical mutation decision model |
| State change semantics (`StateChange`, `materiality`) | `src/baps/integration.py` | state-mutation-authoritative | integration evidence | align with runtime evidence vocabulary |
| Decision satisfaction semantics (`IntegrationSatisfaction`) | `src/baps/integration.py` | state-mutation-authoritative | IntegrationDecision | unify with runtime outcome vocabulary |
| Decision -> update derivation | `src/baps/integration.py` | bridge authority | IntegrationDecision -> StateUpdateProposal | common adapter API for both decision types |
| Fingerprinted derivation | `src/baps/integration.py` + `src/baps/state.py` | bridge authority | IntegrationDecision -> StateUpdateProposal | integrate with runtime-derived proposals |
| Base-state validation check | `src/baps/state.py` (`validate_update_base_state`) | state-authoritative | pre-mutation gate | preserve as canonical precondition in unified flow |
| State mutation orchestrator | `src/baps/state_service.py` | state-authoritative | State mutation | consume canonical update proposals |
| Loop explicit application bridge | `src/baps/loop.py` (`apply_loop_decision_update`) | bridge authority | optional mutation trigger | policy-controlled unified lifecycle invocation |
| Blackboard decision recording | `src/baps/runtime_integration.py` and `src/baps/loop.py` | process-authoritative | post-decision recording | normalize event schema and decision payload shape |

## 5. Observations

1. Integration ontology is intentionally split between runtime governance and state mutation bridges.
2. `game_service.py` currently terminates at runtime-path integration append; it does not invoke state update derivation or mutation.
3. `run_loop(...)` intentionally avoids implicit blackboard writes and implicit state mutation; both remain explicit helper calls.
4. Independence rules are already encoded in state-centric semantics:
   - `accepted` is independent from `satisfaction`,
   - `materiality` is independent from both.
5. Documentation reference note: requested path `docs/NORTHSTAR.md` corresponds to the existing file `docs/NORTH-STAR.md` in this repository.
