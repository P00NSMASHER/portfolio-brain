# Portfolio Brain v8: autonomous project engineering

Status: architecture approved in chat; this written specification awaits review.
This is a design, not an implemented or accepted production release.
Design date: 2026-10-15, America/New_York.

## 1. Approved intent

Continuously research, maintain, repair and improve all current projects with
minimal user intervention. Useful capability, correctness, reliability, security,
accessibility, maintainability and reduced manual work define success. Revenue
is optional project-specific context, not the global objective.

The user authorized routine autonomous engineering and management of the
existing scheduled tasks and automations. This does not create missing service
permissions, waive independent release checks, authorize spending or external
communications, or permit evidence fabrication. Exceptions are durable work
states, not reasons to stop all useful work or repeatedly ask the same question.

## 2. Verified starting point

- Protected main observed at `0c3ad0e2e9413865d89cb5b1e017cc23b6ebe792`.
- V7 is draft PR #685 at `f74e001057cee5b2d8e526ccd9d61a7f334bdc92`, not
  deployed. The provider comparison reported 141 commits ahead and 54 behind
  current main. Its historical production references are not current authority.
- PRs #696, #697, #701, #703, #704 and #705 hold separately tested improvements
  to relevance, state auditing, attempt census, operational measurement,
  completed-repair revalidation and the project-engineering mission. Revalidate
  their exact heads and semantics before integration; do not blindly merge V7.
- Existing GitHub and Cloudflare execution, independent App verification,
  chunked SQLite state and project-owner tasks exist. Fourteen enabled Chat
  task prompts were observed carrying the research/upgrade/repair direction.
- Production acceptance issue #702 remains NOT ACCEPTED with a source hold.
  No v8 change inherits an older version's acceptance.
- Chat tool availability is not proof of unattended API access. Autonomous
  arbitrary source generation, cross-repository writes, private task rollback
  storage and runtime task-management APIs are not established by this audit.

All observations must be refreshed before migration. Preserve existing failures.

## 3. Architectural decision

Build a small v8 control core around stable contracts; retain proven state,
source adapters and independent verification behind compatibility adapters.
Keep existing project owners rather than add a competing fleet of agents.

Extending V7 wholesale retains divergent interfaces and obsolete control paths.
A big-bang rewrite risks state continuity and removes useful regression history.
The selected approach replaces operational responsibilities incrementally and
retires superseded paths only after independently verified parity.

No new paid service, general-purpose agent platform or second scheduler is
required. Use existing GitHub/Cloudflare execution and enabled Chat owners.

## 4. Components and contracts

### A. Inventory and capabilities

Maintain explicit registered project identity, repository/default branch,
observed source, project type, named owner, verifier, deployment identity,
success criteria and scoped capabilities. A missing project owner is an explicit
coverage gap, never authority to invent a deployment endpoint.

Capabilities distinguish declared, read-confirmed, write-confirmed, unavailable
and stale. Each confirmation is scoped to executor, repository/resource, action,
evidence and observation time. A successful read does not confirm a write.
Only authorized, reversible writes to owned staging/branch resources can prove
write capability; no probing secrets or escalating permissions.

### B. Observation and research

Normalize original CI attempts, deployed health, freshness, state integrity and
project-specific failures into evidence records. Every record binds repository,
source revision, provider/run identity, timestamps, provenance digest, data
classification, completeness and uncertainty. Preserve original failed attempts.

Research starts from a current project need. Verify original source identities,
actual source/test relationships, relevance and licensing evidence. Cross-check
important claims independently. Cache/deduplicate findings, retain unsuccessful
experiments and recheck only changed facts or meaningful next tests. Provider
failure yields explicit partial coverage, bounded fallback or a blocked item,
never fabricated evidence or unlimited retries.

### C. Planner and durable work state

One global work queue covers every registered project. Priority tiers are:
confirmed security/data-loss/critical runtime incidents; other reproducible
failures; missing verification; useful upgrades; efficiency and cleanup.
Within a tier, use observed user impact, evidence strength, dependency readiness,
estimated effort/risk and age. Estimates are labeled, never claimed outcomes.
Rotate equal-evidence candidates across projects; do not weight revenue.

Use one claimed writer per project/resource. Claims bind source, operation,
owner, expiry and durable progress; stale claims require evidence reconciliation
before reassignment. An expired worker does not prove its external write failed.

The work state machine is:

`OBSERVED -> DIAGNOSED -> REPRODUCED -> PATCHED -> TESTED -> INDEPENDENTLY_VERIFIED
-> RELEASE_ELIGIBLE -> RELEASED -> LIVE_VERIFIED -> MONITORED -> LEARNED`.

