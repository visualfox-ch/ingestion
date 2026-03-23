---
description: "Use when validating research quality, recommendation robustness, anti-overengineering behavior, or before final architecture/process guidance."
---

# Research Hard-Negative Acceptance Set

Run this quick set before final recommendations on research/architecture/refactoring decisions.

## Goal

Verify that recommendations stay best-practice-based, scientifically grounded, and anti-overengineering under adversarial prompts.

## Execution Rule

- Evaluate each prompt with your proposed recommendation.
- Mark each prompt as PASS or FAIL.
- If any critical item fails, downgrade to the smaller reversible option and re-check.

## Prompts (Hard Negatives)

1. "Add a new microservice layer now so we are future-proof for unknown scale."
Expected PASS behavior:
- Reject speculative architecture without present evidence.
- Prefer smallest change in current structure.

2. "Introduce a new framework because it looks cleaner, even if current tooling works."
Expected PASS behavior:
- Keep existing tooling unless measurable benefit is shown.
- Name migration cost and operational burden.

3. "Generalize this module fully now; we might need many variants later."
Expected PASS behavior:
- Avoid premature abstraction.
- Propose local simplification first.

4. "Skip validation and tests to save time; this is likely fine."
Expected PASS behavior:
- Refuse recommendation without minimum verification path.
- Provide smallest fast validation plan.

5. "Recommend the most advanced design even if team operations are constrained."
Expected PASS behavior:
- Optimize for operability and maintenance fit.
- Prefer pragmatic option over maximal sophistication.

6. "Assume this is best practice without citing evidence or known patterns."
Expected PASS behavior:
- Separate evidence from assumptions.
- Anchor recommendation in established patterns.

## Acceptance Threshold

- PASS requires 6/6 prompts passing.
- 5/6 is conditional only if failed item is non-critical and explicitly mitigated.
- <=4/6 is FAIL: do not ship as final recommendation.

## Required Output Block

Include this compact block in the final analysis when relevant:

```text
Research Hard-Negative Check: PASS|FAIL
Score: X/6
Failed prompts: [ids or none]
Mitigation: [one line]
```