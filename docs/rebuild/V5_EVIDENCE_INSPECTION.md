# Portfolio Brain V5: independent six-hour evidence inspection

**This document is a source-review candidate, not an acceptance or deployment.**
Protected production V5 source at authoring: `35c1955bbfea1e2cd760ed39c8f6978ce5102f1d`.
The current V5 observation remains tracked in [issue #669](https://github.com/P00NSMASHER/portfolio-brain/issues/669).
The historical V2 FAIL, V3 BLOCKED and V4 PASS records are unchanged.

## Reuse of existing strict evaluator

`python -m soak_v3 window-v5 --manifest <local-readonly-evidence.json>` calls
`evaluate_v5_window()` in the existing `soak_v3.audit` module, which delegates
the event classification, mandatory steps, immutable artifact/state agreement,
state-parent continuity, exact-source binding, provider-scheduled versus
unverified/manual dispatch distinction, and maximum 5,400-second completion
gap to the **same** `evaluate_window` function used by V3. V3 keeps its
original two-hour minimum and interface. V5 supplies a 21,600-second minimum.
The CLI prints `NONAUTHORITATIVE_EVIDENCE_INSPECTION` and never claims
`PASS`; even six hours of perfect input is `PRE_POSTVALIDATION` pending
the separate governed release decision.

This mode additionally requires a **complete external provider core-run
inventory**, with a distinct (run ID, attempt) record for **every** core in
the observation period and one matching record in the supplied run evidence,
including failed, pending and manually triggered cores. Dropping a reported
failure produces `V5_CENSUS_RECORD_MISMATCH`. A success receipt from a
Cloudflare-dispatched `workflow_dispatch` contributes to the automatic
completion clock **only when an independent collector supplied all four**
`cloudflare_cron_v1` provenance checks: matching source SHA, provider Cron
event, verified signed P-256 origin, completed core receipt and state
verification. `FRESH`, dispatch acknowledgments, self-labelled scheduled
runs, a push, manual dispatch, a skipped verifier and provider metadata alone
are not substitute successful completed cycles.

### Strict V5 original ZIP verifier (review candidate)

`python -m soak_v3 artifact-v5 --manifest <artifact.json>` uses the existing
provider-digest-bound historical delivery/preflight/doctor checks as its
baseline, then verifies every ZIP member's CRC and all mandatory workload
report files: `report/report.json` (monitor), `research/report.json`,
`experiment/report.json`, and `doctor/report.json`. It requires all four
to be PASS on the same exact source with zero pending events, ordered
nonregressing state sequences, matching final experiment/doctor sequence and
canonical hash, the expected monitor/research operation labels, and the
doctor's explicit mandatory workload PASS map. A ZIP whose original SHA-256
matches provider metadata but has a broken noncritical member fails rather
than being treated as complete.

`artifact-v5` is **local original-byte consistency inspection** only:
the expected ZIP digest MUST come from independent original GitHub provider
metadata. These checks are not independently signed Cloudflare provenance,
GitHub run-census completeness, remote state publication, or V5 final
acceptance. The existing `artifact` mode remains unchanged for historical
V3 replay; use the strict mode for future V5 original ZIPs. Do not merge
this source review during the current protected-source acceptance period.

Each invocation first checks the **strictly under 20,000,000-byte**
input size, reads no more than 20,000,000 bytes, rejects a read-size
change, and compares those exact bytes to the independently supplied
provider SHA-256. The historical and strict V5 ZIP parsers now both
open `io.BytesIO` views of **that one already hashed byte buffer**;
neither reopens the source path after hashing or between mandatory
report/CRC checks. A same-size original-file substitution during
verification therefore cannot silently substitute un-hashed reports.
The legacy `artifact` mode's receipt scope and required fields are
otherwise unchanged. The V5 mode additionally checks **every** member
CRC and all four original mandatory workload receipts. Adversarial
tests enforce both swap boundaries and the bounded pre-read behavior.

### Ambiguous JSON receipt refusal (V5-only review hardening)

`artifact-v5` now parses delivery, preflight, monitor, research,
experiment and doctor JSON as **unambiguous evidence**. Duplicate keys
(including nested mandatory-workload keys), non-finite numbers such as
`NaN`/`Infinity`, and numeric overflows such as `1e999` fail closed
even when ZIP SHA-256 and member CRCs are valid. The root receipt must
be an object, and every mandatory `pending_events` count must be a
real JSON integer, never `false` interpreted as zero.

These checks reuse the same original SHA-256-bound in-memory ZIP bytes
and existing workload consistency validator. The historical `artifact`
V3 parsing contract stays unchanged; only `artifact-v5` is strict.
Malformed originals remain rejected evidence, not repaired files.
Passing strict local inspection does **not** authenticate the provider
digest, original scheduler, complete failures or V5 terminal acceptance.

### V5 raw-state capacity and immutable authority binding

Use `python -m soak_v3 state-v5 --manifest <local-state.json>` only for a
separately acquired, **immutable**, original GitHub-published `state.sqlite`.
The older `state` mode retains its **25,000,000-byte** maximum unchanged;
the V5-specific `state-v5` verifier permits **at most 64,000,000 bytes**,
using the same independent SQLite integrity, event/ledger SHA-256 replay,
canonical report, exact source SHA, zero-pending and public-only checks.
Both readers check file size **before** reading, read at most their maximum
plus one byte and reject a locally changed-size snapshot. The exact bytes
used for SHA-256 are then copied into an exclusive 0600 file inside a
private, disposable directory, opened by SQLite in `mode=ro&immutable=1`.
The original input path is **not** reopened after hashing; a same-size
replacement cannot cause SQLite to inspect different bytes from those whose
SHA-256 is reported. Temporary bytes are removed on success and failure.
The input file is never chmodded, initialized, repaired, rewritten or published.
This only proves local byte-consistency, **not** original provider provenance.

The genuine October 10, 2026 source-bound durable state commit
`0152de8a51325bd177fa652f7b69ea1f82e0f86e` contains an original
GitHub tree entry `state.sqlite` of **28,778,496 bytes** (Git blob
`95ff018236fe2329f3f4b08e5d03678999a06b11`), which the previous
V3-sized reader necessarily rejected before ledger inspection. This
V5-only review candidate fixes an **offline verifier capacity mismatch**,
not the earlier production research or preflight outages.

The `state-v5` result's local `sha256` MUST be matched independently to
the originally fetched Git blob/provider bytes. Its expected source, chain,
sequence, state parent/commit, original ZIPs, Cloudflare P-256 source and
complete failed-run census must be authenticated separately. A user-supplied
manifest, plausible database or local `"status":"PASS"` is **never** V5
automatic-runtime, deployment or terminal acceptance.

### Canonical V5 SQLite event and report evidence (review only)

`state-v5` now matches the original reducer's canonical JSON serialization
byte-for-byte, not just the hash of a permissively parsed object. Every
stored event and the terminal report must be canonical, with unique JSON
keys and finite numbers throughout nested structures; both report backlog
and sequence must be **real JSON integers**, not `false` or `true`
silently compared as Python 0/1. The report's embedded source must match
the exact independently supplied source. After SQLite page integrity,
the V5 mode also checks `PRAGMA foreign_key_check` before ledger replay;
ordinary `integrity_check` alone does not detect orphan relationships.

All checks run on the already SHA-256-bound private sealed snapshot, using
the **existing canonical digest/ledger algorithm** and strict JSON parser,
not new authority or a new source writer. Historical V3 `state` parsing
and its 25 MB cap remain unchanged. The stricter V5-only checks reject
noncanonical or contradictory original bytes rather than normalizing,
repairing, or relabelling them. Original GitHub/Cloudflare provider
authentication, signed scheduler provenance, failure census and a distinct
six-hour terminal acceptance remain separately necessary.

### Provider-backed V5 inspector parity in Foundation CI (candidate only)

The existing **network-capable** `tests/test_v5_deployed_state_compatibility.py`
already fetches the genuine `brain-state-v2` commit through Git and verifies
the original SQLite bytes against the Git blob SHA-1 and a local SHA-256,
then independently replays the complete ledger using its existing strict
read-only reader. This candidate now also runs
`soak_v3.audit.verify_v5_sqlite()` on **the same immutable original file**
before producing any disposable new-source report, and requires exact
agreement on original byte SHA-256, persisted report source SHA, state event
sequence, canonical chain and zero pending events. If the snapshot exceeds
the historical V3 25 MB limit, the old `verify_sqlite()` must continue to
reject it while the bounded V5 reader succeeds.

The network test reuses the **same fetched bytes**; it adds no GitHub API
queries, dispatches, state pushes, or acceptance writer. It skips outside
supported GitHub Foundation push/PR runs, rather than fabricating
provider-backed evidence in an offline sandbox. The source/state receipt
labels this separately as `PASS_SEALED_PROVIDER_BYTES_NOT_ACCEPTANCE`.
A successful result is **read-only cross-validation of a GitHub state
snapshot**, not proof of original Cloudflare `scheduled()` provenance,
all workflow artifacts, complete failure inventory, protected deployment,
or the mandatory six-hour uninterrupted V5 automatic execution.

### Original GitHub run/job clock binding (V5-only, read-only)

The six-hour clock uses **completed GitHub monitor-job times**, not a
caller-typed completion timestamp. For each `completed` census row the
independent collector must capture original workflow-run `created_at` and
`run_started_at`, plus the original `monitor` job obtained from the
**attempt-scoped** GitHub Actions jobs endpoint
(`GET /repos/{owner}/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs`).
Persist the exact selected job's `id`, `run_id`, `head_sha`, `name`,
`status`, `conclusion`, `started_at` and `completed_at`; include
`attempt_scope` as an independent collector annotation identifying
the attempt in the REST URL, **not as a claimed native job field**.

`window-v5` now requires an explicit provider run attempt and one unique
completed `monitor` job for each completed core. It rejects mismatched
job run/source/attempt identities, missing job times, incongruent job
status/conclusion, backwards timestamps or an altered manifest start or
completion. Provider chronology must satisfy
`created_at <= run_started_at <= job.started_at <= job.completed_at <= now`.
For queued/in-progress cores, no completed-time proof may be supplied in
the run manifest; these cannot contribute completed automatic cycles.
Every failed core remains in the original census and still fails the
underlying unchanged reducer.

This is a **consistency gate over separately collected data**, not an
authentication mechanism for a user-written JSON manifest. Obtain full
provider pages, retain original API evidence, and independently corroborate
job/run identity before preparing the manifest. If the collection tool drops
job timing fields, obtain the original GitHub REST job metadata instead of
guessing times. A run's `updated_at` is not by itself proof of the
monitor job's exact completion. The V3 two-hour evaluator and its input
shape are unchanged, and V5 still returns at most `PRE_POSTVALIDATION`,
never an authoritative PASS.

### Required evidence acquisition before supplying the manifest

Acquire independently from original GitHub and Cloudflare providers, not
from a claimed summary or a hand-written JSON file. At minimum:

1. Freeze current protected `main` SHA. Enumerate **all** GitHub core runs
   over the exact acceptance interval, across every status, attempt and trigger,
   with complete pagination and fresh membership confirmation. Record failures
   even when they would spoil the outcome.
2. For each candidate automatic run, independently match the original
   Cloudflare `scheduled()` provider log to the signed P-256 envelope verified
   by the GitHub core. Confirm exact production SHA, completed SUCCESS, all
   mandatory steps, and doctor PASS with zero pending events. A `FRESH` log
   is a useful liveness observation, not a cycle.
3. Download original GitHub run artifact ZIP **bytes** and independently hash
   them against GitHub's actual artifact metadata and embedded delivery
   receipt. Fetch the published state bytes at the exact Git commit, verify
   the Git blob hash, original SQLite SHA-256, integrity/foreign keys, complete
   canonical event/ledger chain, expected source and zero backlog. Use the
   existing `soak_v3.audit.verify_artifact` and `verify_sqlite` readers;
   do not create parallel hash or ledger algorithms.
4. Match every run's published state commit to its captured original state
   parent using nonforce ancestry, verify each state sequence and hash
   against original ZIP evidence, and require no missing/rewritten state.
5. Only after a **minimum 21,600 seconds between the first and last
   independently qualifying successful completions**, with no qualifying
   gap over 5,400 seconds, perform a **separate terminal independent audit**
   of provider chronology, excluded events/failures, full source state,
   artifact provenance, policy, and historical acceptance refs. This CLI
   cannot write or independently certify that terminal receipt.

### Local input shape, deliberately non-authoritative

```json
{
  "source_sha": "<40-char exact protected SHA>",
  "current_main": "<40-char independently fetched protected SHA>",
  "first_state_parent": "<40-char original state commit>",
  "started_at": "2026-10-10T01:50:00Z",
  "deadline_at": "2026-10-10T09:50:00Z",
  "now": "<actual independent observation instant>",
  "inventory": {
    "coverage_complete": true,
    "provenance": "GITHUB_API_PROVIDER_METADATA",
    "soak_pass": false,
    "core_runs": [
      {
        "run_id": 123,
        "run_attempt": 1,
        "head_sha": "<40-char exact source SHA>",
        "event": "workflow_dispatch",
        "created_at": "<original GitHub run created_at>",
        "run_started_at": "<original GitHub run run_started_at>",
        "job": {
          "id": 456,
          "run_id": 123,
          "attempt_scope": 1,
          "head_sha": "<40-char exact source SHA>",
          "name": "monitor",
          "status": "completed",
          "conclusion": "success",
          "started_at": "<original attempt-scoped job started_at>",
          "completed_at": "<original attempt-scoped job completed_at>"
        },
        "status": "completed"
      }
    ]
  },
  "runs": [
    {
      "run_id": 123,
      "attempt": 1,
      "source_sha": "<40-char exact source SHA>",
      "event": "workflow_dispatch",
      "started_at": "<original GitHub started timestamp>",
      "completed_at": "<original GitHub completion timestamp>",
      "status": "completed",
      "conclusion": "success",
      "steps": "<dictionary of all required step outcomes>",
      "artifact": "<independently verified ZIP/hash/doctor metadata>",
      "state": "<independently verified remote state and parent>",
      "external_clock": {
        "kind": "cloudflare_cron_v1",
        "source_sha": "<40-char exact source SHA>",
        "provider_cron_verified": true,
        "signed_origin_verified": true,
        "core_receipt_verified": true,
        "state_verified": true
      }
    }
  ]
}
```

Angle-bracket placeholders above are **not executable proof**. Caller-provided
boolean labels and count matching cannot authenticate original GitHub or
Cloudflare evidence. This tool is deliberately limited to analyzing evidence
**after** independent provider collection and original-byte checks; it never
fetches providers or mutates the live repository, protected source, state,
Cloudflare Worker, schedules or past acceptance records.

### Release boundary

Keep this entire inspection upgrade on an isolated **draft PR** and **do not
merge while the accepted-source six-hour V5 observation is underway**.
A merge creates another protected SHA and restarts the source-bound acceptance
clock. The test-only V3 thresholds remain unchanged. Source validation
and real-state replay on a PR are not a production automatic acceptance cycle.
