# HARDENING_LOOP_PLAN

## Purpose

This document defines the immediate hardening plan for BAPS.

The goal is to move from framework skeleton and demos toward a working LLM-agent loop that can actually produce useful output.

The current priority is not broad architecture expansion.

The current priority is:

```text
make the loop run on a real document workflow
```

The core loop is:

```text
User Request
  -> State Derivation
  -> View Construction
  -> Progress Planning
  -> Game Execution
  -> Integration Decision
  -> State Update
  -> Export
  -> Repeat
```

Each step below must become independently testable, replayable, and eventually replaceable by an LLM-backed implementation.

---

# 1. User Request Intake

## Role in the loop

The user request defines what the system should accomplish.

It is not yet the state.
It is not yet the plan.
It is not yet the update.

It is the directional input from which the system derives an initial working problem.

Examples:

```text
Write a short report about drainage problems in Houston houses.
```

```text
Improve this markdown document by adding the missing conclusion section.
```

```text
Extract the parties and dates from this legal document.
```

## Minimal near-term behavior

For now, support only document-oriented requests.

The intake step should produce a small structured request such as:

```text
request_text
output_path
allowed_update_policy
```

Do not build a general intent system yet.

## LLM-agent version

An intake agent can later classify:

```text
document task
software task
legal-doc task
unknown task
```

But the first implementation should not depend on a complex classifier.

For now:

```text
assume document task
```

or require an explicit flag.

## Hardening actions

1. Define the minimal accepted input for the first real document loop.
2. Reject ambiguous inputs instead of guessing silently.
3. Ensure the user request is persisted in the working state or run report.
4. Add tests for valid request, missing output path, and unsupported mode.

## Done when

A command can receive a text goal and an output document path, and the rest of the system can start from that.

---

# 2. State Derivation

## Role in the loop

State derivation converts the user request and environment into internal state.

The user does not need to provide canonical state manually.

Conceptually:

```text
User Request + Environment
  -> State0
```

For the first document loop, the state can be minimal.

## Minimal document state

Do not over-design this.

A first useful document state can be:

```text
DocumentState
  - goal text
  - output path
  - current document text
  - detected sections or markers
```

But if the current existing `State` model is enough for the immediate loop, use it.

Do not invent a rich document model until forced by the workflow.

## LLM-agent version

An LLM may eventually inspect existing document content and infer:

```text
current sections
missing sections
document purpose
candidate next update
```

But the first pass can use deterministic parsing.

## Hardening actions

1. Decide the smallest internal state required for one document append/update.
2. If current `State` is enough, use it.
3. If current `State` is not enough, add only the missing field or operation needed for the document loop.
4. Ensure state derivation is deterministic for tests.
5. Ensure generated state can be persisted and reloaded.

## Done when

Given a request and an output document path, the framework can derive a persisted initial state without the user writing state manually.

---

# 3. View Construction

## Role in the loop

A View is the bounded representation consumed by a progressor or LLM agent.

Do not use “projection” loosely here.

Use:

```text
View = internal reasoning input
Export = user-facing output artifact
```

For a document workflow, the view should expose enough information for the next improvement decision.

Example:

```text
Goal:
Write a short report about X.

Current document:
...

Detected sections:
- Introduction
- Background

Missing obvious sections:
- Conclusion
```

## Minimal near-term behavior

Build a deterministic document view from current document text and goal.

Do not summarize with an LLM yet unless needed.

## LLM-agent version

Later, a ViewBuilder agent may compress long documents into bounded views.

But that is secondary.

The first working document loop should use small files.

## Hardening actions

1. Define the exact text given to the progressor.
2. Keep it short and inspectable.
3. Include the goal, current content, and obvious document structure.
4. Add tests ensuring the view changes after the document changes.

## Done when

The second loop iteration sees a different view after the first update.

---

# 4. Progress Planning

## Role in the loop

The progressor proposes the next bounded move.

It should not rewrite the whole project.
It should not invent architecture.
It should propose one useful next update.

Conceptually:

```text
View
  -> ProgressProposal
```

For the first document loop:

```text
missing section detected
  -> propose append_section
```

