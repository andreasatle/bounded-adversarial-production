# Bounded Adversarial Production

Experimental bounded adversarial production framework with a minimal, deterministic execution loop.
Games currently run as a single Blue / Red / Referee cycle, and runtime events are appended to a Blackboard log.

## Current Components

- `schemas`: Pydantic models for contracts, moves/findings/decisions, runtime state, events, and artifact records.
- `blackboard`: append-only JSONL event log with read/query support.
- `artifact lifecycle`: document artifact adapter, change proposal/apply/rollback, and adapter handler.
- `runtime engine`: one-round game execution with run identity and event emission.
- `role invocation guard`: validated role calls with semantic checks and bounded retries.
- `example deterministic roles`: tiny Blue/Red/Referee role functions for wiring and tests.
- `demo CLI`: `baps-demo` command to run one hardcoded deterministic game.

## Quickstart

Create environment and install dependencies:

```bash
uv sync
```

Run tests:

```bash
uv run pytest
```

Run demo:

```bash
uv run baps-demo
```

## Expected Demo Output

Example:

```text
game_id=demo-game-001
run_id=run-0001
final_decision=accept
blackboard_path=blackboard/events.jsonl
```

## Blackboard Output

- Runtime events are written to `blackboard/events.jsonl`.
- `blackboard/` is ignored by git.
- Events are append-only runtime execution logs.
