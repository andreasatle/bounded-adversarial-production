# Project Goal

## Vision

Build a bounded adversarial production framework where AI agents collaborate and critique each other to improve software quality while maintaining explicit state, traceability, and deterministic workflows.

The framework should support:
- structured game execution,
- adversarial review loops,
- explicit project state exposure,
- durable event logging,
- and controlled state evolution.

---

## Core Requirements

### 1. Game Execution

The system shall support:
- GameRequest -> GameResponse execution,
- bounded iterative rounds,
- Blue/Red/Referee roles,
- configurable game definitions.

### 2. Explicit State Exposure

The system shall:
- expose project state declaratively,
- support multiple state source kinds,
- inject selected state into game context,
- keep state access read-only initially.

### 3. Durable Traceability

The system shall:
- persist structured events,
- preserve append-only execution traces,
- support replay/debugging.

### 4. Extensible State Adapters

The framework shall support:
- markdown document state,
- git repository state,
- event log state,
- directory topology state.

### 5. Future Goals

Future versions may support:
- state transitions,
- integrator-controlled mutations,
- sponsor/planner agents,
- automated game selection,
- artifact reconciliation.

---

## Non-Goals

The system is not intended to:
- autonomously modify arbitrary source code,
- perform unrestricted recursive self-modification,
- hide state transitions,
- or rely on opaque mutable agent memory.