## Minimal near-term behavior

Use a deterministic progressor first.

Example:

```text
If marker/section missing:
  propose append section
Else:
  propose no-op / complete
```

## LLM-agent version

An LLM progressor later chooses:

```text
which section to add
what text to write
whether document is complete enough
```

But the LLM output must still be parsed into a narrow proposal.

## Hardening actions

1. Keep proposals small.
2. Allow only one update per loop iteration at first.
3. Add a deterministic no-op path when no update is needed.
4. Add LLM-backed progressor only after deterministic progressor works end-to-end.

## Done when

The progressor can propose exactly one append-only document improvement or explicitly report that no update is needed.

---

# 5. Game Execution

## Role in the loop

The game step evaluates or pressure-tests the proposed move.

It turns a proposal into a result.

For now, do not make the game complicated.

Conceptually:

```text
ProgressProposal
  -> GameResult
```

For document writing, the game may initially check:

```text
Does the section already exist?
Would the update duplicate content?
Is the update append-only?
Does the update preserve existing text?
```

## Minimal near-term behavior

The first game can be deterministic validation, not a multi-agent debate.

## LLM-agent version

Later:

```text
Writer agent proposes text.
Reviewer agent checks relevance and duplication.
Referee accepts/rejects.
```

But only after the deterministic game closes the loop.

## Hardening actions

1. Implement deterministic game checks for append-only document update.
2. Reject destructive updates.
3. Reject duplicate marker/section updates.
4. Produce a clear result object already compatible with integration.

## Done when

A proposed document update is either accepted as safe or rejected with a concrete reason.

---

# 6. Integration Decision

## Role in the loop

Integration is the authority boundary.

It decides whether the game result becomes an update.

Conceptually:

```text
GameResult
  -> Decision
```

The integration layer should not invent new work.
It should decide whether the proposed work is acceptable.

## Minimal near-term behavior

For append-only document updates:

```text
accepted if:
  update is append-only
  marker is absent before update
  existing content is preserved

rejected if:
  duplicate marker
  destructive change
  malformed update
```

## LLM-agent version

Later, an LLM referee can judge semantic quality.

But structural safety should remain deterministic.

## Hardening actions

1. Keep `accepted` separate from quality score/satisfaction.
2. Ensure rejected decisions do not mutate state or files.
3. Ensure accepted decisions produce explicit update proposals.
4. Add tests for accepted, rejected, and no-op decisions.

## Done when

Only accepted decisions can become updates, and every rejection leaves the document unchanged.

---

# 7. State Update

## Role in the loop

The update step mutates authoritative state.

For the first document workflow, this likely means updating the document content and persisted state.

Conceptually:

```text
Decision
  -> Update
  -> State1
```

## Minimal near-term behavior

Support one operation first:

```text
append_section
```

or, if working through the current existing state update mechanism:

```text
add_artifact
```

Do not overload existing operations.

No operation should lie about what it does.

## LLM-agent version

The LLM may write the section text, but the actual update operation should still be structured and validated.

## Hardening actions

1. Add only operations needed by the current document loop.
2. Keep append-only update semantics explicit.
3. Verify before/after hashes or fingerprints.
4. Verify existing content is preserved.
5. Make no-op updates explicit.

## Done when

An accepted append-section decision changes the document once, persists the change, and cannot duplicate the same section on the next run.

---

# 8. Export

## Role in the loop

Export is the user-facing artifact produced from state.

For document workflow:

```text
State
  -> markdown document
```

Do not confuse Export with View.

```text
View = reasoning input
Export = user-facing output
```

## Minimal near-term behavior

The markdown file itself can be the export.

If state is represented separately, the markdown file is still the output the user cares about.

## LLM-agent version

Later export targets may include:

```text
markdown
docx
pdf
json summaries
```

Not now.

## Hardening actions

1. Export only markdown first.
2. Ensure output file is stable and readable.
3. Ensure rerunning the loop does not corrupt it.
4. Keep workspace output out of git unless explicitly promoted.

## Done when

The framework produces a real markdown document that improves across loop iterations.

---

# 9. Loop Control

## Role in the loop

Loop control decides whether to run another iteration.

