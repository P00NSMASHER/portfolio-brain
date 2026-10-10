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
        "created_at": "<original GitHub timestamp>",
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
