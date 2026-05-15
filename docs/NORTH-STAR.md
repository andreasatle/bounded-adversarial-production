# NORTHSTAR.md

## Purpose

BAPS exists to create a framework for iterative autonomous project evolution through bounded adversarial evaluation and controlled state updates.

The framework should continuously move a project toward its intended direction while preserving:

* auditability,
* bounded authority,
* adversarial pressure,
* and human control over long-term intent.

The system is intended to operate on arbitrary project artifacts, including:

* software repositories,
* document collections,
* structured knowledge bases,
* or other evolving project states.

---

# Core Philosophy

The framework should behave similarly to an optimization loop, although operating over symbolic and textual project state rather than numeric vectors.

Conceptually:

```text id="0m71vf"
NorthStar + ProjectStateView
    ->
planner
    ->
GameRequest
    ->
Game
    ->
GameResponse
    ->
StateUpdateProposal
    ->
IntegrationDecision
    ->
State
```

The system should continuously attempt to reduce the discrepancy between:

* the current project state,
* and the intended project direction described by the `NorthStar`.

The system should never assume convergence is complete.

The project should remain continuously evolvable.

---

# State

`State` is the durable evolving project artifact.

Examples:

* git repositories,
* documents,
* extracted datasets,
* architecture specifications,
* generated assets.

The framework exists to iteratively improve the `State`.

The `State` is the primary object of optimization.

The `NorthStar` is considered part of the `State`.

---

# Blackboard

The `Blackboard` is distinct from the `State`.

The blackboard is:

* process memory,
* audit history,
* reasoning trace,
* coordination substrate,
* and provenance layer.

The blackboard may contain:

* game history,
* evaluations,
* rejected proposals,
* reasoning traces,
* findings,
* integration decisions,
* and historical records.

The blackboard is not the end product.

The framework must preserve a strong separation between:

* product state,
* and process history.

---

# ProjectStateView

`ProjectStateView` is a bounded textual projection of the `State` used for LLM reasoning.

The framework should support multiple projections depending on context and task.

Examples:

* architecture summaries,
* discrepancy summaries,
* test summaries,
* selected source excerpts,
* dependency summaries,
* document summaries.

The projection should:

* remain bounded,
* remain readable,
* expose relevant structure,
* and avoid overwhelming reasoning context.

The projection is derived from the `State`.

It is not authoritative.

---

# Games

Games are bounded adversarial evaluation mechanisms.

Games exist to:

* investigate discrepancies,
* pressure-test proposals,
* challenge assumptions,
* evaluate architectural decisions,
* detect drift,
* identify weaknesses,
* and explore bounded local improvements.

Games do not directly mutate `State`.

Games produce:

* evidence,
* findings,
* evaluations,
* and proposed updates.

---

# Planner

The planner should continuously attempt to identify the bounded next move most likely to move the project toward the `NorthStar`.

The planner should reason over:

* `NorthStar`,
* `ProjectStateView`,
* discrepancies,
* and historical context where appropriate.

The planner should avoid:

* conversational drift,
* local optimization obsession,
* and arbitrary task generation disconnected from the `NorthStar`.

The planner is directional, not authoritative.

---

# State Updates

State updates are proposed, not directly applied.

All state mutation should occur through explicit update proposals and integration decisions.

The framework should support updates against arbitrary parts of the `State`.

Examples:

* repository patches,
* document amendments,
* discrepancy resolution,
* accepted architectural changes,
* capability additions,
* `NorthStar` amendments.

Only accepted updates may mutate the durable `State`.

---

# Integration

Integration acts as the authority gate between:

* proposed updates,
* and durable project mutation.

The integration layer should evaluate:

* whether a proposal moves the project toward the `NorthStar`,
* whether the proposal is sufficiently grounded,
* whether the proposal violates architectural or authority boundaries,
* and whether sufficient evidence exists.

Integration decisions may:

* accept,
* reject,
* defer,
* or escalate for human approval.

---

# Human Authority

The framework is intended to minimize required human involvement in ordinary project evolution.

The human role should primarily consist of:

* defining the initial `NorthStar`,
* reviewing and approving/rejecting `NorthStar` amendments,
* defining high-level environmental constraints,
* and supervising catastrophic or ambiguous situations when necessary.

Ordinary bounded project evolution should be performed autonomously by the system.

The framework should therefore preserve a strict boundary between:

* autonomous project optimization,
* and human control over long-term intent.

---

# NorthStar Amendments

The framework may propose amendments to the `NorthStar`.

This is necessary because:

* projects evolve,
* understanding improves,
* contradictions emerge,
* and underspecification may be discovered during optimization.

However:

* autonomous agents may propose `NorthStar` updates,
* but only humans may authorize them.

This boundary exists to prevent:

* uncontrolled goal drift,
* recursive objective corruption,
* hidden prompt-level mutation of intent,
* and accidental redefinition of project purpose.

---

# Adversarial Pressure

The framework should preserve adversarial pressure at multiple levels.

The system should continuously attempt to:

* challenge assumptions,
* expose weaknesses,
* discover edge cases,
* identify inconsistencies,
* and prevent ungrounded convergence.

The system should prefer:

* bounded skepticism,
* explicit evidence,
* and replayable reasoning
  over:
* opaque confidence,
* hidden assumptions,
* or unchallenged conclusions.

---

# Long-Term Goal

The long-term goal of BAPS is to create a framework capable of:

* autonomous bounded project evolution,
* adversarial self-improvement,
* durable auditability,
* controlled state mutation,
* and directional convergence toward human-defined intent,
  without requiring continuous human micromanagement.