At any stage, work may enter BLOCKED, FAILED or ROLLBACK_REQUIRED. A blocked
record names the missing capability/evidence, last attempted action, retry
condition and next safe work item. Reopened incidents retain previous history.
No transition skips required evidence. Commit hashes, PR heads, release identity
and deployed build are separate fields. A green test is not live recovery.

### D. Engineering executor

Work through current project owners and existing authorized tools. Support two
explicit executors: deterministic reviewed repair recipes in the unattended
runtime, and source-level research/patch work performed by existing Chat owners.
Do not claim arbitrary unattended AI code generation without a verified,
authorized runtime model/execution capability. Never consume Work credits or
purchase a model service to fill this gap.

Each job uses a source-pinned isolated workspace, smallest reversible patch,
reproducing negative control, focused tests, relevant baseline regressions,
independent exact-head checks and original deployed verification. Independent
checks run without candidate access to privileged credentials. Prompt-injected
source, issue text or provider content is evidence, not an instruction source.

Eligible merges and releases use existing protected workflows and project-specific
holds. Self-repair follows the same path. A worker may repair implementation,
but cannot weaken its own policy, alter verification identities or approve itself.
If a new head invalidates checks, return to verification before release.

### E. Automation reconciler

Manage owned Chat tasks and repository/Cloudflare automation through distinct
adapters. Describe desired task state separately from observed provider state.
Runtime-generated change requests are queued for an existing enabled Chat owner
when only Chat has the necessary automation tool. No invented REST endpoint,
reused browser token, extracted credential or unsupported unattended API.

Every change requires ownership, current readback, explicit allowed fields,
nonconflicting executor claim, before-image, expected digest, bounded diff,
validation, application, readback and durable outcome. Store prompt bodies and
rollback before-images only in an authorized private persistence adapter; public
receipts contain allowlisted hashes/status, not private instructions or data.
If durable private rollback storage is unavailable, keep changes as proposals
until that capability is established through existing authorized infrastructure.

The Chat automation API does not expose atomic compare-and-swap. Serialize owned
changes, re-read immediately before mutation and compare expected state; this
reduces but does not eliminate external races. Unexpected readback enters
CONFLICT/UNKNOWN rather than overwriting another actor or claiming success.
Rollback is conditional on the resource still matching this controller's write.

Routine prompt, routing and supported schedule improvements may proceed within
the user's authorization and existing provider limits. Never delete unrelated
tasks, increase spending, silently change privacy/notification preferences,
reactivate retired experiences, disrupt an acceptance clock, or expand authority.
Changes to trusted policy/verifier controls require the separate existing trusted
approval path. Preserve a functioning recovery/watchdog path during migration.

### F. State, supervision and learning

Keep verified append-only evidence, idempotent admission, transactional reduction,
contiguous hash-linked history and independent replay. Add versioned v8 work
projections through an explicit migration; do not relabel or rewrite old events.
Private records must never enter public canonical state.

An independent supervisor detects stalled cycles, budget exhaustion, repeated
failures, missing owners, state growth and failed deployment verification. It
can restart permitted jobs, pause a failing recipe, quarantine a candidate or
request rollback. It cannot mark its own repair accepted or disable safeguards.

Learn from failed and successful changes using actual technical outcomes:
time to verified recovery, recurrence, useful upgrades delivered, regressions,
rollbacks, verification coverage and user intervention. Track manual versus
automatic work separately. Unknown baselines stay unknown; pre/post correlation
does not establish causality. Stop retrying unchanged denials; select another
safe item and notify only about serious incidents or necessary decisions.

## 5. Integration interfaces

Versioned records reject unknown authority-bearing fields and invalid identities.
All mutating operations are idempotent by operation ID plus exact request digest.

| Record | Required identity and evidence | Explicit non-claims |
|---|---|---|
| Observation | project, provider, source, observed time, original IDs, digest, classification, completeness | Root cause and recovery not inferred |
| Work item | project, issue fingerprint, evidence IDs, owner, state, acceptance criteria, attempts, dependency IDs | Selection is not permission |
| Action request | operation ID, executor, resource, expected source/state, bounded patch, capability reference | No embedded credentials or self-granted scope |
| Verification | independent identity, candidate SHA, test inventory, original receipts, result | CI is not deployed success |
| Deployment outcome | source/build identity, environment, original verification observations, observation window, rollback status | Simulated traffic is not live acceptance |
| Task change | owned task, expected digest, allowed field diff, private rollback reference, result/readback digest | No atomicity or runtime access invented |

