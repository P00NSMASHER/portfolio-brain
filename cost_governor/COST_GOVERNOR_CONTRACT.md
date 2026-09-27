# Step 20 Cost Governor Contract

Step 20 is a fail-closed **paid model/API execution boundary**. It does not decide what work is valuable and it grants no authority. Ordinary GitHub-hosted workflow starts and runner minutes are workload controls, not paid-spend budget.

## Pre-execution reservation

Every non-Tier-0 model/API invocation must reserve its worst-case paid usage immediately before provider execution. Active paid reservations count against the same financial ceilings as committed usage. A reservation is identified by a deterministic idempotency key and retry group.

The checked-in paid/model/API ceilings are finite and nonnegative. Enabling a provider or model is still insufficient to spend money or tokens: provider readiness, routing, authority, idempotency, retry, and pre-execution reservation gates must all pass independently.

## Financial budget scopes

Paid model/API work must pass the portfolio, project, provider/model, and retry ceilings. The portfolio USD ceiling remains **$10 per UTC day**.

GitHub job starts and runner minutes are retained in the historical usage schema for backward compatibility and telemetry, but their paid-budget ceilings are zero and they are not evaluated as financial spend.

## Workload controls

Managed GitHub work is controlled separately with bounded per-job timeouts, subsystem duplicate suppression, service-specific concurrency groups, pending-event coalescing, service-specific schedule cadence, and bounded liveness recovery.

There is no daily GitHub job-start quota in the cost governor. Essential command-center and health reporting therefore remain able to explain paid blocks instead of being blocked by them.

## Duplicate and retry safety

Paid idempotency keys suppress duplicate spend. Reusing the same key for a different request fails closed. Retry groups cannot reset attempt numbers to bypass retry limits.

The compatibility GitHub workload preflight retains idempotency and max-runtime checks, but prior GitHub job counts do not consume paid budget or activate the paid hard stop.

## Accounting and hard stops

Reservations store only sanitized IDs/hashes, project/provider/model/workflow identifiers, numeric usage, timestamps and evidence references. Prompt text, payloads, credentials, customer data and private evidence remain prohibited while BLK-005 is open.

Actual paid usage is committed against the reservation. If a paid execution disappears before commit, its expired reservation remains charged at the reserved maximum for the rest of that UTC accounting day. If actual paid usage exceeds its reservation, the reservation becomes `OVERAGE`, the decision becomes `HARD_STOP_OVERAGE`, and every subsequent paid model/API preflight is blocked with `BLOCKED_HARD_STOP`.

A GitHub workload runtime overrun is reported as `WORKLOAD_OVERRUN`; it does **not** activate the paid-spend hard stop.

## Paid-ledger race prevention

Only workflows that can actually spend model/API money share the `portfolio-paid-cost-ledger` concurrency group. Non-paid workflows use service-specific concurrency groups, preventing unrelated pending jobs from replacing one another while preserving serialization of artifact-backed paid accounting.

## Kill switches and cancellation

`cost_governor/COST_KILL_SWITCH.json` and the `PORTFOLIO_SPEND_DISABLED` repository variable stop new paid model/API execution.

The watchdog may cancel only the explicit paid workflow allowlist. It does not cancel Pages, Hunter, heartbeats, notifications, the autonomous scheduler, foundation CI, or other non-paid control-plane work. Non-paid liveness recovery continues to operate and reports the paid hard-stop reason when one is active.

## Authority boundary

A cost reservation is not an approval. ACT requests are rejected by the governor. Customer communication, cash movement, payments, live trading, deployment and other consequential actions retain their existing human/governance gates even when budget is available.
