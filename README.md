# bounded-adversarial-production (BAPS)

BAPS is a framework for **bounded model-driven project evolution**.

Projects evolve through:

- authoritative state
- textual model projections
- bounded games
- typed deltas
- controlled state mutation
- exported outputs

The current runtime is adapter-driven and supports multiple project types.

---

## Canonical Runtime

```text
config/NorthStar
        ↓
      State
        ↓
    StateView
        ↓
   CreateGame
        ↓
     GameSpec
        ↓
     PlayGame
        ↓
    DeltaState
        ↓
StateUpdateProposal
        ↓
   StateService
        ↓
      export
```

Lifecycle commands:

```bash
baps-run init
baps-run run
baps-run init_and_run
```

---

## Core Concepts

### State

`State` is the authoritative project condition.

Properties:

- persisted as JSON
- canonical source of truth
- contains `NorthStar`
- contains project artifacts

Examples:

- document artifacts
- coding artifacts

---

### StateView

`StateView` is the **model-facing textual projection**.

Models consume:

```text
StateView.content
```

Models do **not** consume raw `State` JSON.

Example:

```text
=== StateView Start ===

--- NorthStar ---

# Goal

Implement Fibonacci generator.

--- State Artifacts ---

## Artifact: main-code

kind: coding

### Files

src/fibonacci.py

=== StateView End ===
```

---

### CreateGame

CreateGame derives the next bounded task:

```text
State + NorthStar
        ↓
     GameSpec
```

Example:

```text
Objective:
Create Fibonacci implementation.

Success condition:
File exists and tests pass.
```

---

### PlayGame

PlayGame executes bounded adversarial evaluation:

```text
Blue
   ↓
Red
   ↓
Referee
```

Blue:
- proposes candidate delta

Red:
- critiques proposal

Referee:
- decides:

```text
accept
revise
reject
```

---

### Integration

Accepted deltas become:

```text
DeltaState
      ↓
StateUpdateProposal
      ↓
StateService
```

`StateService` is the mutation boundary.

Only integrated proposals modify authoritative state.

---

### Export

Export materializes state:

```text
State
   ↓
output files
```

Export is:

- one-way
- non-authoritative

Output files never define state.

---

## Project Types

Current adapters:

### Document

Capabilities:

- document state
- section updates
- markdown export

Delta:

```text
append_section
```

Example:

```bash
uv run baps-run init_and_run \
    --spec examples/document-project.yaml
```

---

### Coding

Capabilities:

- file state
- code generation
- file export

Delta:

```text
write_file
```

Example:

```bash
uv run baps-run init_and_run \
    --spec examples/coding-project.yaml
```

Example output:

```text
src/fibonacci.py
tests/test_fibonacci.py
```

---

## Installation

Install dependencies:

```bash
uv sync
```

Run tests:

```bash
uv run pytest
```

---

## Architecture Principles

1. State is authoritative.

2. StateView is model-facing.

3. Project mechanics belong to adapters.

4. Core orchestration remains project-type generic.

5. StateService owns mutation.

6. Export is one-way.

---

## Documentation

System contract:

```text
docs/SYSTEM.md
```

Implementation details:

```text
docs/ARCHITECTURE.md
```

---

## Current Status

Implemented:

- adapter-driven runtime
- document adapter
- coding adapter
- CreateGame
- PlayGame
- bounded role execution
- Ollama integration
- deterministic tests

Inactive / future:

- blackboard runtime integration
- tool execution subsystem
- richer orchestration layers