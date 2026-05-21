You are documenting the normative system contract for an existing Python project called:

bounded-adversarial-production
(package name: baps)

Your task is to create or replace:

docs/SYSTEM.md

Purpose:
SYSTEM.md defines the REQUIRED operational semantics, boundaries, invariants, and anti-invariants of the current canonical runtime.

ARCHITECTURE.md documents implementation.

SYSTEM.md defines what must remain true.

Constraints:

- DO NOT redesign architecture
- DO NOT rename concepts
- DO NOT invent features
- DO NOT describe conceptual systems as active
- preserve current terminology
- preserve current boundaries
- document observations instead of changing behavior
- align strictly with actual code and canonical runtime
- SYSTEM.md must be shorter and more normative than ARCHITECTURE.md

Canonical runtime:

config/NorthStar
-> State
-> StateView
-> CreateGame
-> GameSpec
-> PlayGame
-> DeltaState
-> StateUpdateProposal
-> StateService
-> export

Treat this as authoritative unless code proves otherwise.

Required structure:

# Purpose

Explain:

ARCHITECTURE.md
    implementation evidence

SYSTEM.md
    normative contract

SYSTEM.md defines required semantics.

---

# 1. Canonical Spine

Document canonical runtime:

config/NorthStar
-> State
-> StateView
-> CreateGame
-> GameSpec
-> PlayGame
-> DeltaState
-> StateUpdateProposal
-> StateService
-> export

State explicitly:

This is the only active lifecycle execution path:

init
run
init_and_run

Do not include inactive systems here.

---

# 2. Core Invariants

Document ONLY invariants that are either:

implemented
or
mandatory system contracts

Expected examples:

1. State is authoritative project condition.
2. State persists as JSON.
3. StateView is model-facing text.
4. JSON is storage/transport, not StateView content.
5. NorthStar belongs to State.
6. Project behavior lives behind ProjectTypeAdapter.
7. Core orchestration remains project-type generic.
8. CreateGame is State/NorthStar aware.
9. PlayGame is GameSpec bound.
10. StateService is mutation boundary.
11. Export is one-way.
12. Prompts consume StateView only.

Add only if code/system supports them.

---

# 3. Adapter Contract

Document ProjectTypeAdapter responsibilities.

Expected ownership:

initial state creation

CreateGame StateView rendering

PlayGame StateView rendering

project prompt supplements

delta parsing

delta -> StateUpdateProposal mapping

export

State:

core orchestration remains generic.

---

# 4. Active Project Types

Document active registered types.

Examples:

document
coding

State equality of participation.

Do not privilege one type.

---

# 5. Blackboard Status

Document actual status.

If inactive:

state explicitly.

Expected contract:

blackboard is not canonical runtime state.

If reintroduced:

append-only history/meta only

never authoritative state

Document observations separately.

---

# 6. Anti-Invariants (Forbidden Drift)

Document forbidden architectural drift.

Expected examples:

Do not pass State JSON as StateView.

Do not place project-specific logic in core orchestration.

Do not bypass ProjectTypeAdapter.

Do not parse English semantics as validator authority.

Do not make output files canonical state.

Do not introduce competing runtimes.

Do not expose authoritative State internals to prompts.

Provide concrete examples where useful.

Explain historical motivation if known.

---

# 7. Authority and Boundaries

Document authority hierarchy.

Expected examples:

model outputs are proposals

state changes happen only through StateService

export materializes state

export never defines state

accepted integration required before mutation

Document actual authority model.

---

# 8. System Alignment Rules

Verify:

State != StateView

core != adapter

export != state

prompt context == StateView

blackboard != authority

Document any mismatch as observation.

---

Requirements:

Keep concise.

Normative style.

No implementation deep dive.

No hype.

No future architecture proposals.

No redesign.

After writing:

run:

uv run pytest

Return:

summary

files updated

exact test result

observations

contract ambiguities