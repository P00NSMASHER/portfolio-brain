# V7 bounded autonomous check revalidation

## Release boundary

This is a candidate extension of existing draft PR #685, not a new production service. Protected V6 source `f39a8b2ad88b6e1f0db246b586c89a9d611a566c` and acceptance issue #684 remain unchanged. Do not merge during that source-specific acceptance window. V7 needs separate protected-source release authorization and its own acceptance. Historical checks and the original V7 shadow audit certify only their exact source versions.

## Intended behavior

The decision queue currently identifies a completed check deterioration but asks the operator to gather its next evidence. The extension selects that follow-up itself and uses the existing `GitHub.observe` GET-only implementation to recheck the public, policy-allowlisted repository. It does not diagnose root cause, repair code, execute third-party source, create or merge a PR, close an incident, change credentials, spend money, or publish state.

Only an existing, replay-verified PASS report with zero pending events qualifies. Both original comparison timestamps must still be actual and inside the existing 172800-second freshness window, on the same revision, with unambiguous check names and source references bound to the exact repository/commit. All eligible input evidence is validated before the first provider read. Unknown repositories, stale/nonactual comparisons, and third-party source-review proposals never trigger investigation reads.

The plan is deterministic, deduplicated by repository, and capped at three repositories. The existing adapter enforces a global 24-request cap, response size, retry and timeout bounds, public visibility, complete bounded check pagination, unique check identities, matching check revision, and unchanged branch during collection. Reserve sixteen remaining request slots before each observation: eight possible metadata/branch/check-page reads, each with at most one existing transient retry. Unused slots are not consumed. Defer remaining work honestly instead of raising budgets or inventing completion. The local `STOP` file is checked before each repository observation; an in-flight bounded observation is not interrupted.

## Outcomes are evidence, not authority

| Result | Meaning |
| --- | --- |
| `STILL_ADVERSE` | A uniquely named completed adverse check is observed on the same revision. |
| `SUCCESS_OBSERVED_NOT_RESOLUTION` | A uniquely named successful check is now observed; root cause and incident resolution are not established. |
| `SOURCE_CHANGED_REQUIRES_NEW_COMPARISON` | Current branch moved; no old-versus-new revision recovery inference. |
| `CHECK_NOT_COMPLETED` | Pending work is not success. |
| `UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK` | Missing or duplicate names cannot confirm either failure or recovery. |
| `OTHER_CONCLUSION_NOT_RESOLUTION` | Neutral, cancelled, skipped or absent conclusions are not resolution. |
| `UNVERIFIED_READ_FAILED` | Provider or evidence verification failed; preserve earlier successful observations but stop further reads and mark the overall result incomplete. |

Every receipt retains source SHA, original state sequence, original queue identity, observed revision, and explicit counts for eligible, attempted and deferred work. Source report objects are unchanged. `execution_authority=false`, `root_cause_verified=false`, `github_mutations=0`, `events_written=0`, and `paid_calls=0` remain explicit. Errors use fixed status labels rather than raw provider exception messages. Fetched check metadata is never treated as an instruction or a shell command.

## Standalone, one-shot entry point

After a separately authorized release and source-compatible state generation:

```sh
python -m brain.investigate \
  --db /private/brain/state.sqlite \
  --expected-sha "$(git rev-parse HEAD)" \
  --output /private/brain/investigation
```

This command is NOT wired into existing Cloudflare/GitHub cron, `brain service`, doctor, mandatory workloads, or canonical event schemas. It performs at most one bounded pass, without a scheduler or background loop. The public-state-only CLI verifies clean exact source and reads the existing original database through `readonly_authority_snapshot`; all `Store` operations occur on a disposable private copy. It must never bootstrap a missing original, drain pending events, generate a new canonical report, write attempts, or write feedback. Expired/source-mismatched reports fail before provider use. Output collision with the original database is rejected before snapshot or provider reads.

