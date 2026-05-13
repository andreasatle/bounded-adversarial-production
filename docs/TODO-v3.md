# Future Direction

This document captures the current directional understanding of the project.
It is intentionally lightweight and exploratory.

The goal is not to freeze architecture prematurely, but to preserve the emerging conceptual model so that future work remains directionally coherent.

---

# Core Direction

The framework is evolving toward:

```text
goal discrepancy
    ->
bounded adversarial games
    ->
candidate updates
    ->
accepted state evolution
````

The system is intended to support long-term directional convergence toward a user-defined goal document ("north star"), rather than finite pipeline completion.

The goal is not exact convergence.
The goal is bounded directional improvement.

---

# Current Understanding

## Games Are Sources of Updates

A game is not global truth.

A game is a bounded mechanism for producing:

* candidate updates
* findings
* evidence
* critiques
* local convergence attempts

The game does not own global state.

---

# Blackboard vs State

The append-only JSONL blackboard is currently:

* event history
* trace output
* replayable evidence

It is *not yet* the canonical current project state.

The system likely needs projected/materialized views later:

* current accepted accomplishments
* current accepted architecture
* unresolved discrepancies
* active games
* accepted capabilities

---

# Discrepancy-Driven Evolution

The project should evolve according to discrepancy between:

```text
current believed state
```

and:

```text
goal state / north star
```

Games exist to reduce discrepancy.

The framework should avoid optimizing only against:

* the latest critique
* local reward
* isolated prompts

Directionality must come from the goal document and accepted state.

---

# Red Team Role

Red is evolving into a generalized:

```text
drift detector
```

Red should detect:

* code drift
* documentation drift
* architecture drift
* accomplishment drift
* security drift
* goal mismatch
* local discrepancy increase

Red critiques should remain:

* scoped
* actionable
* bounded to the current game context

Red does not own mutation authority.

---

# Current Accepted Architectural Direction

The architecture is currently converging toward:

```text
Framework Layer
  Sponsor
  Integrator
  Scheduler/Resource Allocation (later)
  Game Registry (later)

Game Engine
  Blue
  Red
  Referee
```

The referee is local to the game.

The integrator owns durable state transition authority.

---

# Prompt Assembly Direction

Hardcoded prompts are currently acceptable while semantics stabilize.

Long-term direction is layered prompt assembly:

```text
framework rules
+ game type rules
+ role rules
+ goal context
+ current state projection
+ round/revision context
+ artifact/context retrieval
```

Prompts are expected to become materialized local game state rather than static templates.

---

# Local vs Frontier Models

The current working assumption is:

* local models perform routine bounded game execution
* stronger frontier models perform:

  * planning
  * discrepancy prioritization
  * global audits
  * difficult reviews
  * sponsor-level reasoning

The project is intentionally local-first.

---

# Multi-Machine Direction

Distributed execution is currently considered a later infrastructure layer rather than a core semantic problem.

The important work is:

* convergence semantics
* state visibility
* discrepancy management
* bounded adversarial dynamics

not distributed execution itself.

---

# Current Major Open Questions

## Convergence

Does adversarial structure materially improve convergence and drift resistance compared to simpler iterative generation systems?

---

## Planner State

What projected state must be exposed for effective sponsor/planner reasoning?

---

## Accepted State

What should become durable accepted project state versus transient blackboard history?

---

## Materiality

What discrepancies deserve additional revise rounds?

How should materiality be determined?

---

## Goal Evolution

How should goal documents evolve safely without destabilizing project identity?

---

# Current Development Philosophy

The project should continue evolving:

* additively
* experimentally
* through bounded games
* through executable validation
* through observed behavior
* without premature infrastructure explosion

The framework should be built in layers ("onion style"), hardening local semantics before introducing additional orchestration layers.

