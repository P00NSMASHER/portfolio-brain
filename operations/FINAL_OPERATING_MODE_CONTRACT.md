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

## What does not become autonomous

The release does not grant customer communication, payment/cash movement, live market trading or brokerage execution, deployment, merge authority, secret changes, or unapproved child-facing consequential changes. Human-gated approvals remain human-gated.

Paid/model/API execution remains deny-by-default because the checked-in provider registry has no enabled non-Tier-0 model and Step 20 paid/token/model/API ceilings remain zero.

## Runtime independence

Ordinary operation is GitHub-hosted and machine-readable. Interactive ChatGPT and the user's 15 scheduled ChatGPT tasks may monitor and analyze the system, but the operating loop does not require them to execute.

## Promotion gate

Before merge to `main`, exact-head CI must pass with Steps 1–25 validators, Step 23 hostile regressions, and the Step 24 no-prompt canary.

After merge, the promoted `main` head must pass foundation CI and the push-triggered runtime observation path. The final durable state must record the exact main SHA and post-promotion evidence before Portfolio Brain is declared operational.
