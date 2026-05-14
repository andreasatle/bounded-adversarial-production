# BAPS Unified TODO / Roadmap

This document tracks the current coherent development direction for BAPS.

The project evolves additively through bounded validated steps.

The primary goal is NOT autonomous chaos.
The goal is stable adversarial convergence toward durable project goals.

---

# CURRENT CORE DIRECTION

The system is evolving toward:

    discrepancy between:
        current believed state
        vs
        goal/north-star state

            ->
        bounded adversarial games

            ->
        candidate updates

            ->
        accepted durable state evolution

Games are local bounded optimization attempts.

The framework layer owns:
- scheduling
- prioritization
- durable integration
- resource allocation

The game engine owns:
- bounded local adversarial execution

---

# PHASE 1 — HARDEN CURRENT FOUNDATIONS

Status:
Mostly implemented.

Goals:
- stabilize semantics
- eliminate ambiguity
- preserve clean authority boundaries
- avoid premature orchestration explosion

## 1.1 Runtime Semantics

- [ ] Remove duplicated prompt assembly logic between:
  - `play_game.py`
  - `game_service.py`

- [ ] Introduce shared runtime construction helpers

- [ ] Clarify and formalize:
  - request
  - response
  - state transition
  semantics

- [ ] Decide whether:
  - `GameResponse`
  - `GameState`
  - projected state updates
  should become separate explicit concepts

- [ ] Introduce explicit:
  - terminal outcome
  - integration recommendation
  semantics

## 1.2 Structured Role Outputs

Current Red parsing is line-oriented.

Need stronger structured outputs.

- [ ] Add optional strict JSON response mode
- [ ] Add schema-driven role output parsing
- [ ] Preserve fallback permissive parsing
- [ ] Add malformed-output retry semantics

## 1.3 Event System

Current blackboard is append-only JSONL.

Need stronger querying and projection support.

- [ ] Add per-run query helpers
- [ ] Add event summarization
- [ ] Add filtered replay support
- [ ] Add lightweight indexing
- [ ] Add run lineage support

Do NOT:
- add heavy databases yet
- redesign append-only semantics

## 1.4 Artifact System

Artifact system exists but is not integrated into runtime.

- [ ] Connect runtime decisions to artifact proposals
- [ ] Support:
  - proposed changes
  - accepted changes
  - rejected changes
  lifecycle

- [ ] Add explicit:
  - artifact mutation authority
  - rollback semantics
  - revision lineage

- [ ] Add richer artifact adapters

Current supported:
- document

Future:
- code repository
- structured config
- test suites
- architecture docs

## 1.5 State Sources

Current state sources are read-only text adapters.

Need richer grounding.

- [ ] Add repository-aware adapters
- [ ] Add semantic retrieval helpers
- [ ] Add structured project-state projections
- [ ] Add discrepancy-oriented retrieval

Avoid:
- uncontrolled context explosion
- giant prompts

---

# PHASE 2 — ACCEPTED STATE + PROJECTIONS

Current blackboard is history, not canonical state.

Need materialized/projected views.

## 2.1 Accepted State Layer

Introduce explicit projected state:

- [ ] Accepted accomplishments
- [ ] Accepted architecture
- [ ] Accepted capabilities
- [ ] Known unresolved discrepancies
- [ ] Active game registry

Important:
Blackboard remains append-only history.

Projected state is derived/materialized.

## 2.2 Integration Semantics

Need explicit durable integration authority.

Introduce:
- Integrator component

Responsibilities:
- consume `GameResponse`
- compare competing outputs
- decide accepted durable state
- determine project evolution

- [ ] Define `IntegrationDecision`
- [ ] Define state transition semantics
- [ ] Define conflict-resolution semantics

## 2.3 Discrepancy Tracking

Core future semantic direction.

Need explicit discrepancy representation.

- [ ] Introduce discrepancy schemas
- [ ] Represent:
  - missing capability
  - architecture drift
  - documentation drift
  - goal mismatch
  - unresolved findings

- [ ] Add discrepancy severity/materiality

---

# PHASE 3 — GOAL-DRIVEN EVOLUTION

