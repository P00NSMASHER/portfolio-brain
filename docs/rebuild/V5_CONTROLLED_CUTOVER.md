# Portfolio Brain v5: source-switch cutover and rollback readiness

**Status: PRE-PROMOTION HOLD.** This is an operator runbook, NOT authority to merge,
change Cloudflare, deploy new code, suspend tasks, or start a new acceptance clock.
Source candidate: draft [PR #661](https://github.com/P00NSMASHER/portfolio-brain/pull/661);
the exact review head must be freshly read when any decision is taken. Historical
certified v4 protected `main` source:
`9fc08c72e2d050359e7f119bfcbfb82b23f95b5b`. Its
[`brain-acceptance-v4/acceptance/finish-soak-v4.json`](https://github.com/P00NSMASHER/portfolio-brain/blob/brain-acceptance-v4/acceptance/finish-soak-v4.json)
is terminal PASS **for that source and historical observation window only**.
Historical v2 FAIL/v3 BLOCKED remain immutable.

## What is currently deployed, verified read-only October 9, 2026

The connected Cloudflare account has one actively deployed 100% Worker version
`9b94dc1d-ee63-47de-8c61-dd62ffd7120c` for
`portfolio-brain-recovery`, and actual Cron
`*/10 * * * *` UTC. Both named secrets
`GITHUB_ACTIONS_TOKEN` and `SIGNING_KEY_PKCS8` exist as
`secret_text` bindings. Their values were **not inspected or exposed**.
An exact source-content comparison of the deployed Worker script with protected
[`reliability/cloudflare/worker.mjs`](../../reliability/cloudflare/worker.mjs)
was TRUE (5,731 JavaScript characters). A provider deployment record and
bindings are distinct evidence from configured repository source.

**No Cloudflare source-SHA repin is needed at cutover** if that Worker remains
unchanged: `tick()` fetches GitHub's protected `/branches/main`, validates
the returned exact SHA, inventories real core runs for **that current SHA**,
and signs the current SHA in the Cloudflare `scheduled()` envelope.
Its HTTP `fetch()` always returns 404; there is no public dispatch URL.
It suppresses fresh same-source completions for 25 minutes, refuses active
or stale queued same-source writers, and requests a GitHub dispatch only when
due. GitHub core verifies the signed source using the existing public key.
Cloudflare HTTP 204 is dispatch acknowledgement, NEVER execution success.

GitHub main:
- full native core Cron `7,27,47 * * * *` UTC from
  `.github/workflows/brain-cycle.yml`;
- native watchdog `16,36,56 * * * *` UTC from
  `.github/workflows/brain-clock.yml`;
- core state-writer concurrency `group: brain-v2-state`, no cancel;
- state branch `brain-state-v2/state.sqlite`, expected-parent check before
  **nonforce** push, exact source checked before and after publication.
The V5 candidate adds only bounded stale-parent post-push readback retries.
Do not force-update any state ref. In-flight old-source work can fail
`MAIN_DRIFT` when source changes; preserve failure evidence, and require
continuity from the last actual durable state commit.

## Offline cutover/rollback simulation (not deployment)

`tests/test_v5_source_switch_safety.py` runs the actual reviewed Cloudflare
Worker functions under Node with mocked network and a throwaway P-256 key.
It checks v4 recent success -> FRESH; new v5 current main with only old success
-> DUE and new-source signed dispatch; real new-success -> FRESH; new active
writer -> ACTIVE without duplicate dispatch; stale new writer -> fail-closed;
controlled return to the old source -> dispatch rebinds to current source.
It also tests the unchanged core/native watchdog schedule, provenance and
nonforce state-writer guard. This is **simulated input**, no external dispatch,
runtime acceptance, billable call, or real-world availability guarantee.
The existing review also proved read-only real-state migration, v5 shadow
first-cycle on a disposable snapshot, independent source-bound provider reads,
and original ledger preservation; these are distinct forms of evidence.

## Go/no-go gates before any separately authorized promotion

1. **Authorization:** user/operator explicitly approves this *specific*
   source transition. No general "keep developing" instruction changes
   the release authorization or branch-protection rules.
2. **Source freeze:** identify the final PR #661 head SHA, base/main SHA,
   complete changed-file inventory, and genuine exact-head `validate` by
   GitHub Actions App 15368 and `portfolio-phase1-gate` by independent
   App 5121826, both completed SUCCESS. A newer commit voids earlier receipts.
   A protected merge commit has a NEW source SHA: verify actual merged source
   anew rather than treating a passing PR virtual-merge checkout as identical
   commit identity.
3. **Live state:** record the exact original state branch parent commit,
   SQLite Git blob, raw SHA256 and size, independently replay integrity,
   canonical event/ledger chain, actual unprocessed-event backlog and
   last `monitor/research/experiment/doctor` results. State may advance
   after the snapshot; do NOT overwrite that advancement on promotion.
4. **Active clocks:** verify current Cloudflare Worker deployment, Cron,
   dynamic SHA sourcing and secret binding NAMES, native GitHub schedules,
   no competing writer and current-main liveness with actual recent
   completed cores. No secret values in logs or evidence comments.
5. **Transition mechanics:** use the **existing** protected review/merge
   process only after explicit authorization. Do not disable 15 scheduled
   tasks, shut down native/Cloudflare Crons, change signing keys, force-push
   state, replay posted work, or start parallel state publishers.
   Protected main commit changes during promotion, so queued old-source
   workers must fail on `MAIN_DRIFT` rather than write stale state.
6. **First new-source core:** require a *real* Cloudflare `scheduled()`
   provider record plus signed P-256 envelope (or correctly labeled actual
   native schedule), matching newly deployed protected source SHA, completed
   GitHub core with mandatory workloads and doctor PASS/pending0, original
   ZIP SHA256, published nonforce state commit and exact preserved parent.
   A `push` event or manually dispatched core is **not** an automatic
   Cloudflare cycle even if all its workloads succeed.
7. **New acceptance:** independently establish a new V5 acceptance period,
   including at least 21,600 seconds between first and last genuinely
   provider-backed successful completions and no accepted completion gap
   over 5,400 seconds, with **all** failures, excluded unverifiable provider
   events and original artifacts inventoried. Retain V4 terminal PASS as
   historical only; do not re-label or rewrite it as V5.

## No-go / rollback trigger and safe response

STOP release claims and investigate if actual deployed SHA deviates, signer
or provider logs disappear, event chain/SQLite integrity fails, a state parent
diverges, repeated unverified post-push reads occur, mandatory jobs fail or
pending events cannot be drained. Never hide the problem with another
scheduler, retry loop, manual fake scheduled job or fabricated PASS.

For rollback, first retain the actual V5-era state commit and immutable
evidence; validate the full ledger at that exact commit. Restore prior
implementation **through reviewed protected change control** (for example,
a new revert commit), not a force reset of `main` or a state branch.
**A revert commit has a NEW source SHA even if its files resemble v4, so
the historical v4 terminal PASS cannot certify that rollback SHA.**
The dynamic Cloudflare clock and native workflows will bind to the actual
current protected SHA after a proper rollback, and genuine new scheduled runs
must independently re-establish readiness. Before rollback, independently
confirm the v4-equivalent reader can replay any later V5-era ledger events
and projection schema without silently dropping or rewriting history.
The V5 draft's offline rollback sample is useful evidence, not certification
of every possible future state.

## Unresolved permission and runtime gates

**HOLD DRAFT / DO NOT DEPLOY** until release authorization is explicit and
the above exact-head/source/state/provider checks are revalidated at that time.
No part of this runbook is an automation that performs those steps, and no
new user task or routine ChatGPT notification is required.
