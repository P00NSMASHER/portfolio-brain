# Step 20 Cost Governor Contract

Step 20 is a fail-closed execution boundary. It does not decide what work is valuable and it grants no authority. It decides only whether already-authorized work may consume bounded model/API/GitHub resources.

## Pre-execution reservation

Every non-Tier-0 model/API invocation and every managed autonomous GitHub job must reserve its worst-case usage before substantive execution. Active reservations count against the same ceilings as committed usage. A reservation is identified by a deterministic idempotency key and retry group.

The checked-in paid/model/API ceilings are zero. Enabling a provider or model elsewhere is therefore insufficient to spend money or tokens; a separate policy change is required.

## Independent budget scopes

A request must pass every applicable scope:

1. portfolio daily ceiling;
2. each referenced project daily ceiling;
3. provider/model daily ceiling for model/API work;
4. workflow/job daily and per-job ceiling for GitHub compute;
5. retry sequence and retry-count ceiling.

The strictest failing scope blocks execution.

## Duplicate and retry safety

Reusing the same idempotency key with the same immutable request is duplicate-suppressed and cannot create a second reservation. Reusing the key for a different request fails closed. Retry groups must start at attempt 1 and advance monotonically; attempt numbers cannot be reset to bypass the retry limit.

## Accounting

Reservations store only sanitized IDs/hashes, project/provider/model/workflow identifiers, numeric token/cost/runner usage, timestamps and evidence references. Prompt text, payloads, credentials, customer data and private evidence are prohibited while BLK-005 remains open.

Actual usage is committed against the reservation. If actual usage exceeds any reserved dimension, the reservation becomes OVERAGE and the watchdog treats the current day as a hard stop.

## GitHub race prevention

Artifact-backed accounting is serialized through the shared `portfolio-cost-governed-autonomy` concurrency group. Managed autonomous workflows restore the latest cost artifact, reserve before substantive work, conservatively commit the reserved runner minutes, and upload the sanitized continuation state.

## Kill switches and cancellation

`cost_governor/COST_KILL_SWITCH.json` and the `PORTFOLIO_SPEND_DISABLED` repository variable can force a hard stop. The staged watchdog has `actions: write` only so it can cancel queued/in-progress managed autonomous runs when a kill switch or current-day overage is present. It never cancels foundation CI and cannot grant execution authority.

## Authority boundary

A cost reservation is not an approval. ACT requests are rejected by the governor. Customer communication, cash movement, payments, live trading, deployment and other consequential actions retain their existing human/governance gates even when budget is available.