Goal documents are durable directional guidance.

Need explicit support.

## 3.1 Goal Documents

- [ ] Introduce formal goal-document schemas
- [ ] Add invariant support
- [ ] Add constraint support
- [ ] Add quality expectations
- [ ] Add architectural-direction support

## 3.2 Goal Discrepancy Analysis

Games should derive from discrepancy.

- [ ] Compare:
  - current believed state
  - vs goal state

- [ ] Generate discrepancy candidates
- [ ] Prioritize discrepancies
- [ ] Open bounded games from discrepancies

## 3.3 Goal Evolution

Goal evolution is high-authority.

Do NOT allow arbitrary mutation.

Potential future support:
- contradiction detection
- underspecification detection
- architectural pressure feedback
- sponsor-reviewed refinements

---

# PHASE 4 — FRAMEWORK LAYER

Current implementation mostly has:
- runtime
- roles
- blackboard

Need higher-level orchestration.

## 4.1 Sponsor

Sponsor owns:
- goals
- scope
- budgets
- game contracts

- [ ] Define Sponsor abstraction
- [ ] Define game-opening semantics
- [ ] Define budget semantics

## 4.2 Scheduler

Separate scheduling from game semantics.

- [ ] Add game queue
- [ ] Add prioritization
- [ ] Add concurrency controls
- [ ] Add resource budgeting

## 4.3 Integrator

Integrator owns durable project evolution.

- [ ] Integrate accepted outcomes
- [ ] Maintain projected state
- [ ] Resolve conflicts
- [ ] Track directional convergence

## 4.4 Game Registry

- [ ] Track active games
- [ ] Track completed games
- [ ] Track superseded games
- [ ] Track unresolved findings

---

# PHASE 5 — MULTI-AGENT EVOLUTION

Current runtime:
- single linear Blue -> Red -> Referee

Future:
more dynamic bounded adversarial structures.

## 5.1 Multi-Agent Teams

Potential:
- PM agents
- specialized reviewers
- security reviewers
- architecture reviewers
- testing agents
- discrepancy-analysis agents

Need:
- bounded authority
- scoped visibility
- explicit contracts

## 5.2 Dynamic Agent Spawning

Possible future:
agents spawning sub-agents.

Must preserve:
- boundedness
- traceability
- auditability

## 5.3 Red Team Evolution

Red evolves toward generalized drift detection.

Potential domains:
- code drift
- architecture drift
- security drift
- documentation drift
- accomplishment drift

Red remains:
- critique-only
- non-mutating

---

# PHASE 6 — MODEL + TOOL INFRASTRUCTURE

Infrastructure should remain separate from semantics.

## 6.1 Model Routing

- [ ] Local model routing
- [ ] Frontier-model escalation
- [ ] Cost-aware model selection

Current assumption:
- local models for routine games
- frontier models for planning/global audits

## 6.2 Tooling

Potential future:
- repository tools
- retrieval tools
- execution sandboxes
- test runners
- diff analyzers

Need:
- explicit tool authority
- audit trails
- bounded execution

## 6.3 Distributed Execution

Infrastructure concern only.

Do NOT redesign semantics for distribution.

Future:
- multi-machine execution
- worker pools
- remote execution
- resource allocators

---

# OPEN QUESTIONS

## Convergence

Does adversarial bounded structure improve:
- drift resistance
- robustness
- long-term coherence
vs simpler iterative systems?

## Materiality

What discrepancies deserve:
- revise rounds
- escalation
- sponsor attention?

## Planner State

What projected state should planners/sponsors see?

## Durable State

What becomes:
- durable accepted state
vs
- transient history?

## Goal Evolution

How can goals evolve safely without destabilizing identity?

---

# DEVELOPMENT RULES

The project should evolve:

- additively
- through executable tests
- through bounded semantics
- through explicit authority boundaries
- through deterministic validation where possible

Avoid:
- premature infrastructure explosion
- uncontrolled autonomous behavior
- semantic ambiguity
- hidden authority
- giant rewrites

Build outward in layers.
Stabilize inner semantics first.