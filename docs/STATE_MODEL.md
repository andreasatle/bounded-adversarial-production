# STATE_MODEL.md

## Purpose

This document defines the state model for BAPS.

The goal is to make `State` a tight, typed, side-effect-free representation of the current authoritative project condition.

The state model must be stable enough to support:

* projection,
* bounded adversarial evaluation,
* controlled updates,
* artifact-specific adapters,
* and future autonomous project evolution.

This document intentionally does not define planner behavior, game behavior, or blackboard event semantics except where needed to preserve the `State` boundary.

---

## Core Boundary

BAPS separates durable project condition from durable process memory.

```text
State
    = current authoritative project condition

Blackboard
    = durable operational/process memory that is not State
```

A shorter operational rule:

```text
State is what is true now.
Blackboard is what happened, what was attempted, what was considered, and why.
```

This boundary is foundational.

The framework should not confuse:

* the current project,
* with the history of how the current project was reached.

---

## State

`State` represents the current authoritative project condition.

It is the thing the framework attempts to improve over time.

Examples of state content:

* the authoritative `NorthStar`,
* the current document artifacts,
* the current git repository artifacts,
* other current project artifacts introduced later.

`State` is not a log.

`State` is not an execution trace.

`State` is not a reasoning archive.

`State` should be a tight typed value that can be passed around safely.

---

## Blackboard

The blackboard contains durable information that is not the current authoritative project condition.

Examples:

* game history,
* agent traces,
* reasoning traces,
* planner outputs,
* rejected proposals,
* deferred proposals,
* integration decisions,
* reviews,
* behavioral observations,
* operational lessons,
* tool reliability observations,
* provenance,
* audit events.

The blackboard may influence future planning through explicit projection or retrieval.

However, blackboard contents are not automatically part of `State`.

The blackboard is process memory, not the product state.

---

## Required Shape

A `State` has exactly one `NorthStar` and zero or more ordinary state artifacts.

Conceptually:

```text
State
├── northstar: NorthStar
└── artifacts: tuple[StateArtifact, ...]
```

The `NorthStar` is mandatory.

The ordinary artifact collection may be empty.

---

## NorthStar

`NorthStar` is the authoritative directional target for the project.

It is part of `State`, but it is not an ordinary `StateArtifact`.

Conceptually:

```text
NorthStar
└── artifacts: tuple[StateArtifact, ...]
```

The `NorthStar` may be represented by one or more artifacts.

For example:

* a markdown design document,
* a Word document,
* a PDF,
* a structured text file,
* or another document-like artifact type supported by adapters.

The important invariant is not the exact document format.

The important invariant is that the `NorthStar` remains structurally separate from ordinary project artifacts and remains explicitly authoritative.

---

## NorthStar Authority

The `NorthStar` is special because it defines project direction.

Therefore:

* every `State` must have exactly one `NorthStar`,
* the `NorthStar` must not be hidden inside `State.artifacts`,
* ordinary artifacts must not silently override the `NorthStar`,
* updates to the `NorthStar` require explicit human approval before integration.

Autonomous agents may propose `NorthStar` changes.

Autonomous agents may not silently apply `NorthStar` changes.

This preserves human authority over long-term project intent.

---

## StateArtifact

`StateArtifact` is the minimal shared contract for artifacts contained in `State` or `NorthStar`.

Conceptually:

```text
StateArtifact
├── id
└── kind
```

`StateArtifact` should contain only fields shared by all artifacts.

It should not contain artifact-specific behavior.

It should not contain side effects.

It should not contain history.

It should not contain arbitrary open-ended metadata.

---

## Concrete Artifact Types

Concrete artifact types specialize `StateArtifact`.

Initial concrete types should be narrow:

```text
DocumentArtifact
GitRepositoryArtifact
```

Possible future artifact types may include:

* structured knowledge base artifacts,
* dataset artifacts,
* generated asset artifacts,
* test-suite artifacts,
* model or prompt artifacts.

The core `State` model should not need to know the full concrete behavior of every artifact type.

---

## DocumentArtifact

A `DocumentArtifact` represents a current document-like artifact.

It may refer to different document formats, such as:

* markdown,
* plain text,
* docx,
* PDF,
* or other supported formats.

The document format is a representation detail.

The architectural category is still `document`.

Document-specific behavior belongs in a document artifact adapter, not in `State`.

---

## GitRepositoryArtifact

A `GitRepositoryArtifact` represents a current git-backed project artifact.

It may refer to:

* a repository path,
* a branch,
* a commit,
* or another current repository reference.

Git-specific behavior belongs in a git repository artifact adapter, not in `State`.

`State` should not execute git commands.

---

## Artifact Adapters

Artifact-specific behavior belongs behind adapters.

Adapters exist so that `State` can remain stable while artifact types evolve.

Conceptually:

```text
State
    contains typed artifact references

Adapters
    understand concrete artifact semantics
```

Adapters may handle:

* validation,
* projection,
* loading,
* persistence,
* diffing,
* update proposal generation,
* update application,
* format-specific parsing,
* external tool interaction.

The adapter layer is where concrete behavior belongs.

The state object itself should remain passive.

---

## Adapter Registry

The framework should use an adapter registry to dispatch artifact behavior by artifact kind.

Conceptually:

```text
artifact.kind
    -> adapter registry
    -> artifact-specific adapter
```

This avoids forcing the central state schema to know every concrete artifact subtype.

This matters even if the first implementation only supports one or two artifact types.

The registry keeps the architecture extensible without weakening the core state model.

---

## Side-Effect Rule

`State` must not perform side effects.

Forbidden inside `State`:

* filesystem writes,
* git commands,
* blackboard appends,
* network calls,
* model calls,
* tool execution,
* mutation of external resources.

