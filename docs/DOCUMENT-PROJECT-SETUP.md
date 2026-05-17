# Simple Document Project Setup

## Goal

Create the smallest possible real document project so the BAPS loop becomes inspectable.

The purpose is:

* see every loop step
* inspect generated state
* inspect exported document
* rerun the loop repeatedly
* harden behavior incrementally

Not:

* generic framework expansion
* multi-project scheduling
* software workflow
* agent swarms

---

# Proposed Workspace Layout

```text
.baps-workspace/
  projects/
    drainage-report/
      goal.md
      output/
        report.md
      state/
        current-state.json
      logs/
        loop.log
```

---

# goal.md

```markdown
# Goal

Write a short report about drainage issues around Houston homes.

The report should contain:

- Introduction
- Common causes
- Possible mitigations
- Conclusion
```

This becomes the current NorthStar.

---

# report.md

Initially empty:

```markdown
# Drainage Report
```

The loop progressively improves this file.

---

# current-state.json

This should remain minimal initially.

Suggested shape:

```json
{
  "goal_path": "goal.md",
  "output_path": "output/report.md",
  "known_sections": [],
  "completed": false
}
```

Do not over-design this.

---

# loop.log

Human-readable execution trace.

Example:

```text
iteration=1
state_loaded=True
view_built=True
proposal=append Introduction
accepted=True
export_changed=True
```

This is important because the current goal is observability.

---

# First Real Loop Behavior

## Iteration 1

Input:

* goal.md
* empty report.md

Expected:

* detect missing Introduction
* append Introduction section
* update state
* export report.md
* log actions

## Iteration 2

Expected:

* detect Introduction already exists
* detect Common causes missing
* append Common causes

## Iteration 3

Expected:

* append Possible mitigations

## Iteration 4

Expected:

* append Conclusion

## Iteration 5

Expected:

* no missing sections
* stop

---

# Why This Matters

This changes the system from:

```text
framework demos
```

into:

```text
observable evolving project
```

You can now inspect:

* the goal
* the current exported artifact
* the persisted state
* the loop decisions
* the stop condition

This is the first real hardening environment.

---

# Immediate Hardening Targets

## 1. Goal Parsing

Detect requested sections from goal.md.

Do not use LLM yet.

Simple deterministic parsing is enough.

---

## 2. Section Tracking

Persist completed sections in state.

State becomes authoritative.

Not the View.

---

## 3. Sequential Progress

Only append one section per iteration.

No whole-document rewrites.

---

## 4. Logging

Every iteration should become inspectable.

The user should be able to understand:

```text
why this section was added
```

---

## 5. Replay

Later:

```text
reload state
continue loop
```

without restarting from scratch.

---

# Important Constraint

Keep the system concrete.

Every new function/class/module must answer:

```text
How does this improve the current document loop?
```

If unclear:

Do not add it.
