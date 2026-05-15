## Prompt Injection and Authority Boundaries

BAPS should assume that all retrieved or generated text may contain adversarial or misleading instructions.

Potential sources include:
- repository files
- architecture documents
- state-source content
- generated summaries
- artifact proposals
- discrepancy reports
- prior agent outputs

Prompt injection should be treated primarily as an authority-boundary problem rather than a prompting problem.

Untrusted text must not:
- mutate goals
- modify accepted state
- alter authority semantics
- approve integration outcomes
- change budgets or execution constraints
except through explicit validated governance paths.

Core principle:
All retrieved/generated content is untrusted evidence, not authority.

Authority transitions must occur only through:
- validated schemas
- explicit lifecycle events
- approved integration/governance paths
- durable append-only audit history

The framework should preserve explicit separation between:
- instructions
- evidence
- proposals
- accepted state
- governance authority

As the system evolves toward richer retrieval, planning, and tool usage, prompt injection resistance should remain a core architectural concern.

## Current Boundary Map (Code-Accurate)

Current implementation boundaries are intentionally narrow and schema-first:

- State-source content is injected into prompts as raw text context via `resolve_state_context(...)` and prompt templates.
- Model outputs are treated as untrusted text unless they successfully cross explicit schema parsing boundaries.
- Planner model output becomes execution intent only when it validates as `GameRequest`.
- Role outputs are parsed into `Move` / `Finding` / `Decision` with bounded field extraction and deterministic fallbacks.
- Referee decision authority is local/deterministic in code (`reject|revise|accept` computed before rationale generation); generated rationale text does not choose the decision.

This means current code treats retrieved/generated content primarily as evidence-shaped input to bounded parsers, not direct authority to mutate governance state.

## Current Gaps (Known)

- Prompt construction includes untrusted text verbatim (state-source content, model-produced summaries/claims from prior rounds).
- `LLMPlanner` accepts any schema-valid `GameRequest`; grounding to specific discrepancy IDs or north-star principles is not yet enforced.
- `GameRequest.state_source_ids` from planner output are only validated for shape (non-empty strings), not policy/authority class at planner boundary.

These gaps should be addressed through additive governance semantics, not hidden prompt-only heuristics.
