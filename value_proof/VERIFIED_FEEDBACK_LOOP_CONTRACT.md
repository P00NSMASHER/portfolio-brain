# Verified Value Feedback Loop — Step 8

Step 8 closes the loop:

`Hunter finding -> governed model task -> independent verification -> VERIFIED value outcome -> Hunter strategy feedback + model-routing feedback`.

## Admission gate

Feedback is admitted only when the value outcome is `VALUE_OUTCOME_VERIFIED`, has `evidence_state=VERIFIED`, is decision-useful, and preserves all rights, deployment, authority, customer-value, and capability-verification boundaries.

The feedback loop revalidates builder and verifier provider receipts, exact task/finding/repository/revision lineage, and builder/verifier independence before learning state may change.

## Hunter learning

A stable feedback key prevents repeated executions of the same task/finding lineage from generating duplicate strategy credit.

Only VERIFIED useful outcomes increment `verified_value_outcomes`. Exploit strategies are ordered by that verified outcome count while the protected exploration slot remains intact. Search volume, stars, model confidence, and unverified activity do not increase strategy priority.

## Model-routing learning

Builder and verifier calls are recorded separately with sanitized call receipts and VERIFIED technical feedback. Task-specific summaries track verified outcome count, mean verified outcome value, and mean cost per verified outcome.

Feedback may reorder already-eligible models **within the required tier only**. It cannot:
- cross the deterministic/model tier selected by the task contract,
- bypass data, token, cost, provider allowlist, or independence gates,
- grant authority,
- upgrade evidence,
- claim customer value.

If no validated durable feedback exists, routing remains deterministic lowest-configured-cost selection within the required tier.

## Persistence and idempotency

Hunter learning and model-routing feedback are restored from validated GitHub Actions artifacts. Feedback keys are stable across reruns, so repeating the same proof does not create additional value credit.

The checked-in seeds remain empty; only runtime VERIFIED evidence can populate durable learning state.
