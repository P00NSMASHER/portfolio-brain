# Post-repair reliability observation

The `brain-12-hour-reliability` workflow observes the final protected-main source after each scoped repair completes. It has read-only GitHub permissions and cannot publish an independent acceptance decision or change state.

It replays original core artifact digests, state publication ancestry, required job steps and automatic scheduling provenance through the existing source verifier. It requires at least 43,200 seconds between qualifying monitor completions, gaps no larger than 5,400 seconds, original attempts only, and matching original repair origin receipts. Pending work remains COLLECTING; failed or retried originals cannot pass. Reports are retained as workflow artifacts. A successful workflow with COLLECTING is not a passed 12-hour test.

The observation uses a fixed completed-run snapshot and a bounded first 12.5-hour core window. Repair artifacts are bounded to terminal completion plus 30 minutes. Limits remain explicit and fail closed: 100 core runs in the window, ten inventory pages, 656 API calls. Exceeding capacity is incomplete verification, never truncated PASS. Current production cadence is approximately one core every 30 minutes. This is an operational observation, not proof of unlimited capacity, independent human review, or unrestricted autonomy. Existing independently credentialed six-hour acceptance remains separate.

## Failure recovery validation

- Transient read transport failures: at most three attempts, with bounded delay and timeout.
- Authorization denials, invalid JSON and admission failures: no silent retry or token issuance.
- Diagnostics: static nonsecret error codes; no provider bodies, credentials or arbitrary exception text.
- Durable queue crash: persisted INTENT survives reopen and blocks duplicate external writes after lease expiry.
- Existing full regression suite covers growing complete check history, shared request capacity, source drift, state delivery readback, conflicting writers and interrupted state operations.
- Observer tests cover full/short windows, gaps, pagination, pending cores, original failures, repair reruns, exact origin coverage and out-of-window budget isolation.

Two definition-only private dashboard helpers were removed. Archived workflow fixtures remain because active historical validators verify them. The backlog audit records exact-head dispositions rather than age-based deletion.

A final source change starts fresh evidence. The 12-hour result cannot be marked complete until actual unattended elapsed-time and follow-through evidence pass.

## Native scheduler collision coordination — October 29, 2026

A historical source completed separate native GitHub and signed Cloudflare cores
whose creation intervals overlapped, despite serialized state publication.
PR #785 made such cross-origin overlaps a hard denial of source acceptance.

The existing native core cron `7,27,47 * * * *` is retained, but moved
from direct `brain-cycle` execution into the already-scheduled `brain-clock`
watchdog. The existing watchdog cron `16,36,56 * * * *` and independent
Cloudflare Worker `*/10 * * * *` remain configured. No schedule or permission
is disabled, created, or widened. The same watchdog first examines source-bound
actual core runs: a recent successful core or an active writer suppresses
redundant dispatch; stale active writers fail closed. Only an overdue source
issues a GitHub-native watchdog dispatch, and its original scheduled-parent
provenance is independently replayed through GitHub.

Original accepted Cloudflare cores retain their signed P-256 origin receipts.
Fallback native cores use the source-bound `watchdog-origin.json` and actual
scheduled watchdog provider run. The verifier rejects manual origins, stale,
failed or retried clock parents, mixed origin artifacts, and overlapping
Cloudflare/native invocation windows even when both appear as
`workflow_dispatch`. The former source's PASS and overlap failure remain
historical evidence; the new protected release must collect a fresh
12-hour observation and independent source acceptance. Source-specific
monitor/core gaps, contiguous state history, and repair follow-through remain
required. Clock dispatch alone is never a completed core.

## Observation duration change — October 28, 2026

At the owner's explicit request, new releases use a 12-hour minimum instead of 24 hours. This is a prospective change: existing 24-hour receipts and failed runs retain their original source, criteria and outcome. No old failure is reclassified or evidence clock reset on the same source. The release containing this change starts its own source-bound evidence window. The 30-minute terminal allowance, 90-minute maximum intercore gap, first-attempt requirement, complete artifact replay and repair coverage checks remain unchanged. A 12-hour PASS is bounded operational evidence, not a guarantee of flawless future execution.
