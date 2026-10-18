# Project Genesis: first isolated increment

Baseline: `d25b54041341089482ad55e5d270171879e186b1`.
Authoritative full-requirement inventory: [V9 Capability Matrix](V9_CAPABILITY_MATRIX.json).
This branch does not activate v9 in production.

## Verified baseline and limits

Read current main, repository permissions (owner admin/push), issues #702 and #689,
their recent coordination evidence, active v8 source and workflows. No competing
v9 PR was observed in the open-PR inventory. Local shallow checkout matched main.
The local execution service then disconnected before tests could run.
GitHub Actions must supply original results; no local passing result is claimed.

Issue #702's recent comments supersede its historical body. The current d25 source
has a pending source-specific six-hour hold, with first independently recorded
automatic completion 2026-10-17T22:52:04Z. This is a cited historical checkpoint,
not a terminal acceptance performed here. Existing review-only #717 owns terminal
verification; this program does not duplicate it or reset the clock.

Current Actions readback includes successful d25 core 39094472684 and successful
#717 Foundation 39093584833 / verifier workflow 39093711862. A successful workflow
does not establish original ZIP/SQLite replay or live deployment. Current Worker
deployment and quota usage were not independently re-read in this increment.

## Coherent architecture

1. Observe: reuse project inventory and original-provider source observations.
2. Compile: bind a bounded mission DAG to immutable v8 work identities and repo heads.
3. Resume: derive progress from the existing private KernelJournal, never parallel
   mission-state copies. Unknown external writes and unreleased resource claims
   prevent scheduling. A changed head requires a new source-bound mission.
4. Execute: later adapters must acquire journal claims transactionally, persist
   intent before external writes, reconcile uncertain results by provider readback,
   and enforce repository-specific authority. This increment has no executor.
5. Evaluate: preserve original failure, positive/negative test, CI and independent
   acceptance evidence; never promote TESTED into delivered or learned.
6. Deliver: existing independent protected release and new-source acceptance only.
7. Learn: authenticated outcomes feed reusable capabilities and bounded experiments.

The initial mission planner is a read-only local scheduling projection, not a
transactional dispatch reservation or a deployed command OS. Multiple consumers
must not act on a plan without a fresh atomic claim and source/authority checks.
Candidate-owned records and hashes establish consistency, not independent trust.

## Increment sequence and acceptance

A. Mission compiler + replay projection + full capability matrix. Exercise cycles,
missing dependencies, duplicate identity, source drift, unresolved external writes,
claims, restart, corruption and resource bounds.
B. Add independently reviewed execution adapters for one existing low-risk recipe;
prove real resume/reconciliation and distinct implementer/verifier ownership.
C. Demonstrate authorized two-repository delivery with each repo's original checks,
runtime outcome and rollback proof. Never infer write permission from Brain access.
D. Capability Forge: compare alternatives under immutable externally held benchmark
inputs, negative controls and compute limits; reuse a verified tool in a second repo.
E. Portfolio telemetry, durable research missions and experiment selection.
F. Frontier prototypes only where measurable: bounded candidate tournaments,
fault injection in isolated environments, causal hypotheses and source-linked proof.

Existing independent App 5121826 publishes through trusted main controls and runs
candidate regressions in network-disabled containers. This is separately executed
regression evidence, not an immutable candidate-independent research benchmark.
Additional immutable benchmark/criteria custody is required for self-improvement.

## Safety and recovery

No workflow, Cron, task, release gate, credential, quota or production-state changes.
No hosted model service, autonomous specialist runtime or cross-project deployment
is established by these files. No new paid service or compute purchase.
Preserve v8 journals and production unchanged. Discarding this unmerged branch rolls
back this increment; local plans can be regenerated from the same mission/journal.
Corrupt journal or changed source must stop planning, never erase evidence.
No v8 component retires until its replacement proves independently verified parity.

## Evidence checkpoint

Implemented source and original CI are recorded on this PR at exact revisions.
Full capabilities 27/29 remain SPECIFIED because a local foundation does not satisfy
the complete mission compiler / Portfolio Command OS requirements. Other full v9
requirements remain NOT_STARTED until verified against their stated scope; the matrix
records historical components to reuse without falsely resetting historical facts.
Production merge, runtime adoption and measured portfolio improvement: none.

## Original protection readback

Ruleset 24182301 (`portfolio-main-protection`) is active, includes main with
no exclusions or bypass actors, prevents deletion/non-fast-forward updates,
requires PRs and resolved threads, and requires strict exact-source checks
`validate` from App 15368 plus `portfolio-phase1-gate` from App 5121826.
The observed required approving-review count is zero; this does not waive the
user's separate independent review and source-specific acceptance requirements.
Only Portfolio Brain repository permissions were checked in this increment.

## Offline entry points

`python -m brain.v9 compile --input input.json` emits a JSON envelope whose
`result` is the mission manifest. Input has exactly `work` (validated v8 rows),
`source_heads` (repository-to-immutable-SHA map), and `max_parallel` (1–5).
Preserve that result as mission.json in the existing authorized private workspace;
the compiler does not create a second state store.

`python -m brain.v9 plan --mission mission.json --heads heads.json --journal /private/kernel.sqlite --now 2026-10-18T04:00:00Z`
reopens the existing private journal read-only and emits the plan. The heads file
is an independently collected observation supplied by the caller, not a permission
grant. The command neither executes jobs nor authenticates those observations.
Same-repository tasks serialize conservatively, including case-insensitive aliases.
All replay event times, including released claims, must precede the projection time.

On malformed input, unknown writes, stale source or corrupt state, retain the
original manifest/journal and obtain fresh evidence; never edit history to unblock.
