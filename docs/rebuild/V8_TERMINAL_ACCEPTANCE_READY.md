# V8 final-source six-hour acceptance readiness - independent reviewer handoff

**Purpose:** make terminal acceptance an evidence check, not a new work package
or a new observation clock. This is an **unmerged, read-only review kit** for
P00NSMASHER/portfolio-brain. It changes no running source, scheduler, task,
Cloudflare Worker, branch protection, credential, customer data or spending.

## Current source and protected boundaries

- Reviewed protected production source: 1a310ebfd0bf3aadffc74ae178582f0c235c9ab9
  (guarded #710, #711 and #712).
- Actual post-merge Foundation CI and push-triggered Brain cycle both passed,
  but the push run #39017489995 is **not** unattended or a valid anchor.
- Original pushed state snapshot: 8ecefd629ade67cf58b9790c4c03668ab6616409,
  original ZIP artifact #12094917804, zero pending events. Historical, not a
  six-hour pass. Original provider file SHA/CRC verification was independent.
- One existing Portfolio Brain Reliability task remains enabled hourly; its
  task/check time never controls acceptance start. No new task is necessary.

## Immediate first qualifying automatic completion

As soon as GitHub finishes the FIRST genuine automatic same-source core:
1. Re-read protected main and original run ID, event, SHA, attempt and jobs.
   Require exact current SHA and a successful original monitor job, first
   attempt, all mandatory preflight/research/doctor/publication/evidence steps.
2. For schedule, verify GitHub-native schedule origin. For
   workflow_dispatch, require an actual original signed Cloudflare Cron
   verification or independently authenticated watchdog/clock step, **not**
   an operator/manual dispatch or webhook acknowledgment.
3. Download that run's original named ZIP from GitHub, verify its provider
   size, SHA-256, ZIP CRC, delivery/doctor receipts, zero backlog, published
   state child with its exact original Git parent, and signed origin artifact.
4. The automatic window starts at that job's **original completed_at UTC**.
   Retain first run ID, completion time, original state parent and provider
   evidence. Later checking does NOT reset the start to task check time.
5. Do not count a push-triggered run, Cloudflare FRESH, incomplete dispatch,
   modified source, skipped job, failure, rerun, synthetic receipt or manual
   success as a qualifying automatic core.

## During the window

- Keep production main/Brain core/Worker/secret/scheduler unchanged.
- Each original automatically completed core must preserve main source, first
  attempt, all required jobs, signed origin, zero pending events, unchanged
  provider artifact digests and a continuous single-parent nonforce state
  chain. Scan **all** exact-source core runs, including failures, retries and
  skipped attempts, not only selected green ones.
- Maximum gap between completed qualifying cores: **5,400 seconds**.
- Earliest terminal core is the first independently verified automatic
  completion **plus >=21,600 seconds**. Elapsed time alone is not an acceptance
  result.
- The scoped CaptureBrief repair workflow must prove **its own** authentic
  automatic run and original GitHub App one-repository token; a bot-written
  draft PR is still not merged/delivered. Check original Product Core CI,
  exact one-file document correction and reviewer/owner release boundary.
- A material failure stays visible and blocks certification. Repair must
  follow protected source/independent QA and a source-specific new window if
  the production SHA changes. Do not alter clocks or rewrite old evidence.

## Terminal original-evidence replay

The supplied review-only script verification/v8_terminal_readiness.py has
independent negative/positive tests in tests/test_v8_terminal_readiness.py.
Its **first stage** uses only original GitHub GET endpoints and the existing
GitHub Actions read token to census original same-source runs/attempts, all
mandatory job steps, artifact identities/digests, real original ZIP SHA/CRC
and embedded doctor/delivery/state receipts, and published Git parent chain.

A terminal run can be considered for **second stage** only once the script's
original completion-span test has verified >=21,600 real seconds and gaps
<=5,400 seconds. Provide two **separately immutable** Git object checkouts:
- canonical: production Git commit exactly
  1a310ebfd0bf3aadffc74ae178582f0c235c9ab9.
- terminal: exact final qualifying brain-state-v2 published child commit
  read from the last original ZIP delivery and original Git commit, not a
  mutable branch ref guessed before the last run.

The script restores the **original state chunks** from that terminal commit
and runs the production-source brain.state_archive.restore,
soak_v3.audit.verify_sqlite(strict_event_ids=True) and
brain.core.Store.read_report independent deterministic replay. It binds the
actual raw SQLite digest/ledger sequence/canonical hash to the terminal
original state-publication.json and doctor report, requires FK/integrity
and zero pending events, and writes only a sanitized read-only receipt.

Example usage inside an **independently reviewed** GitHub-hosted Actions job
with an original read token and trusted immutable checkouts:

    GH_TOKEN=$GITHUB_TOKEN python -I \
      verification/v8_terminal_readiness.py \
      --output "$RUNNER_TEMP/v8-terminal-provider-readback.json" \
      --source-dir canonical \
      --terminal-dir terminal

An interim read can omit both checkout arguments and report
WAITING_FIRST_ORIGINAL_AUTOMATIC_COMPLETION or
WINDOW_RUNNING_NOT_ACCEPTED, but **cannot** claim acceptance.

There is intentionally no new active cron, automatic merge, protected release
API, or acceptance-emitting CI job on main. **This review-only candidate is
not a source upgrade that should be merged during the hold.** It can be copied
into a separately reviewed, source-pinned one-shot acceptance proof job on a
review branch at terminal time, following the already proven historical
independent GitHub Actions replay (run 39014095025). Verify the exact
reviewed source, independent verifier App identity, original GitHub job and
immutable artifact SHA/CRC, then remove temporary CI wiring.

### Independent external source still required

This GitHub-based script **deliberately does not** certify Cloudflare
telemetry by reading its own producer claim. A separate authenticated,
read-only Cloudflare Workers observability query must corroborate original
scheduled events (portfolio-brain-recovery, outcome=ok, original
scheduledTime/request ID) and map each signed dispatch to its exact completed
GitHub core. Check genuine original P-256 signature validation, not mere
DISPATCH_ACCEPTED_NOT_COMPLETED or FRESH log lines. This independently
owned Cloudflare corroboration must be attached before terminal certification.

### Completion decision

Record **PASS** only after original full run/attempt census, source SHA/gaps,
all original ZIP SHA/CRC, complete state lineage and independent SQLite/ledger/
report replay, external Cloudflare origin corroboration, a separate reviewer
decision, and the actual autonomous repair outcome. A true deployed code
repair additionally needs authorized CaptureBrief merge/delivery and live
readback; draft PR/CI isn't delivery.

If some proofs pass but external events or real repair are absent, retain
**HOLD/PENDING** with exact missing evidence, do not imply universal
autonomy, and preserve previous-source acceptance as historical. This
readiness kit never changes or claims the disproven 5 GB capacity target.
