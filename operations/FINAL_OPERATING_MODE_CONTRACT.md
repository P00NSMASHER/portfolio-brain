# Step 25 Final Autonomous Operating Mode

Step 25 is the release gate that promotes the already-verified Step 0–24 architecture to the repository default branch.

## What becomes autonomous

On `main`, the approved recurring workflows may self-trigger on their existing schedules:

- runtime hourly sync, daily learning, weekly synthesis;
- bounded public Hunter cycles;
- evidence-gated scheduler cycles;
- the cost watchdog; and
- evidence-gated notification cycles.

`runtime-event-observe` reacts to pushes on `main`. The runtime worker and software-factory candidate workflow remain reusable/callable surfaces rather than new schedules.

Scheduler and heartbeat workflows remain scheduled and manually dispatchable, but are not separately push-triggered. All cost-state writers share a singleton concurrency lane; limiting ordinary main-push fan-out prevents GitHub from evicting excess pending runs before any job starts. Foundation CI validates their code and contracts on each relevant push, and their next scheduled or explicit dispatch supplies execution evidence.

## What does not become autonomous

The release permits only policy-bounded customer email through the action-engine gateway. StarBlox/ABVM validation is adult-stakeholder-only and excludes direct minor contact, child-data collection, production changes, and consequential child-facing changes. Payment/cash movement, live market trading or brokerage execution, deployment, merge authority, secret changes, and unapproved child-facing consequential changes remain human-gated or prohibited.

Paid/model/API execution remains deny-by-default at invocation time unless the enabled OpenAI route passes provider readiness, finite pre-execution cost reservation, retry, idempotency, and kill-switch gates. Model output is advisory and cannot grant authority or upgrade evidence.

## Governed no-work outcomes

For recurring OBSERVE lanes, a cost-governor denial or engaged kill switch is an expected, auditable no-work outcome. Every downstream action remains skipped, but the workflow reports a notice instead of a false operational failure. Modification-capable software-factory execution remains fail-closed with a nonzero workflow result when its gate denies authority.

## Runtime independence

Ordinary operation is GitHub-hosted and machine-readable. Interactive ChatGPT and the user's 15 scheduled ChatGPT tasks may monitor and analyze the system, but the operating loop does not require them to execute.

## Promotion gate

Before merge to `main`, exact-head CI must pass with Steps 1–25 validators, Step 23 hostile regressions, and the Step 24 no-prompt canary.

After merge, the promoted `main` head must pass foundation CI and the push-triggered runtime observation path. The final durable state must record the exact main SHA and post-promotion evidence before Portfolio Brain is declared operational.

Post-release, trigger-only command-center refresh commits are excluded from runtime event observation. This preserves the serialized cost/state boundary for useful work and prevents a display refresh from generating redundant repository-observation traffic. The bounded Gmail connector gateway is considered live only when its sanitized operating-status proof exactly matches the durable gateway ledger sequence and timestamp; no raw connector identifiers are persisted.
