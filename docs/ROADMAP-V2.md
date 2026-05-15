# Revised BAPS Roadmap

This roadmap reflects the current implementation state of BAPS, while separating:

* implemented foundations,
* near-term semantic consolidation,
* medium-term governance evolution,
* and longer-term aspirational capabilities.

The project should continue evolving additively through bounded validated steps.

The immediate priority is no longer feature explosion.
The immediate priority is semantic stabilization and architectural coherence.

---

# CURRENT PROJECT STATE

BAPS already contains substantial foundational infrastructure:

Implemented in meaningful form:

* bounded adversarial runtime loop
* append-only blackboard/event history
* role validation and retry guards
* prompt rendering system
* model abstraction layer
* Ollama integration
* deterministic testing infrastructure
* projected-state read models
* integration decision recording
* discrepancy schemas/events
* bounded planner/autonomous helpers
* filesystem artifact lifecycle primitives
* state-source routing/manifests

The project is no longer in the “toy framework” stage.

The primary architectural risk has shifted from:

* missing capability

to:

* semantic fragmentation,
* unclear authority boundaries,
* lifecycle duplication,
* and ontology drift.

---

# IMMEDIATE PRIORITY — SEMANTIC CONSOLIDATION

This is the current critical phase.

Do NOT aggressively expand:

* autonomy,
* orchestration,
* dynamic agents,
* distributed execution,
  before these semantics stabilize.

## 1. Clarify Authority Boundaries

Need explicit stable distinctions between:

* runtime-local state
* projected/read-model state
* accepted durable state
* transient proposals
* historical event log

Important unresolved areas:

* `GameState` vs `GameResponse`
* integration authority semantics
* projection authority semantics
* accepted-state lifecycle semantics

## 2. Stabilize Event Semantics

Current append-only event model is strong, but replay semantics need strengthening.

Near-term goals:

* explicit lineage semantics
* replay/reconstruction guarantees
* stable event identity semantics
* supersession/revocation consistency
* causal relationship clarity

Avoid:

* heavy databases
* premature infrastructure complexity

## 3. Consolidate Lifecycle Models

Current architecture contains multiple partially-overlapping lifecycle systems:

* discrepancies
* accepted state
* artifact proposals
* integration decisions
* revocations/supersessions

Need clearer generalized lifecycle semantics.

Risk:
parallel mini-frameworks emerging independently.

## 4. Audit Projection Semantics

Projected state is now a major architectural layer.

Need:

* projection auditability
* deterministic rebuild guarantees
* conflict semantics
* accepted-state provenance clarity

Important current ambiguity:
cross-schema provenance naming and event-vs-run identity consistency.

## 5. Artifact Governance Integration

Artifact infrastructure exists but governance semantics remain incomplete.

Near-term goals:

* explicit artifact proposal workflows
* integration-to-artifact linkage
* accepted/rejected proposal semantics
* mutation authority clarification
* revision lineage stabilization

---

# SHORT-TERM DEVELOPMENT (NEXT ACTIVE PHASE)

After semantic consolidation stabilizes.

## 1. Stronger Planner Semantics

Planner should:

* inspect projected state
* inspect unresolved discrepancies
* estimate highest-value directional movement
* emit bounded game requests

Planner must NOT silently invent intent.

Need:

* grounding assessment
* underspecification detection
* amendment proposal semantics
* directional justification

Potential planner outputs:

* proposed task
* grounding rationale
* cited north-star principles
* ambiguity/underspecification warnings

## 2. North-Star / Goal Evolution

The north-star document should remain:

* aspirational
* directional
* amendable
* reviewable

but not:

* rigid implementation sequencing
* operational task lists

Need support for:

* amendment proposals
* ambiguity detection
* contradiction detection
* underspecification pressure

High-authority goal evolution must remain review-driven.

## 3. Discrepancy-Centered Planning

Move toward:

* discrepancy-derived games
  instead of:
* manually selected tasks.

Potential discrepancy types:

* architecture drift
* missing capability
* documentation drift
* unresolved findings
* projection inconsistencies
* goal mismatch

---

# MEDIUM-TERM EVOLUTION

Only after semantic foundations are stable.

## 1. Scheduler / Resource Governance

Need bounded orchestration without centralized micromanagement.

Potential responsibilities:

* game prioritization
* resource budgeting
* concurrency limits
* escalation control

Important tension:
preserve local autonomy while enforcing boundedness.

## 2. Richer State Sources

Future goals:

* repository-aware adapters
* semantic retrieval
* discrepancy-oriented retrieval
* architecture-aware context extraction

Avoid:

* uncontrolled context flooding
* giant prompts

## 3. Richer Artifact Types

Current:

* document artifacts

Future:

* repositories
* structured configs
* test suites
* architecture graphs
* operational manifests

## 4. Improved Structured Outputs

Need stronger:

* schema-driven extraction
* malformed-output recovery
* deterministic validation
* structured evidence references

---

# LONG-TERM ASPIRATIONAL DIRECTION

These are directional goals, not immediate implementation priorities.

## 1. Multi-Agent Bounded Teams

Potential future:

* architecture reviewers
* security reviewers
* discrepancy-analysis agents
* testing agents
* planning agents

All agents must remain:

* bounded
* auditable
* authority-constrained

## 2. Dynamic Agent Spawning

Possible future capability:

* agents spawning bounded subgames/subagents

Must preserve:

* traceability
* boundedness
* replayability
* explicit authority

## 3. Distributed Execution

Infrastructure concern only.

Potential future:

* multi-machine execution
* worker pools
* distributed planners
* remote execution

Do NOT redesign core semantics around distribution.

## 4. Tool Ecosystems

Possible future:

* repository tools
* execution sandboxes
* test runners
* retrieval systems
* diff analyzers

All tools require:

* bounded authority
* audit trails
* explicit execution semantics

---

# IMPORTANT ARCHITECTURAL PRINCIPLES

## 1. North Star Defines Direction, Not Tasks

The north-star document defines:

* directional pressure,
* constraints,
* invariants,
* convergence intent.

The planner operationalizes this into bounded tasks.

If a planner cannot strongly ground a proposed task in the north star, this should generate:

* ambiguity warnings,
* clarification requests,
* or amendment proposals,
  rather than hidden goal mutation.

## 2. Boundedness Over Uncontrolled Autonomy

The project prioritizes:

* bounded execution
* bounded authority
* bounded visibility
* bounded planning horizons

over unrestricted recursive autonomy.

## 3. Event History Is Durable Truth

The append-only blackboard is the durable historical substrate.

Projected state is derived/materialized, not canonical history.

## 4. Local Optimization, Global Governance

Games are local bounded optimization attempts.

The broader framework owns:

* governance
* prioritization
* integration
* directional convergence

## 5. Preserve Auditability

All meaningful state evolution should remain:

* inspectable
* replayable
* attributable
* reconstructable

Avoid hidden mutation and implicit authority.

---

# CURRENT RECOMMENDED FOCUS

Before implementing major new capabilities:

1. Audit Phase 1/2 implementation coherence
2. Stabilize lifecycle semantics
3. Clarify authority boundaries
4. Tighten replay/projection semantics
5. Reduce ontology duplication
6. Strengthen planner grounding semantics

The project now has enough foundational infrastructure.
The priority is ensuring the foundation converges coherently rather than expanding capability surface area prematurely.
