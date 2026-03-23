---
description: "Use when discussing architecture, system design, abstractions, service boundaries, framework choices, refactoring structure, or long-term design tradeoffs. Enforce simple architecture, anti-overengineering, and operational pragmatism."
---

# Architecture Guidelines

Apply these rules whenever the task is about architecture or structural design.

- Prefer the simplest architecture that satisfies the current requirements.
- Treat every new layer, service, framework, queue, abstraction, or indirection as a cost that must be justified.
- Default to boring, established patterns over novel design unless there is a measurable reason not to.
- Prefer extending the current architecture over introducing parallel systems.
- Prefer reversible changes over irreversible platform commitments.

Architecture decisions must explicitly answer:

1. What concrete problem is this design solving now?
2. Why is the current structure insufficient?
3. What is the smallest structural change that solves it?
4. What operational burden does the design add?
5. What testing, observability, and maintenance burden does it add?
6. Why is this better than the next simpler design?
7. Does this introduce speculative future-proofing without present evidence?

Default architecture preferences:

- Monolith extension over premature service split.
- Clear module boundaries over extra infrastructure.
- Existing tooling over new platform dependencies.
- Explicit, local logic over generalized abstractions too early.

If uncertain, recommend the smaller architecture step first and define how to validate whether a larger redesign is actually needed.