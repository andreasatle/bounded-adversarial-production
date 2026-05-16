# Bounded Adversarial Production

State-centric agent framework for bounded, inspectable progression loops.

The repository currently emphasizes typed boundaries, deterministic behavior, and explicit event recording over autonomous execution.

## Core Loop

Current architectural loop:

```text
State -> Views -> StateProgressor -> GameProposal -> GameExecutor -> Integrator -> Blackboard
```

This loop is represented by composable model/protocol boundaries and a small orchestration function (`run_loop(...)`).

## Key Concepts

- `State`: authoritative project condition (`src/baps/state.py`), distinct from process history.
- `StateView` / `NorthStarView`: deterministic rendered views of state inputs (`src/baps/northstar_projection.py`).
- `Blackboard`: append-only JSONL process memory and event replay source (`src/baps/blackboard.py`).
- `StateProgressor`: proposes a candidate game progression from objective + north star view (`src/baps/state_progressor.py`).
- `GameProposal`: structured candidate game emitted by a progressor.
- `GameExecutor`: executes a proposed game and returns a `GameExecutionResult` (`src/baps/game_executor.py`).
- `IntegrationDecision` / `StateChange`: structured integration outcome over execution results (`src/baps/integration.py`).
- `run_loop(...)`: explicit orchestration of progressor -> executor -> integrator (`src/baps/loop.py`).

## Current Maturity

- Deterministic/fake implementations exist for progression, execution, and integration boundaries.
- Real execution semantics and real state mutation pipelines are not implemented yet.
- Current value is boundary clarity, replayability, inspectability, and strong test coverage.

## Existing Runtime Path

In parallel, the project still includes the bounded Blue/Red/Referee runtime path (`runtime.py`, `game_service.py`, `play_game.py`) with append-only blackboard event output.

## Quickstart

Install dependencies:

```bash
uv sync
```

Run tests:

```bash
uv run pytest
```

Run deterministic demo:

```bash
uv run baps-demo
```
