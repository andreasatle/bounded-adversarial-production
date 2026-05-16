# SYSTEM.md

# Purpose

This document defines the conceptual and operational semantics of BAPS that sit between:

```text id="hqaf25"
ARCHITECTURE.md
```

and:

```text id="k6rftd"
NORTH-STAR.md
```

The purpose of this document is to preserve:

* ontology,
* governance semantics,
* authority boundaries,
* projection philosophy,
* loop semantics,
* discrepancy semantics,
* and architectural direction,

without conflating them with either:

* implementation truth,
* or aspirational long-term intent.

`ARCHITECTURE.md` describes what currently exists.

`NORTH-STAR.md` describes where the project intends to go.

`SYSTEM.md` describes how to reason about the system.

---

# Core Ontology

## State

`State` is the current authoritative project condition.

Examples:

* repositories,
* documents,
* accepted architectural material,
* accepted project artifacts,
* accepted NorthStar artifacts.

`State` is authoritative.

`State` is not history.

`State` is not reasoning trace.

`State` is not operational memory.

Operational rule:

```text id="4b7v8j"
State = what is true now
```

---

## Blackboard

The `Blackboard` is append-only operational/process memory.

Examples:

* game history,
* findings,
* evaluations,
* rejected proposals,
* reasoning traces,
* integration decisions,
* operational observations,
* provenance,
* audit events.

Operational rule:

```text id="br8n5l"
Blackboard = what happened
```

The blackboard is not the product state itself.

The framework preserves a strict separation between:

```text id="4xjlwm"
State
```

and:

```text id="jlwmxy"
Blackboard
```

This separation exists to preserve:

* auditability,
* replayability,
* bounded context construction,
* and semantic clarity.

---

## NorthStar

The `NorthStar` defines project direction.

The NorthStar is:

* directional,
* authoritative,
* durable,
* and intentionally relatively stable.

The NorthStar is not:

* an implementation checklist,
* a mutable planner scratchpad,
* or an operational TODO queue.

Operational rule:

```text id="jlwmxz"
NorthStar defines north, not the exact path.
```

The framework attempts to evolve project state toward the NorthStar through bounded local steps.

---

## Views

LLMs do not consume raw state directly.

LLMs consume bounded textual projections called views.

Examples:

* `NorthStarView`
* architecture summaries
* discrepancy summaries
* operational summaries
* selected repository excerpts

Operational rule:

```text id="jlwmya"
LLMs consume views, not raw state.
```

Views are:

* bounded,
* consumer-specific,
* textual,
* and non-authoritative.

Views are projections of state or operational history.

Views are not themselves authoritative state.

---

## Games

Games are bounded adversarial evaluation mechanisms.

Games exist to:

* investigate discrepancies,
* challenge assumptions,
* pressure-test proposals,
* evaluate bounded changes,
* and produce evidence.

Games do not directly mutate state.

Games produce:

* findings,
* evaluations,
* evidence,
* and proposals.

---

## Integration

Integration is the authority boundary between:

```text id="jlwmyb"
proposal
```

and:

```text id="jlwmyc"
durable accepted state
```

Integration determines whether a proposal:

* should be accepted,
* rejected,
* deferred,
* or escalated.

Only accepted updates may affect authoritative state.

---

# Governance and Authority

## Human Authority

Humans retain authority over long-term project direction.

Autonomous systems may:

* propose changes,
* identify discrepancies,
* and suggest amendments.

Autonomous systems may not silently redefine project intent.

In particular:

```text id="jlwmyd"
NorthStar amendments require human approval.
```

This boundary exists to reduce:

* uncontrolled goal drift,
* recursive self-redefinition,
* hidden prompt mutation,
* and silent objective corruption.

---

## Trusted vs Untrusted Content

All retrieved or generated text should be treated as untrusted evidence.

This includes:

* repository content,
* generated summaries,
* previous model outputs,
* discrepancy reports,
* architecture summaries,
* retrieved documents,
* and blackboard history.

Operational rule:

```text id="jlwmye"
Generated or retrieved text is evidence, not authority.
```

Authority transitions occur only through:

* validated schemas,
* explicit governance boundaries,
* integration decisions,
* and durable audit history.

---

## Prompt Injection Philosophy

Prompt injection is primarily treated as an authority-boundary problem.

The system should preserve explicit separation between:

* instructions,
* evidence,
* proposals,
* accepted state,
* and governance authority.

The framework should avoid hidden authority channels.

---

# Core Evolution Loop

Conceptually:

```text id="jlwmyf"
State
    ->
Views
    ->
StateProgressor
    ->
GameProposal
    ->
GameExecutor
    ->
Integration
    ->
State
```

