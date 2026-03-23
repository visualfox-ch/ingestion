---
description: "Use when discussing refactoring, code cleanup, structural simplification, module extraction, deduplication, naming cleanup, or maintainability improvements. Enforce minimal refactors, anti-overengineering, and pragmatic change scope."
---

# Refactoring Guidelines

Apply these rules whenever the task is about refactoring or structural cleanup.

- Prefer the smallest refactor that materially improves clarity, correctness, or maintainability.
- Do not generalize code before repeated need is demonstrated.
- Avoid refactors that widen scope without a clear payoff.
- Keep public APIs, runtime behavior, and operational workflows stable unless change is explicitly required.
- Prefer local simplification over broad architectural churn.

Refactoring decisions must explicitly answer:

1. What concrete problem in the current code is being fixed?
2. What is the smallest safe change that improves it?
3. Does the refactor reduce duplication, complexity, or defect risk in a measurable way?
4. What new abstraction, indirection, or coupling does the refactor introduce?
5. Why is this better than leaving the code as-is or making a smaller cleanup?
6. What tests or validations prove behavior stayed correct?

Default refactoring preferences:

- Remove duplication only when the shared abstraction stays simpler than the duplicated code.
- Extract helpers only when they improve readability or reuse without hiding important context.
- Rename for clarity, not style churn.
- Split modules only when responsibilities are actually mixed.
- Prefer deleting dead code over wrapping it in new abstractions.

If uncertain, recommend the narrower cleanup first and defer broader refactors until repeated pain is validated.