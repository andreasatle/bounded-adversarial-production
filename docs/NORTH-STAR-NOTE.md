A useful way to think about the north-star document is that it defines “north,” not the exact path to travel.

The planner is responsible for proposing bounded tasks/games that maximize expected movement toward the north star. However, the planner must not silently invent missing intent. If the planner determines that the best candidate task is weakly grounded, ambiguous, or unsupported by the current north-star document, this should be treated as evidence that the north star is underspecified rather than permission for autonomous goal mutation.

In such cases, the system should emit:

* grounding warnings,
* clarification requests,
* or proposed amendments to the north-star document.

This creates an explicit feedback loop between:

* directional intent,
* operational planning,
* and detected underspecification.

The north-star document should therefore evolve over time through reviewed amendments, while remaining aspirational and directional rather than degrading into a rigid implementation checklist.
