# Restart-safe owner repair follow-through

**Scope:** This module improves Portfolio Brain's ability to finish technical
repair work instead of repeatedly reporting the same issue or forgetting an
unchanged blocker. It is an optional *offline/read-only decision engine* used
by the existing project owners. It does not grant new GitHub credentials,
scheduled tasks, default-branch writes, real customer contact or source
promotion, and it cannot replace the independent verifier.

## What is now automated in code

- A source-bound candidate is retained as **OBSERVED** until its actual owner
  confirms reproduction/implementation. It is not magically marked patched.
- Repeated source and CI evidence reuses an existing owner and PR. On a
  two-cycle stall, the next operation becomes inspect/resume, never silently
  drop, duplicate a branch, or pretend the finding is resolved.
- Exact PR/CI source movement reopens the same owner fingerprint with a new
  source evidence key and resets retry accounting. Repeated red regressions
  are bounded to two meaningful corrective revisions per cycle.
- Independently verified CI is separated from a release decision. A separate
  reviewer must approve the source-specific gate; a green draft cannot mark
  itself deployed.
- A closed PR that disappears from the latest open-PR sample is **carried
  forward** until its provider identity and current-main evidence are checked.
- Only a GitHub provider receipt showing the same source PR, closed+merged
  state, exact current-main merge SHA, and complete named main checks from
  the trusted GitHub Actions App 15368 is classified as
  `MAIN_SHA_AND_REQUIRED_TECHNICAL_CHECKS_MATCH_NOT_PRODUCTION`.
  RETALLY requires original `release-gate` and `freight` checks; App
  Factory requires original `test`, `browser`, and `manufacturing`
  checks. Missing, incorrect-app, wrong-SHA, incomplete, or adverse checks
  fail closed. A squash merge followed by further main commits needs
  *separate ancestry confirmation*: equality with the latest main is not
  assumed.
- Confirmed technical-main items stay in the private history even if they
  stop appearing in the active discovery set. Their presence never claims
  live service deployment, revenue, real buyer adoption or signed Brain V6
  source acceptance.

## Source-bound CLI for existing owners

Each existing project-stage report contains
`autonomous_repair_queue`, `autonomous_repair_followthrough`, and the
latter's `next_history` private continuation rows. They can be replayed on
subsequent existing owner runs without a new automation.

Prepare `queue.json` by extracting `autonomous_repair_queue` from the
original report.json into a private directory. Then run:

```sh
python -m brain.repair_followthrough_cli \
  --current /absolute/private/queue.json \
  --cycle 1945 \
  --history /absolute/private/previous-run/report.json \
  --provider /absolute/private/fresh-github-proof.json \
  --output /absolute/private/current-run
```

For the first run omit `--history` and `--provider`. On the next run, pass
the prior private `report.json` directly: `next_history` is extracted
automatically. An owner can safely update history status only from genuine
source events: `CLAIMED`, `REPRODUCED`, `PATCHED`, `CI_RED`,
`CI_GREEN`, `INDEPENDENT_GREEN`, `DELIVERY_REQUESTED`,
`BLOCKED_EXTERNAL`, `MAIN_TECHNICALLY_VERIFIED`. The CLI never
self-certifies these statuses.

The optional provider JSON is an array of **fresh, directly verified GitHub
API facts**. One example after a verified GitHub squash merge is:

```json
[
  {
    "repository": "P00NSMASHER/x402-product-factory",
    "pr_number": 46,
    "source_head_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "pr_state": "closed",
    "merged": true,
    "merge_commit_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "current_main_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "main_checks": [
      {"id": 1, "name": "test", "app_id": 15368, "head_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "status": "completed", "conclusion": "success"},
      {"id": 2, "name": "browser", "app_id": 15368, "head_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "status": "completed", "conclusion": "success"},
      {"id": 3, "name": "manufacturing", "app_id": 15368, "head_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "status": "completed", "conclusion": "success"}
    ]
  }
]
```

**All SHA and ID values in this example are illustrative, not actual
evidence.** Never use it as a provider receipt. The source identity should
be independently read from GitHub, including the specific original check
app, before the report can interpret it. JSON schema validation does not
cryptographically authenticate an operator-supplied provider response.

## Operator actions and hard holds

The existing hourly Portfolio Executive Director coordinates repair ownership.
Freight Product Director and App Factory own implementation; distinct QA
owners must run actual source-specific checks. Normal source/testing changes
may be delivered through existing owner-authorized SHA-guarded routes when
they genuinely satisfy protected review gates. **This code itself never
merges** and never authorizes new production privileges.

Keep RETALLY legal registration deferred until a real first customer and
continue to require independent authorization for real buyer contact,
payments, customer data, credentials, subscriptions, or financial decisions.
Keep the Portfolio Brain signed six-hour V6 acceptance source frozen until
the independent acceptance path closes. Preserve original failure histories,
15 existing task cadences, disabled alerts and child privacy. Treat a
technical-main PASS as different from actual production-runtime verification.
