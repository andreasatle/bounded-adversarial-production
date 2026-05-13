# High-Level Framework Goals

## Core Direction

The framework is intended to support adversarial, multi-agent project evolution through bounded games operating on shared persistent state.

The current focus is not autonomous self-modification or unrestricted agent behavior. The focus is to establish stable primitives, authority boundaries, and coherent game dynamics.

The system should evolve additively rather than through repeated architectural rewrites.

---

# Core Architectural Principle

The framework separates:

- local game authority
- global integration authority
- resource/scheduling authority

This separation is intended to prevent uncontrolled agent drift and preserve coherent system evolution.

---

# High-Level Architecture

## Framework / Controller Layer

The highest-level framework layer is responsible for:

- opening games
- scheduling/prioritizing work
- resource allocation
- tracking active games
- integrating accepted outputs into durable project state

This layer may itself contain LLM-driven agents.

Future components may include:

- Sponsor agents
- Integrator
- Game registry
- Scheduler
- Resource allocator

---

# Game Engine

The game engine is a bounded adversarial execution environment.

A game consists of:

- Blue team
- Red team
- Referee

The referee is internal to the game engine and is not a top-level authority.

The game engine produces a `GameResult` that is returned to the higher-level framework.

---

# Sponsor

The sponsor defines and opens games.

Responsibilities:

- define goals
- define scope
- define contracts
- define round/resource budgets
- decide what type of game should be played

The sponsor does not directly modify project state.

---

# Blue Team

Blue owns mutations and proposed deltas.

For software projects, Blue is responsible for:

- code changes
- artifact changes
- implementation tests
- revisions after critique

Blue owns the candidate artifact produced during the game.

---

# Red Team

Red critiques the current Blue-produced delta in context.

Red:

- may inspect broad context
- may use prior state as evidence
- may inspect affected existing code
- may not perform unrelated global audits
- may not directly mutate artifacts

Red critiques the delta, not the entire universe.

Red findings should remain actionable and scoped to the current game.

---

# Referee

The referee controls local game flow only.

Responsibilities:

- determine local game outcome
- decide whether:
  - accept
  - revise
  - reject
  - terminate
- keep the game coherent and bounded

The referee does not integrate project state.

The referee does not own global authority.

---

# Integrator

The integrator is a top-level framework component.

Responsibilities:

- consume `GameResult`
- compare competing outputs
- decide whether outputs become durable project state
- coordinate broader project evolution

The integrator owns durable state transition authority.

The integrator may itself use helper agents internally.

---

# Blackboard

The blackboard is persistent shared memory.

The blackboard is append-only and stores:

- events
- findings
- traces
- game history
- accepted outcomes

The blackboard enables:

- replay
- historical inspection
- future retrieval/context grounding
- long-term organizational memory

---

# Context and Grounding

Games should operate on grounded context rather than free hallucination.

Current approach:

- manually injected context files

Future approach may include:

- blackboard retrieval
- artifact retrieval
- repository search
- tool access
- semantic retrieval

Shared visibility with scoped authority is a core principle.

---

# Resource Allocation

Resource allocation is separate from game semantics.

Future resource systems may manage:

- model selection
- machine allocation
- execution scheduling
- concurrency limits

The framework should support future scaling from:

- one sequential machine
to
- distributed pools of workers/models

without redesigning game semantics.

---

# Current Development Philosophy

Current development prioritizes:

- stable primitives
- additive evolution
- bounded semantics
- coherent authority boundaries
- executable tests over excessive documentation

The framework should evolve through small validated steps rather than speculative over-generalization.