## Immediate High-Leverage TODO Queue

Ordered approximately by architectural leverage, not implementation ease.

---

# 1. Artifact Mutation Integration

Current gap:

```text id="jlwmcy"
games reason about artifacts
but do not mutate artifacts
```

Need:

* runtime -> artifact proposal linkage
* accepted integration -> apply artifact change
* rejected integration -> preserve proposal only

This is probably the single biggest missing “real-world effect” layer.

---

# 2. Planner Discrepancy Prompt Enrichment

Current LLM planner context is still shallow.

Need:

* richer discrepancy summaries
* artifact context
* accepted-state summaries
* active-game awareness
* bounded context windows

This directly improves autonomous planning quality.

---

# 3. Stop / Saturation Conditions

Current autonomous runner:

```text id="jlwmcz"
runs fixed step count only
```

Need:

* stop when no material discrepancies remain
* stop on repeated deferred outcomes
* stop on convergence stall
* stop on review-queue saturation

This is important before long autonomous runs.

---

# 4. Explicit Sponsor Abstraction

Current:

```text id="jllmda"
planner is partially acting as sponsor
```

Need:

* sponsor identity
* budgets
* allowed scope
* planning authority
* escalation semantics

Important authority boundary.

---

# 5. Artifact-Aware Discrepancy Remediation

Need:

```text id="jlwmdb"
discrepancy -> remediation request generation
```

Example:

* architecture drift
* missing capability
* failing invariant

should produce bounded remediation games.

---

# 6. Runtime Tool Execution Boundary

Current runtime has no real tool semantics.

Need:

* explicit tool call abstraction
* bounded execution authority
* execution audit trail
* deterministic test doubles

This is foundational for repository/code manipulation.

---

# 7. Repository Artifact Adapter

Current artifact support is mostly documents.

Need:

* repository adapter
* file snapshots
* patch proposals
* commit-like lineage semantics

Critical for real software evolution.

---

# 8. Integrator Policy Expansion

Current integrator still primitive.

Need:

* scoring
* confidence weighting
* multi-candidate ranking
* policy chains
* escalation semantics

But this is now second-order compared to artifact execution.

---

# 9. Goal/State Discrepancy Analysis

Currently:

```text id="jlwmdc"
planner reacts mostly to existing discrepancies
```

Need:

```text id="jlwmdd"
derive discrepancies automatically
from goal vs projected state
```

This is a major intelligence jump.

---

# 10. Projection Snapshots / Cached Materialization

Current:

```text id="jlwmde"
full replay projection rebuilds
```

Need:

* snapshotting
* incremental projection updates
* cached materialized state

Important before scaling event volume.

---

# 11. Convergence / Drift Metrics

Need:

* discrepancy trend tracking
* repeated-failure detection
* integration acceptance ratios
* architecture drift metrics
* progress heuristics

This eventually informs planner prioritization.

---

# 12. Review Queue Governance

Current review queue is:

```text id="jlwmdf"
list of deferred decisions
```

Need:

* escalation
* aging
* retries
* prioritization
* abandonment semantics

---

# My Recommendation for Immediate Next Focus

This cluster:

```text id="jlwmdg"
1. Artifact mutation integration
2. Repository artifact adapter
3. Runtime tool execution boundary
4. Artifact-aware remediation
```

because that transitions the system from:

```text id="jlwmdh"
reasoning framework
```

into:

```text id="jlwmdi"
acting software evolution system
```
