# Goal Documents and Directional Convergence

The framework is intended to support directional convergence toward high-level project goals rather than strict deterministic completion of predefined pipelines.

A user-provided goal document acts as a long-term directional target ("north star") for the system.

The goal document may describe:

- project intent
- architectural direction
- invariants
- requirements
- quality expectations
- operational constraints
- desired behaviors
- long-term objectives

The framework is not expected to perfectly converge to the goal document in a finite number of games.

Instead, games should attempt to produce monotone improvement toward the goal state.

---

# Relationship Between Games and Goal Documents

Individual games are local bounded optimization/validation steps.

A game does not attempt to solve the entire project globally.

Instead:

- the sponsor derives bounded game contracts from the goal document
- games attempt to improve some scoped aspect of the project
- the integrator evaluates whether game outcomes move the system closer to the directional goal

This allows the framework to evolve incrementally while maintaining long-term directional coherence.

---

# Goal Documents Are Durable Guidance

The goal document is intended to be more stable than individual implementations.

Implementations may evolve substantially over time while the higher-level project direction remains relatively stable.

This supports the idea that:

- code may become partially disposable/regeneratable
- project intent and constraints remain durable

---

# Goal Documents Are Not Absolute Truth

The goal document itself may evolve.

The framework may eventually support:

- suggestions to refine the goal document
- detection of internal contradictions
- identification of underspecified areas
- architectural pressure feedback

However:

- goal-document modification should be treated as a higher-authority operation
- individual games should not directly rewrite global project goals

---

# Direction Over Perfection

The framework optimizes for bounded directional improvement rather than perfect final artifacts.

Game outcomes should be evaluated by whether they move the system closer to the intended project direction under current constraints and budgets.