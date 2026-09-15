# OptiStock AI Review Policy

Version date: August 30, 2026

This document guides an agent or human reviewer when deciding whether a replenishment proposal should move forward for approval.

## How to use this policy

- Treat tool outputs as authoritative evidence.
- Do not invent stock, sales, vendor, timing, or budget facts.
- Use the policy to interpret the evidence, not to replace it.
- If evidence is missing, stale, contradictory, or insufficient, prefer blocking or asking for revision over making assumptions.

## Required evidence before review

- Product lookup for the requested SKU
- Latest inventory snapshot for the SKU and warehouse
- Sales velocity for the SKU and warehouse
- Stock risk result based on the selected target cover
- Active vendor offers
- Vendor performance metrics
- Budget position for the warehouse and budget month

## Review questions

1. Is the inventory snapshot still fresh enough to trust?
   The current working threshold in this project is 2 days.

2. Is the SKU actually at risk?
   If the risk result says coverage is healthy, do not push the case into vendor selection.

3. Is the sales evidence sufficient?
   If the sales tool reports insufficient data, stop and ask for manual review or more data.

4. Are there any valid vendor options?
   Ignore expired offers and vendors that do not meet the reliability bar.

5. Which tradeoff is being made?
   The reviewer should be able to explain whether the recommendation favors:
   - lowest cost
   - fastest arrival
   - a balanced option that still arrives on time

6. Does the proposed arrival beat the projected stockout date?
   If not, the recommendation should normally be blocked or explicitly escalated as an exception.

7. Does the proposed cost fit the remaining monthly budget?
   If not, the case should usually be blocked or clearly flagged for exception handling.

8. Is the proposal grounded in evidence IDs?
   A human approver should be able to trace every key fact back to tool evidence.

## Approval guidance

- Approval must be explicit and tied to the exact proposal version.
- Human feedback may approve, reject, or request revision.
- A revision should produce a new proposal version rather than silently changing the old one.

## Execution guidance

- After approval, revalidate the proposal before any write.
- If stock freshness, vendor validity, or budget position changed materially, invalidate the approval and return the case for review.
- Use idempotency to prevent duplicate purchase requests.

## Recommended reviewer language

- `NO_ACTION`: Current stock coverage is healthy; no replenishment recommendation needed.
- `BLOCKED`: The case cannot proceed because evidence is stale, missing, insufficient, or operationally infeasible.
- `AWAITING_APPROVAL`: The proposal is grounded, understandable, and ready for a named human approver.
- `NEEDS_INFORMATION`: More input or clarification is required before a reliable recommendation can be made.
