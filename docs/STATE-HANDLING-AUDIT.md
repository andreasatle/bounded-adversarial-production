# STATE-HANDLING-AUDIT

## Scope and method
This report is evidence-based and documentation-only. It summarizes current state handling from inspected code/tests/docs without proposing architectural redesign.

Evidence basis:
- direct code inspection of state, loop, run, integration, projection, and schema modules
- direct test inspection for state/store/service/run behavior
- direct docs inspection for stated authority boundaries

Notation:
- **Evidence:** directly observed in code/tests/docs.
- **Hypothesis:** inference where implementation intent is implied but not explicitly enforced.

---

## 1. Current State definition

### 1.1 What models currently represent State
- **Evidence:** `src/baps/state.py` defines authoritative state models:
  - `StateArtifact(id, kind)`
  - `NorthStar(artifacts: tuple[StateArtifact, ...])`
  - `State(northstar: NorthStar, artifacts: tuple[StateArtifact, ...] = ())`
- **Evidence:** `src/baps/schemas.py::ProjectedState` is a replay/read model for blackboard-derived accepted/discrepancy/game summaries, not the same as `state.py::State`.

### 1.2 Fields in `State`
- **Evidence:** `State` fields are:
  - `northstar`
  - `artifacts`
- **Evidence:** invariants enforced in validators:
  - unique IDs within `northstar.artifacts`
  - unique IDs within `artifacts`
  - no overlap between northstar IDs and ordinary artifact IDs

### 1.3 Changeable project variables
- **Evidence:** mutable project-condition carriers in authoritative state are artifact tuples:
  - `state.northstar.artifacts`
  - `state.artifacts`
- **Evidence:** updates are requested via `StateUpdateProposal(target, payload, summary, optional base_state_fingerprint)`.

### 1.4 Metadata/config/routing-like fields (not core project condition)
- **Evidence:** in `StateUpdateProposal`, these are control/routing/provenance-like:
  - `id`
  - `target`
  - `summary`
  - `base_state_fingerprint`
  - operation metadata inside `payload`
- **Evidence:** in replay model `schemas.ProjectedState`, `metadata` is read-model metadata.

---

## 2. State derivation

### 2.1 How State is created or loaded
- **Evidence:** explicit construction via `State(...)` in tests and helper flows.
- **Evidence:** persistence boundary is `JsonStateStore` (`src/baps/state_store.py`):
  - `load()` reads JSON and validates to `State`
  - `save()` writes `State.model_dump(mode="json")`
- **Evidence:** orchestration boundary is `StateService` (`src/baps/state_service.py`):
  - `load_state()` delegates to store
  - `validate_state()` validates artifacts through registry
  - `apply_update()` loads, validates, fingerprint-checks, applies, validates, saves

### 2.2 Does `baps-run` derive State from config/output
- **Evidence:** `src/baps/run.py` does **not** use `State`, `StateStore`, or `StateService`.
- **Evidence:** `baps-run` derives transient dict-like “state” from request + current markdown content (`_build_view_content`, `_build_input`) and writes directly to output markdown file.

### 2.3 Where generated state lives
- **Evidence:** for `baps-run`, durable output is external file content at `<workspace>/output/report.md`.
- **Evidence:** no authoritative `State` JSON is loaded/saved by `baps-run` today.

---

## 3. StateView / projection

### 3.1 How State is converted into reasoning input
- **Evidence:** state-centric loop path (`src/baps/loop.py::run_state_loop_once`) converts `State` into `NorthStarView` via `_build_northstar_view_from_state` + `render_northstar_view`.
- **Evidence:** `northstar_projection.py` renders deterministic markdown sections from `NorthStarProjectionInput` and wraps them in immutable `StateView` (`NorthStarView` alias).

### 3.2 Which code uses NorthStarView / ProjectedState / StateView
- **Evidence:** `run.py` uses `NorthStarView` as prompt/view input to `run_loop`.
- **Evidence:** `loop.py` uses `NorthStarView` in `run_state_loop_once`.
- **Evidence:** `projections.py` uses `schemas.ProjectedState` for event replay/read model.
- **Evidence:** `StateView` is the concrete immutable view artifact type in `northstar_projection.py`.

### 3.3 Any views accidentally treated as authoritative
- **Evidence:** current `run.py` duplicate detection is done from authoritative document content (`before` file content), not `NorthStarView.content`.
- **Hypothesis:** view/authority separation is currently respected in `baps-run` for duplicate detection; still fragile because `run.py` does not use authoritative `State` at all.

---

## 4. State update

### 4.1 Operations that can currently change State
- **Evidence:** `apply_state_update` supports:
  - `operation == "replace_artifact"`
  - `operation == "add_artifact"`