For now, keep it simple.

```text
run until:
  no update proposed
  update rejected
  max_iterations reached
```

## Minimal near-term behavior

Use `max_iterations` with deterministic stopping.

Example:

```text
max_iterations=3
stop early if no update needed
```

## LLM-agent version

Later, an LLM may propose whether the task is complete.

But deterministic stop rules remain necessary.

## Hardening actions

1. Add max iteration cap.
2. Add no-op stop.
3. Print or record why loop stopped.
4. Ensure repeated runs are idempotent once complete.

## Done when

The document loop can run repeatedly and eventually stop without duplicating work.

---

# 10. Staging and Replay for Fast Testing

## Problem

Full LLM-agent runs will become slow.

If every test starts from user request and calls every agent, development will become painful.

We need staging without creating prototype chains.

## Principle

Stages are checkpoints of the real loop.

They are not alternate prototypes.

A stage captures the output of a working step so later steps can be tested quickly.

## Suggested stages

```text
Stage 0: User request fixture
Stage 1: Derived state fixture
Stage 2: View fixture
Stage 3: Progress proposal fixture
Stage 4: Game result fixture
Stage 5: Integration decision fixture
Stage 6: Update proposal fixture
Stage 7: Updated state/export fixture
```

Each stage must be generated by the real previous step at least once.

## Usage

Fast tests can start from Stage 3 to test integration.

But full spine tests must still exist:

```text
request -> export
```

## Hardening actions

1. Add fixture generation only after the real step works.
2. Store fixtures under test fixtures, not workspace.
3. Label fixtures by loop stage.
4. Add one full end-to-end test that does not use shortcuts.
5. Add many stage-level tests for speed.

## Done when

The system supports both:

```text
full slow loop test
```

and:

```text
fast stage replay tests
```

without creating parallel prototype flows.

---

# 11. LLM-Agent Introduction Plan

Do not add LLM agents everywhere at once.

Introduce agents one slot at a time.

## Order

### First LLM slot: Progressor

Reason:

The progressor is where intelligence is most naturally needed.

It decides the next useful move from the View.

Keep game/integration/update deterministic while testing this.

### Second LLM slot: Writer/Game participant

Reason:

Once the progressor can choose a missing section, a writer agent can draft the section text.

### Third LLM slot: Reviewer/Referee

Reason:

Only after deterministic safety exists should semantic review become LLM-backed.

## Required guardrails

Every LLM output must be parsed into a typed, narrow structure.

No free-form model output should directly mutate state or files.

## Hardening actions

1. Add LLM-backed progressor behind existing progressor interface.
2. Capture prompts and outputs for debugging.
3. Add deterministic fake model tests first.
4. Add optional live model smoke test later.
5. Keep deterministic structural validators after LLM output.

## Done when

One LLM agent can improve the document loop without bypassing the existing update/integration boundaries.

---

# 12. Immediate Milestone Sequence

## Milestone 1: Workspace cleanup

Ensure generated files go to workspace, not source tree.

No new abstractions.

## Milestone 2: Real document append loop

Input:

```text
request text + output markdown path
```

Output:

```text
updated markdown file
```

Behavior:

```text
append missing section once
second run does not duplicate
```

## Milestone 3: Stage fixtures

Capture intermediate loop outputs for fast testing.

## Milestone 4: LLM progressor

Replace deterministic progressor with LLM-backed progressor, keeping the rest deterministic.

## Milestone 5: LLM writer

Let an LLM write the actual section body.

## Milestone 6: LLM reviewer

Let an LLM critique the proposed update, but keep deterministic safety checks.

---

# 13. Non-Goals For Now

Do not build these yet:

```text
multi-project scheduler
legal-doc soup
OCR pipeline
software patch workflow
Git integration
capability registry
self-extending agents
blackboard replay system
multi-agent swarm
rich artifact adapter framework
```

These may matter later.

They do not harden the current document loop today.

---

# 14. Core Rule

Every new class, function, command, or concept must answer:

```text
Which step of the core loop does this improve?
```

If the answer is unclear, do not add it.

Current focus:

```text
harden the document loop until it can actually produce useful documents
```