`report.json` in the dedicated output directory is the detailed investigation receipt, not a replacement for the canonical Brain report. Existing private report publication provides 0700 directory and 0600 files, rejects symlink/hardlink aliases, and publishes machine JSON last. The private Markdown and HTML summaries display each investigated repository, check outcome, observed revision, source reference, used request count, deferred items, and explicit no-repair/no-resolution caveats; they escape untrusted check names. The machine JSON remains the full structured receipt and is not substituted for the canonical Brain report. Do not point this output at the canonical report directory. Incomplete, stopped, or budget-deferred execution is not a full revalidation success.

## Test requirements

Use the real existing GitHub adapter with synthetic transport fixtures, not a replacement implementation of provider verification. Cover persistent failure, observed success without incident closure, branch movement and branch races, incomplete/ambiguous check observations, private metadata, source identity, stale/future evidence, zero-backlog and exact-source requirements, stop before/between observations, global budget reservation, deterministic selection and explicit deferred work. Exercise the real CLI on synthetic SQLite state and require unchanged original bytes, mtime and permissions, private receipt output, no missing-state bootstrap, no expired report reads and no output overwrite of original state.

Final candidate quality requires full exact-head Foundation CI plus the separately credentialed existing independent verifier. A passing synthetic test suite is not a real production incident investigation or V7 operational acceptance.


## Continued check follow-up from immutable state (candidate extension)

The original V7 queue rechecked newly deteriorated checks, but stopped
investigating once two consecutive samples both showed a failure. The extension
derives **persistent adverse checks** and **observed recoveries** from the
already-verifiable original SQLite ledger; it does **not** introduce an incident
database, cursor, scheduled task, new event schema, or extra state writer.

Before any GitHub requests, it independently reconstructs each original event
identity and the immutable canonical hash chain and requires exact agreement
with the source-bound canonical report's state sequence, hash and deterministic
repository-change projection. The source report must be PASS with no pending
events and a fresh, original timestamp. Each candidate must be policy
allowlisted, PUBLIC, ACTUAL, and based on two distinct fresh observations of
the **same immutable commit** with unambiguous check identities and completed
conclusions. A completed adverse check repeated in both samples is labelled
`PERSISTENT_ADVERSE_OBSERVED` (not a newly diagnosed regression); adverse to
successful is `RECOVERY_OBSERVED_NOT_RESOLUTION` (not a fix). Missing,
simulated, stale, revised-source, pending and ambiguous samples do not qualify.

Deterministic order prefers **new check deteriorations**, then **persistent
adverse checks**, then **observed recoveries**. Equally ranked persistent
and recovery repositories rotate each UTC hour (derived from the trusted
invocation time, not a mutable cursor), so a fourth ongoing failure is not
indefinitely starved by three alphabetically earlier repositories. The limit
remains three public repository rechecks per invocation and the same 24-request
provider budget.
Every deferred case is counted; stopped, invalid and provider-failed cycles
remain visible, and no failed or skipped verification is called resolved.

The local private investigation report displays the distinct follow-up class.
The optional post-core sidecar uploads only **fixed-enumeration aggregate
counts** of follow-up classes, never names, code, URLs or raw event history.
`INITIAL_ADVERSE_TRANSITION` is used solely for the existing direct
deterioration path. Public aggregate labels never give execution authority.

The standalone CLI now reads and validates full original events **only on
the disposable read-only snapshot**, and checks report sequence plus chain
identity before selecting additional investigation work. The original SQLite
bytes, timestamp, mode, canonical schema and production workflows remain
unchanged. Regression tests include genuine synthetic ledger replay, repeated
failure, observed success, falsified recovery, competing priority, four-repo
capacity, forged hash/history rejection, out-of-order history identity, stale
and nonactual suppression, and the POSIX private CLI state-preservation path.

**Release remains HOLD** until V6 completes its independent original signed
provider six-hour acceptance, followed by separately approved V7 promotion
and entirely fresh source-specific automatic verification.