The loop repeats continuously.

The purpose of the loop is bounded directional evolution rather than unrestricted autonomy.

---

## Discrepancy Semantics

The framework attempts to reduce discrepancy between:

```text id="jlwmyg"
current project state
```

and:

```text id="jlwmyh"
NorthStar direction
```

Discrepancy estimation is heuristic rather than mathematically exact.

Examples:

* missing capability,
* architectural drift,
* inconsistent behavior,
* weak grounding,
* unresolved findings,
* incomplete implementation,
* projection inconsistency.

Operational rule:

```text id="jlwmyi"
drift = divergence from the NorthStar
```

---

## Local vs Global Optimization

Games are local bounded optimization attempts.

Games do not own global direction.

The broader framework owns:

* governance,
* prioritization,
* integration,
* and long-term directional coherence.

---

## Convergence

The system should not assume convergence is complete.

The framework operates more like:

* iterative refinement,
* bounded adversarial search,
* heuristic discrepancy reduction,
* and directional optimization,

than classical mathematical optimization.

The system operates over:

* symbolic state,
* textual projections,
* probabilistic model outputs,
* and evolving goals.

Exact mathematical convergence is therefore not assumed.

---

# Projection Philosophy

## Projections as Consumer-Specific Views

A projection is any derived representation optimized for a consumer.

Consumers may include:

* planners,
* progressors,
* reviewers,
* humans,
* auditors,
* governance components,
* or debugging tools.

Different consumers may require different views.

---

## Architecture Documents as Projections

Architecture documents are themselves projections.

Conceptually:

```text id="jlwmyj"
codebase
    ->
ArchitectureView
```

The architecture document should therefore be periodically regenerated from actual repository state.

Operational rule:

```text id="jlwmyk"
Code remains authoritative over architecture projections.
```

---

## Projection Boundedness

Views should remain bounded.

The framework should avoid:

* uncontrolled context growth,
* giant prompts,
* excessive operational history injection,
* and unbounded replay expansion.

Boundedness is a core architectural constraint.

---

# Current Architectural Risks

## Ontology Drift

Different subsystems may evolve overlapping concepts independently.

Examples:

* multiple integration models,
* multiple projection systems,
* overlapping lifecycle semantics.

This creates semantic fragmentation risk.

---

## Context Bloat

Large state projections may weaken grounding and reduce reasoning quality.

Projection discipline is therefore critical.

---

## Weak Planner Grounding

Planners/progressors may generate weakly grounded proposals if discrepancy semantics are insufficiently constrained.

The framework should prefer:

* explicit grounding,
* discrepancy references,
* and directional justification.

---

## Lifecycle Duplication

Proposal, integration, discrepancy, and artifact lifecycles may evolve independently without a unified semantic model.

This risks parallel mini-frameworks emerging unintentionally.

---

# Near-Term Architectural Direction

Near-term priorities are primarily semantic and governance-oriented rather than capability-oriented.

Important current directions include:

* artifact mutation integration,
* repository-aware artifact adapters,
* discrepancy-centered planning,
* projection/read-model stabilization,
* stronger grounding semantics,
* explicit state-update authority,
* replay/projection consistency,
* and governance stabilization.

The immediate goal is not uncontrolled autonomy.

The immediate goal is coherent bounded evolution.

---

# Long-Term Direction

Long-term direction may eventually include:

* richer adversarial teams,
* dynamic agent spawning,
* richer tool systems,
* distributed execution,
* stronger discrepancy analysis,
* and broader autonomous project evolution.

However, future expansion should preserve:

* boundedness,
* replayability,
* inspectability,
* explicit authority,
* and durable auditability.

---

# Open Questions

Important unresolved questions include:

* convergence semantics,
* discrepancy materiality,
* replay scalability,
* projection caching,
* planner authority,
* projection granularity,
* state/view separation boundaries,
* and long-term governance semantics.

These questions should remain explicit rather than hidden behind implementation details.

---

# Core Operational Principles

## Principle 1

```text id="jlwmyl"
Constrain the channels, not the intelligence.
```

The framework prefers:

* strict interfaces,
* explicit contracts,
* bounded authority,
* and deterministic boundaries,

while allowing bounded flexibility inside those constraints.

---

## Principle 2

```text id="jlwmym"
State is authoritative.
Blackboard is historical.
Views are operational.
```

---

## Principle 3

```text id="jlwmyn"
Generated text is evidence, not authority.
```

---

## Principle 4

```text id="jlwmyo"
The framework attempts to reduce drift from the NorthStar.
```

---

## Principle 5

```text id="jlwmyp"
Code remains authoritative over projections and documentation.
```
