# Optimization Analogy for the Adversarial Production Loop

This system can be viewed as an optimization process, although it differs from classical numerical optimization in important ways.

The system does not optimize a numeric vector directly. Instead, it iteratively improves a complex project state using bounded LLM-driven evaluations and controlled state updates.

---

# Core Loop

```text
State
    ->
ProjectStateView
    + NorthStar
    ->
LLM Planner
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

The loop repeats continuously.

---

# 1. State

`State` is the durable source of truth for the project.

Examples:

* git repository
* markdown documents
* architecture docs
* test suite
* artifacts
* blackboard/event log
* discrepancy records
* accepted architectural decisions

The state may be large, heterogeneous, and partially non-textual.

The system never reasons directly over the entire state.

---

# 2. ProjectStateView

`ProjectStateView` is an LLM-readable projection of `State`.

Examples:

* `ARCHITECTURE.md`
* summarized test results
* accepted capabilities
* unresolved discrepancies
* module summaries
* dependency graphs rendered as text
* architectural projections

The projection should:

* be bounded
* be textual
* expose the most relevant information for reasoning
* avoid overwhelming the LLM context window

The projection is derived from `State`.

It is not itself authoritative.

---

# 3. NorthStar

`NorthStar` is the aspirational directional target for the project.

It is intentionally different from a TODO list.

The north star should describe:

* desired properties
* architectural goals
* system behavior
* quality constraints
* long-term direction

The north star may evolve over time, but should remain relatively stable and directional.

Examples:

* “The system should robustly resist prompt injection.”
* “Agent interactions should be replayable and auditable.”
* “The framework should converge toward secure and bounded behavior.”

The north star acts similarly to an objective function in optimization.

---

# 4. Discrepancy Estimation

The planner conceptually evaluates:

```text
Discrepancy = NorthStar - ProjectStateView
```

This is not a numeric subtraction.

Instead, the LLM attempts to estimate:

* what is missing
* what is inconsistent
* what is weakly implemented
* what is drifting
* what risks violating the north star

This discrepancy estimation acts similarly to a residual in optimization.

---

# 5. Planner

The planner consumes:

```text
NorthStar + ProjectStateView
```

and emits:

```text
GameRequest
```

The planner attempts to choose:

> the bounded next move most likely to reduce the discrepancy.

This is analogous to choosing a descent direction in optimization.

However:

* the planner is heuristic
* the planner is probabilistic
* the planner is non-convex
* the planner has incomplete information

The planner does not directly mutate state.

---

# 6. GameRequest

`GameRequest` defines a bounded evaluation task.

Examples:

* investigate a discrepancy
* attempt an architectural improvement
* validate a security property
* test an implementation claim
* pressure-test a subsystem

A game request should remain bounded in scope.

---

# 7. Game

The game is a bounded adversarial evaluation mechanism.

Typical roles:

* blue team
* red team
* referee

The game does not directly update `State`.

Instead, it produces evidence and proposals.

The game is analogous to a local search/evaluation step in optimization.

---

# 8. GameResponse

`GameResponse` summarizes the outcome of the game.

Examples:

* accepted locally
* rejected locally
* unresolved discrepancy
* proposed architectural change
* evidence
* findings
* suggested updates

The response is still non-authoritative.

It represents local evaluation output only.

---

# 9. StateUpdateProposal

A `GameResponse` may produce a `StateUpdateProposal`.

This is a proposed patch against part of the durable `State`.

Examples:

* add accepted capability
* resolve discrepancy
* supersede architectural decision
* patch a document
* update a repo artifact

The proposal affects only a subset of the state.

The proposal itself is still non-authoritative.

---

# 10. IntegrationDecision

The integration layer determines whether a proposed update should affect the durable state.

Possible outcomes:

* accept
* reject
* defer

This acts similarly to a trust/convergence gate.

The integrator attempts to determine:

> Does this move the project closer to the north star?

Only accepted updates modify `State`.

---

# Similarities to Optimization

The analogy is useful because the system behaves similarly to iterative optimization:

| Optimization               | Framework                    |
| -------------------------- | ---------------------------- |
| Objective function         | NorthStar                    |
| Current point              | ProjectStateView             |
| Residual/error             | Discrepancy estimation       |
| Gradient/descent direction | Planner-selected GameRequest |
| Local evaluation step      | Game                         |
| Step acceptance            | IntegrationDecision          |
| State update               | Accepted StateUpdateProposal |

---

# Important Differences from Classical Optimization

This is not standard numerical optimization.

Differences include:

* state is symbolic and textual
* discrepancy estimation is heuristic
* gradients are implicit and LLM-estimated
* the state space is non-convex and evolving
* the objective function itself may evolve
* evaluation is adversarial and probabilistic
* projections are lossy summaries of state

The system is therefore closer to:

* heuristic search
* adversarial planning
* iterative refinement
* bounded directional convergence

than to pure gradient descent.

# Amendments
## NorthStar as Part of State

The `NorthStar` is considered part of the durable project `State`.

This is important because it allows the system to treat north-star amendments using the same generalized update mechanism as other state changes, rather than introducing a separate amendment architecture.

Conceptually:

```text
State
- NorthStar
- repository
- documents
- event log
- accepted decisions
- discrepancies
- artifacts
- other project state
```

`ProjectStateView` may contain all or selected parts of the `NorthStar`, depending on the projection used for planning or evaluation.

This means that the system may reason about the `NorthStar` using the same adversarial game mechanisms used elsewhere in the framework.

For example:

```text
GameRequest
    ->
