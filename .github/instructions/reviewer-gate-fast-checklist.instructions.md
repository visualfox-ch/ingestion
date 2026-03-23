---
description: "Use when finalizing recommendations, reviews, handoffs, task outcomes, or go/no-go decisions. Enforce a fast anti-overengineering quality gate."
---

# Fast Reviewer Gate (30s)

Use this as a final go/no-go gate before publishing a recommendation.

## Checklist

1. Problem fit: Is the concrete problem and success criterion explicit?
2. Best practice anchor: Is at least one established pattern or standard named?
3. Minimality: Is the recommended option the smallest viable path?
4. Evidence clarity: Are evidence and assumptions clearly separated?
5. Operability: Are runtime, test, and maintenance costs stated?

## Decision Rule

- 5/5 YES: GO
- 4/5 YES: GO only with explicit risk note
- <=3/5 YES: NO-GO, revise recommendation

## Output Stub

```text
Fast Reviewer Gate: GO|NO-GO
Checklist Score: X/5
Risk Note: [none or one line]
```