You are documenting an existing Python project called "bounded-adversarial-production" (package name: baps).

Your task is to produce a THOROUGH technical architecture and developer documentation pass for the repository.

Goals:
- create a durable understanding of the project
- reduce dependency on tribal knowledge
- make future additive development easier
- preserve architectural continuity
- help future agents/humans understand the system quickly

Important constraints:
- DO NOT redesign the project
- DO NOT change architecture
- DO NOT rename concepts
- documentation only
- if you discover inconsistencies, document them as "observations" rather than changing behavior
- preserve current terminology and current system boundaries

Create or replace the file:
- docs/ARCHITECTURE.md

The documentation should be highly technical and explicit.

Document the ACTUAL codebase, not an imagined future architecture.

The document must include the following sections:

# 1. Project Overview
- purpose of the framework
- current project philosophy
- current architectural direction
- what "bounded adversarial production" means in practice
- distinction between current implementation and future aspirations

# 2. Current System Capabilities
Describe exactly what currently exists and works:
- schemas
- blackboard
- artifacts
- runtime
- roles
- prompt rendering
- model abstraction
- Ollama integration
- deterministic testing
- demo game execution

For each subsystem:
- purpose
- important classes/functions
- current limitations
- relationships to other modules

# 3. Repository Structure
Provide a directory/module map.

For every important module:
- purpose
- major classes/functions
- dependencies
- responsibility boundaries

# 4. Core Runtime Flow
Describe step-by-step:
- how a game executes
- how roles are invoked
- how prompts are rendered
- how model calls happen
- how runtime state is persisted
- how blackboard events are recorded
- how artifacts interact with runtime

Use explicit sequence-style explanations.

# 5. Schema Documentation
Document all important Pydantic models:
- fields
- invariants
- validation behavior
- relationships between schemas

Explain WHY each schema exists.

# 6. Blackboard/Event System
Document:
- append-only philosophy
- event persistence
- event querying
- event lifecycle
- intended future role of the blackboard

Describe current implementation precisely.

# 7. Artifact System
Document:
- artifact lifecycle
- adapters
- snapshots
- metadata
- handler delegation
- filesystem structure

Explain current assumptions and constraints.

# 8. Runtime Engine
Document:
- runtime responsibilities
- role invocation guard
- retry behavior
- game execution model
- current deterministic execution approach

# 9. Roles and Prompt System
Document:
- deterministic example roles
- prompt-driven roles
- PromptRenderer
- FakeModelClient
- OllamaClient
- role execution flow

Include current limitations:
- no tool system yet
- no true multi-agent adversarial loop yet
- etc.

# 10. Testing Strategy
Document:
- current testing philosophy
- deterministic testing approach
- fake model usage
- validation testing
- runtime testing
- artifact testing

Explain WHY deterministic tests are important in this architecture.

# 11. Architectural Invariants
Document only invariants that ACTUALLY appear enforced by the codebase.

Examples may include:
- append-only blackboard
- additive evolution preference
- validated schemas
- deterministic tests
- explicit runtime boundaries

DO NOT invent theoretical invariants not reflected in code.

# 12. Current Architectural Direction
Describe where the project appears to be heading based on the code:
- bounded adversarial games
- role interaction
- referee-style evaluation
- future tool integration
- future pipeline generation
- future self-inspection

Clearly separate:
- implemented
vs
- conceptual/future

# 13. Current Limitations
Be honest and concrete:
- what is stubbed
- what is deterministic/fake
- what is missing
- where orchestration is incomplete
- what would be needed for a true adversarial game loop

# 14. Suggested Next Milestones
Based ONLY on the current architecture.

Prefer additive milestones.

Do not propose breaking redesigns.

Focus on:
- isolated adversarial game loop
- multi-role interaction
- findings/decisions
- tool request boundary
- referee behavior

# 15. Developer Workflow
Document:
- how tests are run
- how commits appear structured
- additive development philosophy
- expected workflow for future contributors/agents

# 16. Glossary
Define project terminology precisely:
- game
- role
- move
- finding
- decision
- artifact
- blackboard
- runtime
- prompt renderer
- model client
- etc.

Requirements:
- extremely concrete
- no fluff
- no motivational language
- no speculative hype
- no invented features
- prefer explicitness over brevity
- include code snippets where useful
- include filesystem examples where useful
- include execution flow examples where useful

After writing the documentation:
- run all tests
- ensure documentation matches actual repository state
- list any ambiguities or uncertainties explicitly

Run:

uv run pytest

Return:
- summary of documentation generated
- files created/updated
- exact test result
- any architectural ambiguities discovered