GameResponse
    ->
StateUpdateProposal(target=NorthStar)
```

However, the ability to propose a `NorthStar` amendment does not imply the authority to apply it.

---

## Human Approval Requirement for NorthStar Updates

Although the `NorthStar` is part of `State`, updates to the `NorthStar` require explicit human approval before integration.

The system may:

* detect underspecification,
* identify contradictions,
* discover drift,
* or propose refinements to the `NorthStar`.

However, autonomous modification of the project direction is intentionally restricted.

Conceptually:

```text
GameResponse
    ->
StateUpdateProposal(target=NorthStar)
    ->
IntegrationDecision(defer_for_human_approval)
    ->
human approval/rejection
    ->
State update only if approved
```

This creates an important authority boundary:

* the system may propose directional changes,
* but humans retain authority over the project’s long-term intent.

This helps prevent:

* uncontrolled goal drift,
* recursive self-redefinition,
* accidental objective corruption,
* and hidden prompt-level goal mutation.


## Separation Between State and Blackboard

A critical architectural distinction in the framework is the separation between:

```text id="1fyl0z"
State
```

and:

```text id="9j0xej"
Blackboard
```

Although both are durable, they represent fundamentally different concepts.

---

## State

`State` represents the evolving project artifact(s) that constitute the actual end product of the system.

Examples:

Coding project:

```text id="0y69qn"
State
- git repository
- NorthStar
```

Document-generation project:

```text id="pj3xsu"
State
- markdown document
- supporting assets
- NorthStar
```

The state is therefore the thing the system is attempting to improve over time.

The `NorthStar` is considered part of `State` because it represents part of the durable project definition and intended direction of the artifact itself.

Conceptually:

```text id="qpmjlwm"
State
- NorthStar
- implementation artifacts
- documents
- repository contents
- accepted durable project material
```

---

## Blackboard

The `Blackboard` is not the end product.

Instead, it acts as a process substrate and audit/history layer.

Examples:

```text id="xjlwm6"
Blackboard
- game history
- reasoning traces
- findings
- evaluations
- reviews
- rejected proposals
- integration decisions
- audit events
```

The blackboard may grow indefinitely and contains historical and coordination-oriented information.

Importantly:

```text id="mgt95v"
Blackboard != State
```

The blackboard stores process history, not the evolving artifact itself.

---

## Relationship Between State and Blackboard

The framework may use blackboard information to:

* audit decisions,
* explain provenance,
* replay reasoning,
* inspect historical behavior,
* or derive additional projections.

However, the blackboard should not be confused with the current project artifact.

Conceptually:

```text id="6f2z9s"
ProjectStateView = projection(State)
```

not:

```text id="xxi1an"
projection(Blackboard)
```

unless historical reasoning is intentionally included.

This separation helps avoid:

* contaminating the product state with process traces,
* uncontrolled growth of planning context,
* accidental coupling between reasoning history and artifact state,
* and semantic confusion between “what the project currently is” and “how the system arrived there.”
