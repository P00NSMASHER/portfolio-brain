# Cost Governor Contract

The cost governor is a fail-closed **financial execution boundary**. It grants no authority and does not decide what work is valuable. Its job is to prevent unbounded paid model/API execution.

GitHub-hosted workload control is intentionally separate. Non-paid reporting, Hunter, scheduler, heartbeat, notification, software-factory, and feedback workflows use `workload_control/WORKLOAD_POLICY.json`, workflow-specific concurrency lanes, GitHub timeouts, duplicate suppression, and pending-event coalescing.

## Paid pre-execution reservation

Every non-Tier-0 model/API invocation must reserve its worst-case paid usage before invocation. Active paid reservations count against the same financial ceilings as committed paid usage. Reservations use deterministic idempotency keys and retry groups.

The checked-in portfolio paid ceiling remains **USD 10 per UTC day**. Provider readiness, routing, authority, idempotency, retry, and pre-execution reservation gates must all pass independently.

Paid workflow wrappers may still record bounded GitHub-job reservations for timeout/accounting compatibility, but GitHub job starts and runner minutes are not financial ceilings and cannot consume the USD budget.

## Financial scopes

Paid model/API execution must pass every applicable scope:

1. portfolio daily paid ceiling;
2. each referenced project paid ceiling;
3. provider/model paid ceiling;
4. retry sequence and retry-count ceiling;
5. provider readiness and the spend kill switch.

GitHub job-count ceilings are not part of financial admission.

## Workload controls

`workload_control/WORKLOAD_POLICY.json` owns non-financial execution controls. Each service has:

- a hard `timeout-minutes` bound;
- its own concurrency group;
- pending-run coalescing for repeated triggers;
- its own scheduled cadence or event trigger.

Because unrelated services no longer share one GitHub concurrency group, a newer pending Pages run cannot evict pending Hunter or scheduler work.

Essential reporting remains available even when paid execution is blocked.

## Duplicate and retry safety

Paid idempotency keys suppress duplicate spend. Reusing the same key for a different request fails closed. Retry groups cannot reset their attempt numbers to bypass retry limits.

Workload duplicate suppression is handled at the service lane through workflow-specific concurrency and trigger coalescing rather than a shared financial quota.

## Accounting and hard stops

Paid reservations store only sanitized identifiers, hashes, numeric usage, timestamps, and evidence references. Prompt text, credentials, customer data, and private evidence are not persisted.

Actual paid usage is reconciled after execution. If actual paid usage exceeds its reservation, the reservation becomes `OVERAGE`. From that point, `hard_stop_reason()` reports a current-day paid overage and every subsequent paid model/API preflight is blocked.

GitHub runner-minute variance does **not** trigger a financial hard stop. GitHub workloads are bounded by workflow timeouts and workload controls instead.

## Paid-ledger race prevention

Only workflows that can mutate paid model/API cost state remain on the shared `portfolio-cost-governed-autonomy` concurrency lane. This preserves a single serialized paid ledger without turning that lane into a queue for unrelated free GitHub work.

## Kill switch

`cost_governor/COST_KILL_SWITCH.json` and `PORTFOLIO_SPEND_DISABLED` stop new paid model/API execution. They do not suppress essential reporting or unrelated non-paid workload lanes.

The watchdog remains an independent backstop for paid hard stops and kill-switch enforcement. Foundation CI is never targeted.

## Truthful status

A workflow blocked before substantive execution must report **BLOCKED** rather than silently finishing green. The command center separately displays durable counts for attempted work, blocked work, executed/completed work, and verified external outcomes.

## Authority boundary

A budget reservation is never an approval. ACT requests remain blocked by the cost governor, and all consequential operations retain their existing authority and human-governance gates.
