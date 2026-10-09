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

## October 9, 2026: signed Cron CLI parsing failure (source still v4)

At 09:30 UTC, the **original Cloudflare** `scheduled()` event for worker
`portfolio-brain-recovery` completed provider-side with
`DISPATCH_ACCEPTED_NOT_COMPLETED` for protected v4 source
`9fc08c72e2d050359e7f119bfcbfb82b23f95b5b`. Its corresponding
[GitHub core #37911706292](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/37911706292)
FAILED in "Verify independently signed Cloudflare Cron provenance"
*before* loading/publishing durable state. The workflow gave Python argparse
the P-256 **URL-safe base64** signature in the two-token form
`--signature "$CF_SIGNATURE"`. This **valid encoding class** can begin with
a hyphen, which argparse interprets as a new option, producing
`argument --signature: expected one argument`, even when the expected
input field is present. That error is a command-line argument binding
failure; it does not prove a signature was invalid or forged, and this
failed run must remain FAILED with no state publication or delivery claim.

Cloudflare's authentic 09:40 UTC `scheduled()` event also accepted a
dispatch. [GitHub core #37912778183](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/37912778183)
subsequently SUCCEEDED, verifying P-256 provenance, mandatory workloads,
doctor PASS/pending0 and nonforce state publication on the original v4
source. Preserve both outcomes and do not replay the failed 09:30 run.

The **unmerged v5 candidate only** changes the workflow call to the single
`--signature="$CF_SIGNATURE"` argv token. This safely binds a leading
`-` to the signature's option value; no verification algorithm, public key,
signing secret, scheduler, replay guard or acceptance criteria change.
`tests/test_brain_cloudflare_clock.py` includes an independently generated
**test-only** valid P-256 envelope with a hyphen-leading signature and
an intentionally tampered signature, plus execution of the actual workflow
shell command in a disposable directory. It requires the signed test case to
verify only under its matching test public key; a request using the real
production key must still fail signature verification or freshness. A green
test is **not** a v5 scheduled execution, not a production fix deployed and
not permission to re-label v4's historical failed job.

## Additional research-quality source candidates in V5 draft (not deployment)

The integration candidate also stages the source-reviewed, independently
green code and regression tests from two still-unmerged main-based drafts:
[knowledge diversity #662](https://github.com/P00NSMASHER/portfolio-brain/pull/662)
at `089a3d9ffb714e0fa365a5c6ad2ba737479814bb` and
[synthetic experiment integrity #663](https://github.com/P00NSMASHER/portfolio-brain/pull/663)
at `bb7f830bc4abb62a50611245687162b9b440c3b7`.
Their implementation and test Git blobs are copied unchanged, with only
the two source-specific guidance pages reconciled to reflect staging in
this combined V5 draft. Their original branches and pull requests remain
unchanged.

New integrated offline tests must demonstrate that balanced *eligible*
knowledge selection and the revised **simulated-only** invoice experiment
can coexist in the same canonical SQLite report, preserve complete replay,
and make no claim of actual speedup, invoices, customer utility or revenue.
The full combined candidate and its independent verifier require **new**
exact-head green checks. Neither the original PR checks nor passing
synthetic tests grant production source authority or new V5 acceptance.

## Financial evidence classification safety (candidate only)

The V5 source candidate also enforces a conservative provenance ceiling on
explicitly supplied long-only holdings observations. New event ingestion rejects
any `ACTUAL` holdings declaration containing `ESTIMATED` or `SIMULATED`
quote or historical price inputs, and any `ESTIMATED` declaration containing
`SIMULATED` prices. Analysis independently exposes valuation and historical
evidence labels, source attestations, and the effective lower-confidence
classification. Existing V4-era ledger bytes and hashes are preserved if
their original declared labels were weaker than their nested evidence:
replay may inspect those archived events, but derived reports conservatively
downgrade them and visibly flag their original discrepancy. All numbers
remain fixed-holdings scenarios, not verified custody, actual performance
or financial execution authority. No brokerage connectors or permissions
are enabled.

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