**Mixed outcomes:** If a single fresh, same-commit comparison has both a
deteriorated check and a different recovered check, both names are rechecked
in the **same bounded provider observation**. Neither the recovery nor a
possibly still-failing check is silently dropped, and the green status remains
only an observation, not root-cause resolution.

### Missing or stalled CI checks (bounded evidence-gap follow-up)

V7 now also rechecks a check that was **previously completed successfully or
adversely** but is absent or nonterminal in the latest fresh PUBLIC/ACTUAL
snapshot on the **same commit**. This is an `EVIDENCE_GAP_REVALIDATION`, never
an inferred regression, recovery, deletion, or verified root cause. Ambiguous
check names, nonactual sources, changed revisions and stale baselines remain
ineligible. The previous check's original source-bound URL supplies provenance
when no latest check URL exists. If the provider still omits the check, the
result is `UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK`; a pending check remains
`CHECK_NOT_COMPLETED`.

Priority: new actual regressions, then evidence gaps, then persistent adverse
checks, then observed recoveries; bounded UTC-hour rotation prevents equivalent
gap cases from starvation. The existing **three-repository and 24-GET limits**
still apply. The isolated sidecar publishes only aggregate allowlisted
`EVIDENCE_GAP_REVALIDATION` counts, no check names or raw history.

The initial deterioration path remains separate: when a repository has a new
regression it receives a priority recheck through the original queue. Gap-only
continuation applies where that same repository does not have a new recorded
regression. Neither path performs repairs, merges, external messages, paid
operations, or canonical state writes.

## Mixed check evidence, without duplicate GitHub reads

If one same-revision comparison contains both persistent adverse checks and
observed recoveries, the investigator revalidates every qualifying check in
one already-budgeted public GitHub observation. A recovery never hides a
different persistent failure. Original per-check classifications are retained
in the private report, and the optional sidecar exposes only fixed-label
aggregate counts; no check names, original state or raw reports are uploaded.

The public sidecar labels unresolved missing or nonterminal checks PARTIAL,
not completed. This does not grant repair, incident closure, PR merge, spending,
trading or any new execution authority. Current request, privacy, history
replay and production safeguards remain unchanged.

## Fair bounded first-response selection

When four or more public repositories show fresh, source-bound completed check
regressions at the same priority, the three available investigation slots rotate
deterministically by UTC hour. This removes alphabetical starvation for
first-response regressions, complementing the existing rotation of evidence
gaps, persistent adverse checks and observed recoveries. New regressions still
rank ahead of lower-priority categories, with no additional GETs, new cursor,
background task, state mutation or permission. Deferred repositories remain
counted in every receipt.

A completed provider observation is never evidence that a check was repaired.
Any changed source revision, unknown completed conclusion, missing check or
nonterminal check is surfaced as incomplete, not a green resolution.

## Complete same-source multi-signal revalidation (draft-only)

The standalone V7 investigation now reconciles the **entire observed
same-commit check set in one bounded provider observation**, even when a new
`success → adverse` regression occurs concurrently with another persistent
adverse check, an observed recovery and a previously completed check that
has disappeared or stalled. Earlier direct-deterioration selection hid
continuation evidence from the same repository.

All candidates still derive from original PUBLIC/ACTUAL events, exact source
SHAs, the full ledger chain and two fresh comparable observations. An
originally deteriorated check receives
`INITIAL_ADVERSE_TRANSITION`; disjoint checks retain their
`PERSISTENT_ADVERSE_OBSERVED`, `RECOVERY_OBSERVED_NOT_RESOLUTION` or
`EVIDENCE_GAP_REVALIDATION` label. Concurrent records must match repository,
revision and source-observation timestamp or the operation refuses all reads.
Contradictory classifications fail closed.

