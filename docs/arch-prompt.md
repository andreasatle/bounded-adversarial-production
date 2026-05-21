You are documenting an existing Python project called "bounded-adversarial-production" (package name: baps).

Your task is to produce a THOROUGH technical architecture and developer documentation pass for the repository.

Goals:
- create durable project understanding
- reduce dependency on tribal knowledge
- preserve architectural continuity
- document actual implementation
- support additive development
- align architecture documentation with SYSTEM.md

Constraints:
- DO NOT redesign the project
- DO NOT rename concepts
- DO NOT change architecture
- documentation only
- preserve current terminology and boundaries
- document observations instead of changing behavior
- document IMPLEMENTED behavior separately from conceptual/future behavior

Create or replace:

docs/ARCHITECTURE.md

The document must describe the ACTUAL repository and canonical runtime.

The canonical runtime is:

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

This runtime must be treated as authoritative unless code proves otherwise.

ARCHITECTURE.md must remain aligned with SYSTEM.md.

Explicitly distinguish:

IMPLEMENTED
vs
CONCEPTUAL
vs
HISTORICAL / INACTIVE

Required sections:

# 1. Project Overview

Document:

- framework purpose
- current philosophy
- current architectural direction
- bounded adversarial production as currently implemented
- implemented vs conceptual separation

Describe actual execution behavior.

Do not infer future systems as active.

---

# 2. Current System Capabilities

Document exactly what exists:

Schemas:
- State
- NorthStar
- artifacts
- deltas
- GameSpec
- decisions
- update proposals

Runtime:
- lifecycle commands
- CreateGame
- PlayGame
- integration
- export

Adapters:
- document
- coding

StateView:
- projection model
- rendering rules

Model layer:
- ModelClient
- FakeModelClient
- OllamaClient

Testing:
- deterministic tests
- fake model use

For each subsystem:

- purpose
- classes/functions
- limitations
- dependencies
- responsibility boundaries

---

# 3. Repository Structure

Provide module map.

Document:

run.py
project_adapter.py
document_adapter.py
coding_adapter.py
state.py
state_service.py
state_store.py
models.py
northstar_projection.py

For each:

- purpose
- responsibilities
- dependencies
- boundaries

Explicitly separate:

core orchestration
vs
adapter mechanics

---

# 4. Canonical Runtime Flow

Describe lifecycle:

init
run
init_and_run

Describe iteration flow:

CreateGame
-> adapter CreateGame StateView
-> GameSpec

PlayGame
-> adapter PlayGame StateView
-> Blue
-> Red
-> Referee
-> DeltaState

integration
-> StateUpdateProposal
-> StateService

export

Explain sequence explicitly.

Document persistence.

Document stop conditions.

Do NOT describe inactive runtimes as active.

---

# 5. Schema Documentation

Document Pydantic models:

State
NorthStar
StateArtifact
DocumentArtifact
CodingArtifact
Section
CodeFile

GameSpec

DeltaDocumentState
DeltaCodingState

RedFinding
RefereeDecision

StateUpdateProposal
StateUpdateTarget

StateView
ProjectionType

For each:

- fields
- invariants
- validation
- relationships
- purpose

Document only code-backed invariants.

---

# 6. Blackboard Status

Document current status precisely.

Include:

- existing blackboard files
- historical role
- inactive status in canonical runtime
- separation from active lifecycle execution

If future role appears in docs:

document as observation only.

Do NOT describe blackboard as active unless code proves it.

---

# 7. Artifact System

Document:

artifact lifecycle

initialization
-> StateView rendering
-> delta parsing
-> update mapping
-> export

Document adapter ownership.

Document filesystem assumptions.

Document export behavior.

Explain constraints.

---

# 8. Runtime Engine

Document:

runtime responsibilities

bounded attempts

retry behavior

integration path

deterministic testing path

validation boundaries

Document actual execution.

Avoid speculative orchestration.

---

# 9. Roles and Prompt System

Document:

CreateGame prompt

Blue prompt flow:
- generic core
- adapter supplements

Red prompt

Referee prompt

Model layer:

ModelClient
FakeModelClient
OllamaClient

Current limitations:

- no tool execution subsystem
- no true multi-agent scheduler
- prompt-only role execution
- limited semantic validation

Do NOT describe PromptRenderer unless implemented.

Do NOT describe deterministic example roles unless implemented.

---

# 10. Testing Strategy

Document:

testing philosophy

deterministic execution

FakeModelClient

validation testing

adapter testing

runtime testing

Explain why deterministic testing matters.

Document actual coverage.

---

# 11. Architectural Invariants

Document ONLY enforced invariants.

Examples:

State authoritative JSON

StateView text projection

NorthStar inside State

adapter ownership

StateService mutation boundary

project-type generic orchestration

export one-way

validated schemas

deterministic tests

Separate:

enforced
vs
conceptual

---

# 12. Current Architectural Direction

Document observed direction:

adapter expansion

bounded games

role interaction

future tool boundaries

future blackboard reintegration

Clearly separate:

implemented
conceptual
historical

---

# 13. Current Limitations

Be concrete.

Document:

inactive blackboard runtime

prompt-only roles

limited deltas

missing tool system

missing scheduler

bounded role model

incomplete orchestration areas

---

# 14. Suggested Next Milestones

Base ONLY on current architecture.

Prefer additive steps.

Examples:

blackboard reintegration

tool boundary

adapter validation hooks

role envelopes

contract tests

Do not redesign.

---

# 15. Developer Workflow

Document:

tests

development flow

additive philosophy

boundary preservation

expected contributor workflow

---

# 16. Glossary

Define:

State
NorthStar
StateView
GameSpec
DeltaState
artifact
adapter
RedFinding
RefereeDecision
StateUpdateProposal
runtime
ModelClient
export
canonical spine

Use current meanings.

---

# System Contract Alignment

Verify alignment with SYSTEM.md.

Explicitly check:

State != StateView

prompts consume StateView only

core orchestration generic

adapter ownership preserved

export != state

blackboard inactive

Document mismatches as observations.

After writing docs:

run:

uv run pytest

Return:

- documentation summary
- files updated
- exact test result
- ambiguities
- architecture observations