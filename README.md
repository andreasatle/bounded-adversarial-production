# bounded-adversarial-production (BAPS)

BAPS is a framework for **multiscale, bounded, model-driven project evolution**.

Projects evolve through:

- authoritative state
- NorthStar as the target
- gap analysis at multiple scales
- recursive decomposition into coherent sub-games
- adversarial bounded execution
- typed deltas with full context chain
- controlled state mutation
- exported outputs

---

## Canonical Runtime

```text
config/NorthStar
        ↓
      State
        ↓
    StateView
        ↓
   CreateGame ──→ DecomposeSpec ──→ sub-gaps (recursive, up to max_depth)
        ↓
  GameSpec (with context_chain from all ancestor levels)
        ↓
     PlayGame (Blue → Red → Referee)
        ↓
    DeltaState
        ↓
StateUpdateProposal
        ↓
   StateService
        ↓
      export
```

CreateGame performs **gap analysis** — it compares current state against NorthStar, identifies the highest-priority gap, and either produces a `GameSpec` to close it directly or returns a `DecomposeSpec` to split it into coherent sub-gaps. Sub-gaps are solved recursively. Every leaf `GameSpec` carries the full `context_chain` from all ancestor levels, so Blue always has the complete planning hierarchy.

Lifecycle commands:

```bash
baps-run init
baps-run run
baps-run init_and_run
```

Additional tools:

```bash
baps-scheduler       # adaptive multi-model scheduler with policy learning
baps-apply-northstar # review and apply approved NorthStar proposals
```

---

## Core Concepts

### NorthStar

NorthStar is the **target state** — what the completed project should look like. It is authoritative and immutable through the automated pipeline. Updates require human approval via `baps-apply-northstar`.

NorthStar is embedded inside `State` and visible to models only through `StateView`.

---

### State

`State` is the authoritative project condition.

- persisted as JSON via `StateService`
- contains `NorthStar`
- contains project artifacts (document, coding)
- never passed directly to model prompts

---

### StateView

`StateView` is the **model-facing textual projection**.

Models consume `StateView.content` — never raw `State` JSON.

```text
=== StateView Start ===

--- NorthStar ---

# Goal
Implement a Fibonacci generator.

--- State Artifacts ---

## Artifact: main-codebase
kind: coding

### src/fibonacci.py
def fibonacci(n): ...
... (12 more lines)

=== StateView End ===
```

---

### CreateGame

CreateGame performs **gap analysis** against NorthStar:

1. **GAP ANALYSIS** — enumerate what NorthStar requires that is absent or incomplete
2. **PRIORITIZE** — select the highest-impact gap
3. **DECIDE** — can Blue close this gap in one turn? If yes → `GameSpec`. If not → `DecomposeSpec`
4. **SELF-CONTAIN** — fold all NorthStar intent into the output

Returns one of:
- `GameSpec` — directly executable leaf game
- `DecomposeSpec` — split into ordered sub-gaps, each solved recursively
- `{"no_new_game": true}` — all gaps closed
- `{"northstar_update_needed": true}` — trajectory requires NorthStar change (human approval)

---

### Context Chain

Each `GameSpec` carries a `context_chain` — the ordered list of gap descriptions from the coarsest decomposition down to the immediate task. Blue sees the full chain, giving every leaf game awareness of why it exists in the broader plan.

```text
[1] Authentication subsystem is entirely absent
[2] JWT token generation has no implementation
[current] Write jwt_utils.py with sign() and verify()
```

---

### PlayGame

PlayGame executes bounded adversarial evaluation:

```text
Blue   → proposes candidate DeltaState
Red    → critiques the proposal
Referee → decides: accept / revise / reject
```

Bounded by `max_attempts` (default 3). Each role can use a different model via per-role model selection.

---

### Delta Operations

**Document adapter:**

| Operation | Description |
|---|---|
| `append_section` | Add a new section |
| `modify_section` | Rewrite an existing section |
| `delete_section` | Remove a section |

**Coding adapter:**

| Operation | Description |
|---|---|
| `write_file` | Write a single file |
| `write_files` | Write multiple files in one game (preferred) |
| `delete_file` | Remove a file |

---

### Integration

Accepted deltas become:

```text
DeltaState → StateUpdateProposal → StateService
```

`StateService` is the only mutation boundary. NorthStar artifacts are protected — `StateService` rejects any proposal targeting them.

---

### Export

Export materializes state to output files. It is one-way and non-authoritative — exported files never define state.

---

## Project Types

### Document

Evolves a structured markdown document via section operations.

```bash
uv run baps-run init_and_run \
    --spec examples/document-project.yaml
```

### Coding

Evolves a codebase via file operations with pytest verification.

```bash
uv run baps-run init_and_run \
    --spec examples/coding-project.yaml
```

---

## Model Configuration

Backend selection via environment variables:

```bash
BAPS_BACKEND=anthropic          # anthropic | openai | ollama
BAPS_ANTHROPIC_MODEL=claude-sonnet-4-6
BAPS_OPENAI_MODEL=gpt-4o
BAPS_OLLAMA_MODEL=llama3.1:8b
```

Per-role model override (any role can use a different model):

```bash
BAPS_BLUE_BACKEND=anthropic
BAPS_BLUE_MODEL=claude-sonnet-4-6
BAPS_RED_BACKEND=anthropic
BAPS_RED_MODEL=claude-haiku-4-5-20251001
BAPS_REFEREE_BACKEND=anthropic
BAPS_REFEREE_MODEL=claude-haiku-4-5-20251001
BAPS_CREATE_GAME_BACKEND=anthropic
BAPS_CREATE_GAME_MODEL=claude-opus-4-7
```

Keys are loaded from `.env` at startup.

---

## Adaptive Scheduler

The scheduler runs specs repeatedly with policy-guided model selection:

```bash
uv run baps-scheduler \
    examples/document-project.yaml \
    examples/coding-project.yaml \
    --concurrency 2 \
    --rounds 5 \
    --escalation-threshold 0.5
```

- Models are ranked by EMA reward score
- Softmax selection with temperature decay over runs
- Automatic escalation to stronger models on failure
- Underperforming models dropped after enough runs
- Model ladder configurable via `BAPS_MODEL_LADDER`

---

## Spec Format

```yaml
project_type: coding
artifact_id: main-codebase
goal: Build a Fibonacci generator with tests.
northstar_markdown: |
  # Goal
  Implement a complete, tested Fibonacci generator.
output_path: output/
max_iterations: 10
max_depth: 3        # maximum decomposition depth (default: 3)
workspace: .baps-workspace/my-project
```

---

## Installation

```bash
uv sync
```

Run tests:

```bash
uv run pytest
```

---

## Architecture Principles

1. **State is authoritative.** Never bypassed or replaced.
2. **StateView is model-facing.** Not authority — projection only.
3. **NorthStar is the target.** CreateGame closes gaps toward it, not arbitrary steps.
4. **Decomposition is multiscale.** Large gaps split recursively; context flows down.
5. **Project mechanics belong to adapters.** Core orchestration stays generic.
6. **StateService owns mutation.** The only path to durable state change.
7. **Export is one-way.** Derived materialization; never feeds back as authority.

---

## Documentation

System contract: `docs/SYSTEM.md`

Implementation details: `docs/ARCHITECTURE.md`