Allowed:

* typed current project structure,
* pure validation,
* pure serialization,
* pure value construction.

Side effects belong in:

* adapters,
* blackboard event appenders,
* integration services,
* runtime services,
* explicit persistence layers.

---

## History Rule

`State` must not contain full history.

Forbidden inside `State`:

* old game traces,
* rejected proposals,
* reasoning logs,
* full prior versions,
* raw audit history,
* planner deliberations,
* behavioral memory,
* complete blackboard replay.

These belong on the blackboard.

`State` may contain current facts derived from history only if they are part of the current authoritative project condition.

Example:

* A current unresolved discrepancy may belong in `State` if it is treated as part of the current project condition.
* The historical sequence of findings that produced that discrepancy belongs on the blackboard.

---

## Projection

Projection should derive an LLM-readable view from `State`.

Conceptually:

```text
ProjectStateView = projection(State)
```

Projection should not automatically mean:

```text
ProjectStateView = projection(Blackboard)
```

Historical blackboard information may be included only when explicitly requested by a projection policy.

The default projection target is the current authoritative project condition.

---

## NorthStar Projection

The `NorthStar` must be projectable independently from ordinary artifacts.

This allows planners and games to reason over project direction without conflating it with ordinary project material.

Conceptually:

```text
project_northstar(state.northstar)
```

The projection may include:

* the full NorthStar artifacts,
* selected sections,
* summaries,
* constraints,
* authority rules,
* amendment policy.

The projection mechanism should be explicit and bounded.

---

## State Updates

State updates must be controlled.

The canonical flow is:

```text
State
    + StateUpdateProposal
    + IntegrationDecision
    -> new State
```

A proposal alone must not mutate `State`.

A game response alone must not mutate `State`.

A planner output alone must not mutate `State`.

Only accepted integration decisions may authorize durable state mutation.

---

## Functional Update Style

State updates should be modeled as transformations from one state value to another.

Conceptually:

```text
apply_update(state, proposal) -> new_state
```

Avoid hidden in-place mutation.

Avoid methods that silently write external resources.

Persistence should be explicit and separate from state transformation.

---

## NorthStar Updates

A `NorthStar` update is a state update with special authority requirements.

The system may propose a `NorthStar` update.

The system may evaluate a `NorthStar` update.

The system may defer a `NorthStar` update for human approval.

The system may not apply a `NorthStar` update without explicit human approval.

Conceptually:

```text
StateUpdateProposal(target = NorthStar)
    -> IntegrationDecision(defer_for_human_approval)
    -> human approval or rejection
    -> new State only if approved
```

---

## Ordinary Artifact Updates

Ordinary artifact updates may be handled through artifact adapters.

Conceptually:

```text
StateArtifact
    + StateUpdateProposal
    + adapter
    -> updated StateArtifact
```

The adapter performs artifact-specific logic.

The state update layer controls whether the result becomes part of the new `State`.

---

## Persistence

Persistence is separate from `State`.

`State` is the value.

Persistence is how the value is stored or materialized.

Examples:

* a manifest file,
* a directory layout,
* a git repository,
* document files,
* serialized JSON,
* external stores.

Persistence behavior belongs in adapters or dedicated persistence services.

---

## Behavioral Memory

Behavioral/system-learning information belongs on the blackboard unless it becomes part of the current authoritative project condition.

Examples of blackboard behavioral memory:

* recurring failure patterns,
* useful prompt strategies,
* model weaknesses,
* planner mistakes,
* red-team findings,
* tool reliability observations,
* operational lessons.

Such information may later influence projections or planning.

However, it should not silently become `State`.

---

## Minimal Initial Implementation

The first implementation should be intentionally small.

Add:

```text
src/baps/state.py
```

With:

```text
State
NorthStar
StateArtifact
StateArtifactAdapter
StateArtifactRegistry
```

Initial concrete adapter stubs:

```text
DocumentArtifactAdapter
GitRepositoryArtifactAdapter
```

Do not implement full projection yet.

Do not implement full update application yet.

Do not integrate runtime or planner yet.

First stabilize the state boundary.

---

## Initial Tests

Initial tests should enforce the boundary.

Required tests:

```text
State requires NorthStar.
State.artifacts defaults to an empty tuple or must be explicitly provided.
NorthStar is not a StateArtifact.
NorthStar contains StateArtifacts.
State.artifacts contains StateArtifacts.
StateArtifact requires non-empty id.
StateArtifact requires non-empty kind.
State has no blackboard/history fields.
Unknown artifact kind is rejected by registry dispatch.
Registered artifact kind resolves to the correct adapter.
State update helpers return a new State instead of mutating the input State.
```

Future tests should cover:

```text
NorthStar projection is separate from ordinary artifact projection.
Blackboard history is not included in default state projection.
NorthStar updates require human approval.
Ordinary artifact updates require accepted integration decisions.
```

---

## Non-Goals For This Phase

Do not solve these yet:

* full git integration,
* full document editing,
* arbitrary artifact type hierarchy,
* planner redesign,
* autonomous state evolution,
* blackboard projection policies,
* event migration,
* multi-agent orchestration,
* tool execution.

Those should come after the state boundary is stable.

---

## Summary Invariants

```text
1. State is the current authoritative project condition.
2. Blackboard is durable process memory that is not State.
3. Every State has exactly one NorthStar.
4. NorthStar is not a StateArtifact.
5. NorthStar contains StateArtifacts.
6. State.artifacts contains ordinary StateArtifacts.
7. StateArtifact is minimal and passive.
8. Concrete artifact behavior belongs in adapters.
9. State performs no side effects.
10. State contains no full history.
11. Projection is derived from State by default.
12. State updates require accepted integration decisions.
13. NorthStar updates require explicit human approval.
```
