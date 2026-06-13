---
name: evaluator-shapes
description: Guides deterministic handling of Al Dente SAMPLE_QUESTIONS-style evaluator tasks, including aggregates, traps, multi-hop chains, complaint policy checks, price conflicts, and generation prompts.
---

# Evaluator Shapes

## Priority Shapes

- CRM aggregates: open opportunities, negotiation totals, grouping by customer channel.
- ERP checks: SKU inventory below minimum, BOM to raw material to supplier, shipments and production orders.
- Calls: latest call for customer, complaint defect and lot extraction, complaint counts across all calls.
- KB: shelf life, allergens, prices, quality and returns policy.
- Traps: unknown customer, unavailable profit margin, unsupported metrics.
- Generation: inline HTML decks or binary artifacts grounded in real facts.

## Deterministic First

Implement these shapes in Python before using the LLM:

1. Verify entity existence.
2. Fetch the smallest sufficient data set.
3. Page only when the question requires complete aggregates.
4. Compute counts, sums, and group-bys in code.
5. Hand computed facts to the composer.

## Trap Handling

- Unknown customer: say no matching customer exists in CRM.
- Profit margin or cost on lots: say it is not stored in the available sources.
- Missing policy, price, or spec: say the source does not contain that fact.
