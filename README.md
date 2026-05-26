# baps — bounded adversarial production

`baps` is a CLI runtime for iterative, model-driven project evolution. You give it a spec with a NorthStar (the desired end state) and it runs a loop: identify the highest-priority gap, have a model propose a change, have two other model roles challenge it, apply what passes. Repeat until there are no gaps left.

It is not an autonomous agent that does whatever it wants. Every iteration is bounded by the spec, every mutation goes through a typed state service, and every claim by the model that writes code gets challenged by a model that looks for problems.

---

## How it works

```
NorthStar (your spec)
    ↓
CreateGame — identifies the highest-priority gap between current state and NorthStar
    ↓ (gap too large? decompose into sub-gaps, solve recursively)
GameSpec — a bounded task contract
    ↓
PlayGame — Blue proposes a change, Red challenges it, Referee accepts/rejects
    ↓
StateService — applies the accepted delta to authoritative state
    ↓
export — writes output files
    ↓
loop until no gaps remain
```

CreateGame is gap analysis, not step planning. It does not decide what to do next — it compares the current state against your NorthStar and closes the most important thing that is missing.

---

## Project types

### document

Evolves a structured markdown document through section operations (`append_section`, `modify_section`, `delete_section`). Useful for specs, reports, or any document that should converge toward a defined structure.

### coding

Evolves a codebase through file operations (`write_file`, `write_files`, `delete_file`). After each accepted change, the code is exported and run inside a Docker container to verify tests pass. The verification result feeds back into the next planning step.

### audit

Reads an external source tree and produces a structured findings report. Each finding records a hash of the source files it covers; on re-runs, findings whose source has changed are flagged as stale.

---

## Language plugins (coding projects)

The coding adapter is language-agnostic. The `language` key in your spec is required and selects a plugin that owns the Docker image, the test command, and the project scaffolding.

Built-in plugins:

| Language | `language` key | Docker image | Test command |
|---|---|---|---|
| Python | `python` | `python:3.12-slim` | `pip install pytest -q && python -m pytest` |
| Zig | `zig` | `baps-zig:latest` | `zig build test` |

The plugin handles everything — the right image is used, the right test command runs, and project boilerplate is scaffolded if it does not exist.

The Zig image is not pulled from a registry — build it locally before first use:

```bash
docker build -t baps-zig:latest docker/zig/
```

This produces a Debian Bookworm image with the Zig toolchain for your host architecture (amd64 or arm64).

Adding a new language means writing one plugin file and registering it. Nothing else changes.

---

## Docker sandbox

All code verification runs inside Docker by default. The model's output never executes on your host.

To run without Docker (development only):

```yaml
sandbox: none
```

This prints a warning and should not be used in production.

---

## Getting started

**Install:**

```bash
uv sync
```

**Write a spec** (e.g. `my-project.yaml`):

```yaml
project_type: coding
artifact_id: main-codebase
language: python
goal: "Implement a binary search tree with insert, search, and delete."
northstar_markdown: |
  # Goal
  Implement a binary search tree in Python with:
  - insert(value)
  - search(value) -> bool
  - delete(value)
  - Tests for all three operations using pytest
output: output/bst-project
workspace: .baps-workspace/bst
max_iterations: 10
```

**Run:**

```bash
uv run baps-run start --spec my-project.yaml
```

baps initializes state on the first run and resumes from where it left off on subsequent runs.

**Wipe and start over:**

```bash
uv run baps-run reset --spec my-project.yaml
uv run baps-run start --spec my-project.yaml
```

---

## Commands

### `start`

Smart continue-or-begin. If the workspace has no state, initializes from scratch. If state exists, resumes the loop from the current state.

```bash
uv run baps-run start --spec examples/coding-project.yaml
uv run baps-run start --spec examples/coding-project-zig.yaml
uv run baps-run start --spec examples/document-project.yaml
uv run baps-run start --spec examples/audit-baps.yaml
```

### `reset`

Wipes workspace state and output, then exits. No model calls are made. Run this before `start` when you want a clean slate.

```bash
uv run baps-run reset --spec examples/coding-project.yaml
```

---

## Model configuration

```bash
# Default: Ollama with gemma3:4b (no API key required)
BAPS_BACKEND=ollama            # default; or: anthropic, openai
BAPS_OLLAMA_MODEL=gemma3:4b   # default

# Anthropic (requires API key)
BAPS_BACKEND=anthropic
ANTHROPIC_API_KEY=sk-...
BAPS_ANTHROPIC_MODEL=claude-sonnet-4-6

# OpenAI (requires API key)
BAPS_BACKEND=openai
OPENAI_API_KEY=sk-...
BAPS_OPENAI_MODEL=gpt-4o
```

Each role (Blue, Red, Referee, CreateGame, Decompose) can use a different model:

```bash
BAPS_BLUE_BACKEND=anthropic
BAPS_BLUE_MODEL=claude-sonnet-4-6
BAPS_RED_MODEL=claude-haiku-4-5-20251001
BAPS_REFEREE_MODEL=claude-haiku-4-5-20251001
BAPS_DECOMPOSE_BACKEND=ollama
BAPS_DECOMPOSE_MODEL=gemma3:4b
```

The Decompose role handles structural gap-splitting at planning nodes and can use a lighter model than the roles that write code.

Keys are loaded from `.env` at startup.

---

## Adaptive scheduler

The scheduler runs specs repeatedly and learns which models perform best:

```bash
uv run baps-scheduler \
    examples/coding-project.yaml \
    examples/document-project.yaml \
    --concurrency 2 \
    --rounds 5
```

It scores models by EMA reward, selects via softmax with temperature decay, escalates to stronger models on repeated failures, and drops underperformers after enough runs. Configure the model ladder with `BAPS_MODEL_LADDER`.

---

## Spec reference

```yaml
project_type: coding          # coding | document | audit
artifact_id: main-codebase    # identifier for the state artifact
language: python              # coding only (required): python | zig
goal: "..."                   # human-readable goal; also used as NorthStar fallback
northstar_markdown: |         # target state; all gap analysis measures against this
  ...
output: output/my-project     # where exported files go (relative to workspace)
workspace: .baps-workspace/x  # where state and run metadata live
max_iterations: 10            # max leaf games per run
max_depth: 3                  # max decomposition depth (default: 3)
max_sub_gaps: 5               # max sub-gaps per decomposition (default: 5)
sandbox: docker               # docker (default) | none
```

---

## Run tests

```bash
uv run pytest
```

---

## Documentation

- `docs/SYSTEM.md` — normative contract: invariants, adapter contract, stop conditions, forbidden patterns
- `docs/ARCHITECTURE.md` — implementation: components, schemas, runtime flow, repository structure
