# V7 autonomous read-only investigation sidecar

## Why

The V7 evidence decision queue can select real, source-bound GitHub failures,
and `brain.investigate` can recheck them once, but a manual invocation cannot
provide unattended operations. This draft adds a **post-publication optional
job** to the existing `brain-cycle-v2` workflow. It does **not** add a
schedule, modify the writer, increase policy budgets, merge an upgrade, grant
execution authority, or affect the signed V6 acceptance window.

## Source-specific and least-privilege sequence

1. The existing `monitor` job first completes its original monitor, research,
   experiment, doctor, evolve, original nonforce SQLite state publication, and
   `brain-v2-cycle-...` artifact upload.
2. The new separate `readonly_investigation` job can run only after that job
   succeeded. The new job has `contents: read` and `actions: read` only,
   no state writer lock, no state publishing or downstream actions, and is
   configured `continue-on-error` so it cannot block a valid core result.
3. It downloads **the same core run and attempt** original evidence artifact,
   validates the original `delivery.json` schema, completed publication flag,
   original `run_id`/`run_attempt`, exact producer/source commit, workflow
   and read-only authority boundary. It rechecks the currently active
   protected `main` source before starting. Any ambiguity blocks follow-up.
4. It checks out exactly the **original published state commit** from that
   receipt using the read-only job token, never a mutable latest state branch,
   and checks the checkout SHA. The existing investigation CLI snapshots that
   SQLite database with an original read-only connection, verifies original
   ledger/report replay, exact source and zero backlog on a disposable clone.
5. A single `timeout 75s` bounded pass uses the existing GET-only GitHub
   adapter, current per-operation 24-request ceiling, and max-three repository
   cap. The sidecar honors the existing source freshness, rejection and STOP
   conditions; success of a check is never called a verified incident fix.
6. The sidecar publishes ONLY a fixed-schema sanitized status JSON containing
   counts and fixed outcome labels. Raw canonical SQLite, full original
   report, source paths, API responses, credentials and private Markdown/HTML
   are **not** uploaded as an investigation artifact.

## Honest results

- `OBSERVED_READ_ONLY`: optional follow-up finished with no deferred cases;
  this is **not** incident resolution, customer value or production acceptance.
- `PARTIAL_READ_ONLY`: incomplete, bounded or timed-out follow-up. Completed
  observations remain advisory, and unresolved work is not hidden.
- `BLOCKED_NO_VERIFIED_INVESTIGATION`: missing or untrusted origin, source
  drift, failed checkout, invalid report, or malformed evidence. Counts are
  neutral, never converted into a success.
- All outcome receipts hard-code `root_cause_verified=false`,
  `production_accepted=false`, `execution_authority=false`,
  `github_mutations=0`, `events_written=0` and `paid_calls=0`.
- Workflow and runner failures remain distinct from the original mandatory
  monitor/research/experiment/doctor outcomes. The optional job never resets
  the main state ledger, production configuration or historical receipts.

## Validation and rollout boundary

The synthetic tests cover accepted and forged delivery manifests, Boolean and
source/run identity confusion, absence of publication proof, sanitized
outcomes, partial work, invalid provider reports, no raw code/customer data
in public artifacts and least-privilege job isolation. Genuine original
signed-provider reports are still required for any claims of operational
acceptance. The current V7 draft must pass full exact-head Foundation CI and
the separate independent App verifier before being a candidate for a
separately authorized promotion.

**DO NOT MERGE OR DEPLOY DURING V6 ACCEPTANCE** (issue #684).
The original V6 `main` remains protected and its six-hour automatic
provider-origin window must finish without interruptions. A future V7
source transition requires its own authorization, exact merged SHA and
genuinely completed source-specific six-hour automatic acceptance.

This feature is **prepared on the V7 draft only**; no production autonomous
sidecar or real GitHub incident investigation is claimed here.


### Immutable-history continuity (extension)

The V7 sidecar runner now revalidates two classes that a one-off check
transition alone would miss: repeated completed adverse observations on the
same exact revision, and observed adverse-to-success recoveries. Original
immutable SQLite and report replay are verified first; no additional durable
state, queue, cron, credential, API quota, scheduled job or writer is created.
Its uploaded status JSON includes only a fixed-enumeration
`observed_followup_kinds` count map and no repository or check names.
Recovered check results never count as an independently verified fix. This
capability is draft-only until separate V7 release acceptance.

The V7 continuation also follows previously completed checks that go missing
or remain pending; their outcomes are labelled evidence gaps rather than
invented check recoveries. Only the fixed-allowlist aggregate category
`EVIDENCE_GAP_REVALIDATION` is added to the optional sanitized receipt.

### Fail-closed autonomous receipt coherence

Before publishing sanitized advisory counts, the sidecar verifies the
investigation's status, eligible/deferred/observed counts, configured
three-repository limit, and any per-check original-evidence classifications.
Impossible combinations (for example, no eligible work plus completed checks,
an apparently completed run with deferred work, or an incomplete provider read
without the requisite failed final observation) are BLOCKED. Check identities
and original per-check classifications, when provided, must exactly match
the corresponding investigation plan; malformed unhashable data is rejected
without exposing source contents. Previously valid historical schema-one
receipts remain readable.

Source-advanced, unavailable, nonterminal and otherwise unresolved check
evidence is classified PARTIAL rather than complete. Neither a green GitHub
check nor a successful GET establishes independently verified incident
resolution, release acceptance or downstream execution authority. All public
results remain fixed-schema and names-free; no new API quota, secrets, state
writer, cron changes, spending, trading, PR mutation or production deployment.

### One-GET multi-signal provenance (V7 draft)

A newly adverse check and different persistent, recovering or missing checks
on one unchanged source revision are now investigated together, with separate
original-evidence classifications for every check. The optional sidecar
preserves fixed-enumeration aggregate counts, never the check names,
repository identities or original ledger. One repository consumes the same
single bounded GitHub observation, not several reads. Unresolved gaps,
pending checks and source drift still produce partial, not complete, results.
This adds no release authority, new scheduled task, state write or trade.
