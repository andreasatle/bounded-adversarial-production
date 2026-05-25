# NorthStar — baps self-improvement

This document is the NorthStar for running baps on itself. It defines direction, quality properties, and constraints for autonomous evolution of the baps framework.

---

## Direction

baps should evolve toward a framework capable of autonomous, bounded, adversarially-pressured project evolution with minimal human involvement in ordinary operation.

Priority areas for self-improvement:

- **Multiple StateView projections** — CreateGame and PlayGame currently receive monolithic views. Architecture summaries, discrepancy summaries, dependency graphs, and test coverage summaries are all valid projections that do not yet exist. Richer projections improve gap analysis quality.
- **Adapter expansion** — new project types should register adapters without touching core orchestration. The adapter contract should remain the only extension point.
- **Auditability** — every accepted state mutation should be traceable. Findings, decisions, and integration rationale should be recoverable from the blackboard.
- **Reduced human touchpoints** — anything that currently requires human intervention beyond NorthStar approval should be examined. If it can be bounded and verified autonomously, it should be.
- **Stronger contract enforcement** — boundaries between State, StateView, adapter, and core orchestration should be enforced structurally where possible, not just by convention.

---

## Quality Properties

Evolutions are good if they:

- Increase the system's ability to close gaps autonomously without increasing human involvement.
- Improve adversarial pressure — skepticism, explicit evidence, and replayable reasoning are preferred over opaque confidence.
- Add capability without bypassing the canonical spine or weakening the mutation boundary.
- Are testable: deterministic tests must cover any new boundary or contract.
- Leave the architecture more, not less, generic at the core.

---

## Constraints

These must not change through the automated pipeline:

- **NorthStar is human-controlled.** Proposals may be generated; only humans may apply them.
- **StateService is the only mutation boundary.** No evolution may introduce a second path to durable state change.
- **Core orchestration must remain project-type generic.** Project-specific logic belongs in adapters exclusively.
- **Export is one-way.** Exported files are derived output; they never become authoritative state.
- **Blackboard is non-authoritative.** It is append-only process history; it never feeds back into State.
- **Model outputs are proposals.** No role output is authoritative without integration through StateService.
