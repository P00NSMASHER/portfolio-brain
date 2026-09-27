# Step 20 Paid Cost + Workload Control Contract

Step 20 grants no authority and does not decide what work is valuable. It now has two deliberately separate control planes:

1. **Paid execution control** for non-Tier-0 model/API calls.
2. **GitHub workload control** for ordinary Actions jobs.

A failure or limit in one control plane must not silently disable the other.

## Paid pre-execution reservation

Every non-Tier-0 model/API invocation must reserve its worst-case token/API/cash usage before substantive execution. Active paid reservations count against the same financial ceilings as committed usage. Reservations use deterministic idempotency keys and retry groups.

The checked-in paid ceiling remains **USD 10 per UTC day**, with finite model/API and token ceilings. Provider readiness, routing, authority, idempotency, retry, spend kill switch, hard-stop state, and reservation capacity must all pass independently.

A paid reservation overage immediately creates a current-day hard stop. Every subsequent paid preflight checks that hard stop before it can reserve or execute.

## GitHub workload admission

Managed GitHub jobs do **not** consume paid-ledger reservations and are not blocked by daily job-start counts. The historical daily job-count fields remain in policy only for schema/telemetry compatibility and are non-enforcing.

GitHub workload admission instead enforces:

1. a configured workflow/job identity;
2. a per-job timeout ceiling;
3. bounded GitHub rerun attempts;
4. authority boundaries;
5. service-scoped concurrency and event coalescing.

Workload admission is state-neutral: it cannot spend money, cannot consume paid budget headroom, and cannot create cost-ledger races.

## Financial budget scopes

A paid model/API request must pass every applicable financial scope:

1. portfolio daily financial ceiling;
2. each referenced project financial ceiling;
3. provider/model daily financial ceiling;
4. retry and idempotency controls.

GitHub job starts and runner minutes are not included when deciding whether a paid request has financial headroom.

## Duplicate and retry safety

Paid reservations preserve durable duplicate suppression and monotonic retry groups. GitHub workload reruns use the native GitHub run attempt and remain bounded by the configured workload retry limit. Service-scoped concurrency coalesces duplicate/pending workload where appropriate.

## Accounting

The paid ledger stores only sanitized IDs/hashes, project/provider/model identifiers, numeric token/cost usage, timestamps and evidence references. Prompt text, payloads, credentials, customer data and private evidence remain prohibited.

Actual paid usage is reconciled against its reservation. If paid execution disappears before reconciliation, an expired paid reservation remains charged at its reserved maximum for the rest of that UTC accounting day. If actual paid usage exceeds any reserved dimension, the reservation becomes OVERAGE and the current day hard-stops further paid execution.

## Concurrency and race prevention

Only workflows that can mutate paid model/API reservation state restore and persist the paid cost artifact. Those paths remain serialized through `portfolio-cost-governed-autonomy`.

Unrelated workload uses service-scoped lanes instead:

- command-center publication;
- Hunter + Scheduler shared-state work;
- agent heartbeat;
- notification delivery;
- software-factory work.

This prevents unrelated pending jobs from displacing one another while preserving serialization where shared state requires it.

## Reporting and operational health

Command-center publication and other workload-only health paths do not restore or persist the paid ledger and do not receive the spend-kill environment variable. They can continue running to explain provider failures, paid hard stops, blocked work, and stale state.

Workflow summaries report **attempted**, **blocked/reason**, **executed**, and **verified** outcomes separately where the operator needs to distinguish a successful workflow shell from substantive work.

## Kill switches and cancellation

`cost_governor/COST_KILL_SWITCH.json` and `PORTFOLIO_SPEND_DISABLED` stop paid execution. The watchdog may cancel only workflows listed in `paid_execution_workflow_names`; it must not cancel workload-only reporting, hunting, scheduling, or health jobs because paid spend is stopped.

Workload liveness recovery also remains available during a paid hard stop. Paid-execution workflows are excluded from that recovery lane.

## Authority boundary

Budget capacity and workload admission are not approvals. ACT requests remain rejected by these control planes. Customer communication, cash movement, payments, live trading, deployment, and other consequential actions retain their independent authority/governance gates.