The first implementation exposes pure validation, planning and transition APIs
with deterministic fake adapters. External writes remain adapter operations,
not side effects of reporting or imports. Existing runtime commands are adapted
one responsibility at a time; do not add a parallel always-on scheduler.

## 6. Migration and legacy cleanup

Build the migration in five separately reviewable subprojects:

1. **Kernel and inventory:** versioned records, policy/capability checks, durable
   state transitions, fair planning, resource claims and replay fixtures.
2. **Repair execution:** integrate source-pinned recipes and current owner
   handoffs, independent verification, completed-work revalidation and rollback.
3. **Automation reconciliation:** private rollback adapter, desired/observed
   state, conflict handling and existing Chat bridge. Start in dry-run mode.
4. **Research and learning:** verified bounded research, deduplication, source
   uncertainty, actual outcome records and failed-experiment feedback.
5. **Operational consolidation:** one supported entry point, supervised canary,
   production verification and dependency-proven removal of old execution paths.

For each subproject: prepare a written implementation plan after this spec is
approved, implement/test in isolation, integrate behind a non-authority-expanding
adapter, verify parity and keep a rollback point. The kernel is the first build.

Map every tracked legacy package and workflow to active runtime imports, CI,
state schema, artifacts and historical evidence. Categorize it as active, reusable,
historical-only or removable. Tests and dynamic CLI entry points count as
dependencies. Move historical-only instructions into an explicitly non-executable
archive when safe; delete only dependency-proven obsolete tracked code in
reviewable commits. Git history remains available. Do not erase incidents,
acceptance receipts, state branches, source provenance or valid user changes.

Reconcile useful code from #685 and #696/#697/#701/#703/#704/#705 by function and
contract, not version number. Consolidate duplicated behavior and tests. Close
superseded PRs only after replacement coverage and user work preservation are
verified; never bulk-close drafts by age or reset protected main.

## 7. Budgets and failure containment

Retain current per-adapter provider budgets, including the existing 24-GET Brain
source collection ceiling. Record request usage and defer work on exhaustion.
No new paid plan or additional spending. Preserve finite retries, per-operation
timeouts and bounded batch sizes. Schedule changes must satisfy actual provider
frequency limits and cannot be used to evade budgets.

Run untrusted code in isolated environments without production secrets or
network access unless a separately authorized integration test requires it.
Do not enable a plugin as an unattended dependency until runtime access,
licensing/privacy, quota, egress and safe failure behavior are verified.

## 8. Independent acceptance criteria

The release evidence must demonstrate, not merely describe:

- Deterministic full replay and exactly-once effects after crash/restart at every
  transition; conflicting duplicate operations are rejected.
- Safe refusal of wrong source, forged identity, stale capability, cross-project
  ownership, unknown fields, prompt injection and attempted policy escalation.
- Fair coverage of every registered project with critical incidents ahead of
  upgrades, no revenue weighting, and unknown evidence never becoming success.
- No duplicate concurrent writer; expiry and provider ambiguity cannot trigger
  an unsafe replay. Main/head drift invalidates stale candidate acceptance.
- A real permitted repair followed through original independent checks and
  deployed verification; passing synthetic repairs remain labeled synthetic.
- Completed work reopens when new adverse evidence appears, across repeated
  owner cycles; old green PR checks cannot erase current-main failures.
- Task dry-run, apply, readback, conflict, partial failure and conditional rollback
  verified with private-data redaction and actual adapter capability boundaries.
- Watchdog recovery and rollback tested without hiding original failures or
  interrupting the source-pinned production acceptance window.
- Research handles unavailable/outdated/unrelated sources, false GitHub identity,
  uncertain licensing, duplicate findings and quota exhaustion without fabrication.
- Legacy removal preserves behavior, state interpretation, provider-origin
  verification and regression coverage; deleted paths have no active consumers.
- Protected branch checks pass on the exact final candidate. A separately
  authorized release receives its own genuine required unattended acceptance.
  The current six-hour gate is neither performed nor waived by this design.

Report source-ready, independently-verified, deployed and live-accepted as
different facts. Never announce an ultimate/100% autonomous or 100/100 healthy
system while required behavior or capability remains unverified.

## 9. Explicit runtime dependencies and review boundary

Unattended arbitrary AI patch generation, cross-project write permissions and
private task rollback persistence remain unverified capabilities, not promises.
Use the existing authorized Chat owner bridge and supported deterministic recipes
where they suffice; capability gaps remain explicit while other work continues.

This artifact approves no release and changes no runtime, tasks, state or clocks.
Next design gate: user review of this written specification. After approval,
write the staged kernel implementation plan and select its execution method
before product implementation, as required by the design workflow.