The high-priority new deterioration keeps its place in the fair
three-repository selection; continuation evidence from that same repository
is merged into it **without another GitHub request, a second queue entry, a
new event, a cursor or any state write**. Read-only receipts can therefore
distinguish a newly failing check, a different persistent failure, an
observed successful check and an unresolved missing check. The public
sidecar reports only bounded category totals and classifies unresolved
gaps/source changes as PARTIAL, never a verified repair.

All prior production, paid-call, trading, source-license, scheduler and
acceptance restrictions remain intact. No V7 runtime is released by this
draft.

## New V7 read-only temporal check evidence (draft)

Every eligible check revalidation can now summarize up to **12 successive
terminal GitHub observations** on one exact source revision from the
**original replay-verified SQLite ledger**, within the existing 48-hour
source-freshness window. The pure `brain.temporal` projection tracks:
consecutive adverse sampled conclusions, first timestamp *observed* in that
sample streak, total completed samples, how often sampled statuses flipped
between adverse and success, and whether the 12-sample display cap was
reached. A gap, unavailable/duplicated check, pending status, simulated
sample, source revision change or expired sample **breaks continuity**,
rather than being silently ignored.

The private investigation receipt and human-readable report disclose these
original measured observations alongside the newly fetched public GitHub
check status. Changes in provider status **do not rewrite original evidence**.
The reported timestamps are **sampling times**, not timestamps of actual
failure onset, outage duration, incident resolution or confidence that a
test is intrinsically flaky. Multiple changes are described only as
observed terminal-state movements, not a root-cause diagnosis.

The optional public sidecar publishes only fixed, names-free
`historical_adverse_streak_bands` counts (none / one / two / three or
more), a count of checks with multiple observed adverse/success movements
and a count of histories truncated at 12 samples. It does not publish
check names, repository names, event timestamps, raw state, API content,
private Markdown/HTML or raw error messages. Malformed historical data,
fabricated counts, inconsistent timestamps or mismatches between the
original plan and the observed check record are **BLOCKED** before a
complete advisory status can be claimed. Old receipts without this
optional metadata remain readable.

**No additional GitHub provider request, state writer, schedule, shared
cursor, automatic repair, third-party-code execution, charge, trade,
customer communication, merge or authorization** is introduced. All
existing V6 production and V7 draft-only governance boundaries remain
unchanged.

## Duplicate check-name quarantine, without hiding independent regressions

A real GitHub commit may have two check runs with an identical name. This
makes **that check name** ambiguous, not necessarily the entire repository.
Previously, the candidate's blanket `PARTIAL_AMBIGUOUS_CHECK_NAMES` exclusion
could silently suppress independently unique and verified regressions.

The V7 investigator now accepts original, ACTUAL_FRESH same-revision
comparisons with this **explicit partial-coverage classification**. The
canonical reducer already removes duplicate-named checks when creating
transitions. For continuation, the ledger is independently replayed, and
the old and new check lists are independently indexed. Only check names
that were uniquely identifiable in **both** original observations may
contribute persistent adverse or recovery evidence. A duplicate in the
newer snapshot must **never** be misclassified as a missing, completed,
adverse or recovered check. A formerly duplicated name does not establish
a valid earlier baseline. Unique checks may still be revalidated in the
existing one-GET-per-repository pass, including new failures mixed with
persistent failures, recoveries and genuine evidence gaps.

Every resulting investigation explicitly records the fixed Boolean
`partial_check_coverage`. Its operator report clearly states that
duplicate-name evidence was quarantined and **complete repository CI
coverage is not established**. The optional public sidecar reports only
`partial_check_coverage_repositories` as a bounded aggregate count and
downgrades the entire status to `PARTIAL_READ_ONLY`, regardless of whether
all individually selected checks were successfully revalidated. Malformed
Boolean flags are **BLOCKED**, not interpreted as truthy success.

All existing provider request limits, source gates, immutable original
ledger, artifact confidentiality, fair selection, human repair approval,
separate V6 acceptance, trading and spending restrictions remain intact.
This remains **V7 draft-only** and cannot authorize a production release.