- **Evidence:** `replace_artifact` enforces matching target ID and kind, preserves ordering and northstar/ordinary separation.
- **Evidence:** `add_artifact` appends one ordinary artifact and relies on `State` validation for duplicate/overlap rejection.

### 4.2 Which function/service applies updates
- **Evidence:** canonical mutation boundary is `StateService.apply_update(proposal)`.
- **Evidence:** lower-level pure transform is `state.apply_state_update(state, proposal)`.

### 4.3 What validates state changes
- **Evidence:** `StateService.apply_update` validates:
  1. current artifacts via registry
  2. base fingerprint (if present) via `validate_update_base_state`
  3. updated artifacts via registry
  4. then persists via store
- **Evidence:** schema validators in `State`, `NorthStar`, `StateArtifact`, `StateUpdateProposal` enforce structural invariants.

### 4.4 Relationship: IntegrationDecision -> StateChange -> StateUpdateProposal -> State
- **Evidence:** `integration.py::derive_state_update_from_decision`:
  - rejected decision -> `None`
  - accepted decision -> `StateUpdateProposal`
- **Evidence:** target artifact ID comes from `decision.state_change.id`; payload includes applied delta and provenance IDs.
- **Evidence:** `derive_state_update_from_decision_for_state` adds `base_state_fingerprint` from current `State`.
- **Evidence:** applying that proposal is explicit via `StateService.apply_update` or helper bridges (`apply_decision_update`, `apply_loop_decision_update`).

---

## 5. Document handling

### 5.1 Are documents represented as State variables, artifacts, or external files
- **Evidence:** authoritative state layer can represent document identity as `StateArtifact(kind="document")`.
- **Evidence:** filesystem artifact lifecycle exists separately in `artifacts.py` (`Artifact`, `DocumentArtifactAdapter`, version/change files).
- **Evidence:** `baps-run` currently uses external output file (`report.md`) directly; it does not map that file into authoritative `State`.

### 5.2 Is there already a tuple/list of document artifacts
- **Evidence:** yes, `State.artifacts` and `NorthStar.artifacts` are tuples of `StateArtifact` and may contain `kind="document"`.

### 5.3 How `DocumentArtifact`/`Artifact`/`StateArtifact` relate
- **Evidence:** `schemas.Artifact` / `artifacts.py` model filesystem artifact lifecycle.
- **Evidence:** `state.py::StateArtifact` models authoritative identity references only.
- **Evidence:** these are parallel concepts with no automatic bridge in `baps-run`.

### 5.4 Which are used by `baps-run` today
- **Evidence:** `baps-run` uses none of `StateArtifact`, `StateService`, `JsonStateStore`, or filesystem `Artifact` adapters.
- **Evidence:** it uses workspace/output markdown file directly plus `run_loop` with local deterministic components.

---

## 6. Product-path status classification

### PRODUCT_PATH (used by `baps-run` now)
- `src/baps/run.py`
- `src/baps/loop.py::run_loop` (proposal -> execution -> integration sequencing)
- `src/baps/northstar_projection.py::NorthStarView/StateView` (as runtime reasoning wrapper in `run.py`)
- `src/baps/integration.py` models indirectly via `IntegrationDecision`/`StateChange` objects produced by local integrator in `run.py`

### SUPPORTING (connected and useful, not directly used by `baps-run`)
- `src/baps/state.py`
- `src/baps/state_store.py`
- `src/baps/state_service.py`
- `src/baps/loop.py::run_state_loop_once` / explicit apply helpers
- tests: `test_state.py`, `test_state_store.py`, `test_state_service.py`

### SHELF (plausible later, not current product path)
- `src/baps/projections.py` (`schemas.ProjectedState` replay/read model)
- runtime-path integration governance (`src/baps/runtime_integration.py`, `schemas.IntegrationDecision`)

### DRIFT_RISK (confusing overlap/duplicate ontology)
- Dual “state-like” surfaces:
  - authoritative `state.py::State`
  - replay `schemas.ProjectedState`
- Dual integration decision families:
  - `integration.py::IntegrationDecision` (state-mutation authority)
  - `schemas.py::IntegrationDecision` (runtime governance/event path)
- `baps-run` uses loop semantics but bypasses authoritative state persistence/mutation surfaces.

---

## 7. Recommended next step (exactly one)
Implement one narrow bridge in `baps-run`: replace direct markdown file append logic with `StateService`-mediated authoritative `State` load/apply/save for a single `document` `StateArtifact` mapped to `<workspace>/output/report.md`, while preserving current external CLI behavior and output fields.

- **Evidence basis for recommendation:** today’s executable command uses `run_loop` but not `StateService`, so authoritative state handling is not yet on the main executable path.
- **Hypothesis:** this is the smallest step that strengthens the current product path without introducing new architecture.
