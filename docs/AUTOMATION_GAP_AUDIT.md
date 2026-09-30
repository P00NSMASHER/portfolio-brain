# Automation-gap audit — 2026-09-30

## Outcome and scope

Live main is `4cbc9525d83da12bd6a726d188d731eb92a83ccb`, not the September 25
scratch foundation. GitHub has 437 files and durable state records steps 0–25
complete. Do not restart that build. The sampled latest 100 Actions runs contain
55 runs on this exact main head; **all 55 failed**. Other sampled PR runs include
successes, which do not establish main health. This is a point-in-time sample,
not a full history or independent security certification.

The immediate shared failure is canonical artifact discovery, not absent scheduling:
`Artifact scan incomplete at page bound; checkpoint/archive required`.
Run/job evidence and pinned source blobs are in `AUTOMATION_GAP_EVIDENCE.json`.
No product repository, credentials, policy, schedule, deployment or runtime was changed.

## Concrete dependency map

| Producer / trigger | Durable output | Consumer / dependency | Current gap |
|---|---|---|---|
| Hourly sync, main push, observation dispatch | Runtime cursor/observation state; immutable transition | Sole state reducer; daily rebuilding; dashboard | Canonical restore fails before observation; downstream repo push forwarding not established by this audit |
| Daily learning / weekly synthesis | Learning/uncertainty/experiment/allocation/repair/transfer reports; runtime state; governed model receipts | Scheduler, dashboard, reporting | Canonical restore dependency; reports mix live learning with checked-in memory/graph ledgers |
| Hunter every six hours / dispatch | Exact-revision findings, negative knowledge, strategy telemetry, proposal inbox, heartbeat | Reducer -> scheduler Researcher review | Restore failure prevents search; review is not implemented reuse or verified project value |
| Scheduler hourly / dispatch | Leased work, execution receipts, Hunter proposal reviews, heartbeat | Reducer; notifications; dashboard | Default handlers cover HUNT/RESEARCH/INTEGRATION/EXPERIMENT only; REPAIR/TEST/VERIFICATION defer |
| Immutable producer events after actual uploads | Hash-bound state transitions in Actions artifacts | Reducer on producer completion -> canonical snapshot | Repository-wide artifact scan exhausts 20 pages; reducer cannot publish |
| Canonical snapshot | Eleven validated continuation domains | Every production reader; watchdog | Shared availability bottleneck; expiring artifacts and finite replay require archival/checkpoint lifecycle |
| Cost watchdog hourly / producer completion | Liveness receipt; bounded cancellation/dispatch | Existing workflows | Also restores canonical cost state first: recovery depends on failing subsystem |
| Agent heartbeat sweep every two hours | HEALTH_CHECK telemetry | Reducer, dashboard | Connectivity telemetry is explicitly not substantive work |
| Model-value proof, feedback and learning bootstraps | Independently checked technical outcome, model feedback, learning observations | Reducer; daily learning; Hunter strategy | Push-marker/manual triggers, not a general recurring proof-completion consumer |
| Factory reusable workflow | Isolated candidate branch/commit/PR; heartbeat | Protected PR validation and independent verifier | No caller found in current workflow set; factory producer not enrolled in reducer caller map |
| Notification cycle every six hours / dispatch | Deduplicated alert state and GitHub alerts | Owner/dashboard | Depends on canonical restore; cannot substitute for external outcome evidence |
| Dashboard hourly / producer completion | Sanitized snapshot/history, preview, Pages output | Owner | Restore failure blocks fresh publication; existing Pages capability grants no new deployment authority |
| REPO-001 scheduled accelerator scouts | Scout queue/digest committed in source repo | Existing TI intake and project adapters | Parallel discovery lane; do not replace with another Hunter or assume automatic ingestion of every discovery |
| ABVM scheduled teacher refresh | QA-checked school pack, Pages/live proof, health artifacts | ABVM health dashboard; portfolio adapter | Product automation exists independently; no inherited deployment authority |

Normal planned chain: producer -> validated state artifact + immutable event -> sole
reducer -> canonical snapshot -> next producer. Producer jobs share a writer lock;
the reducer uses a separate lane so pending-state barriers can clear. This is existing
infrastructure worth preserving, not a reason to build a competing event bus.

## Verified blocker and existing repair

Scheduler run `36680482876`, Hunter run `36676069015`, and reducer run
`36680613474` all fail at the same bounded scan. Workload checks pass; useful
execution steps are skipped. The scan collects all repository artifacts until a
short page, filters by timestamp only afterwards, and throws after 20 full pages.
Thus unrelated/old artifacts consume the scan budget even when a time boundary exists.
Synthetic tests reproduce this exact source-method behavior without credentials/network.

**Existing PR #207 already repairs this outage.** Its head is
`01220d60a86ea28b11e21680e70e0427795b831e`; foundation CI run `36677104835`
succeeded. The inspected diff adds reducer-specific snapshot discovery and an
overlapping event window. It is still open and not main. This audit neither
independently certifies nor merges it. Review concurrency, provider ordering, pagination,
digest/identity checks, unread events and old-snapshot ambiguity before promotion.
Existing open PR #168 addresses real candidate-worker execution; PR #201 concerns
durable learning/uncertainty. Assess them before implementing competing repairs.

## Where queues and evidence stop

- Executor returns `NO_EXECUTION_HANDLER` for unsupported work types and leaves
  them queued. Successful handlers mark scheduler work COMPLETE themselves;
  this represents handler completion, not independent project-value verification.
- Integration assesses transfer readiness; experiment handling inspects existing
  action/outcome ledgers. Neither means candidate implementation or a new experiment ran.
- State-journal domains include runtime, heartbeat, Hunter, proposals, reviews,
  scheduler, cost, model feedback, learning, notifications and history. Native
  memory/graph/experiment/repair/factory outcome ledgers are not journal domains.
  General verified-outcome ingestion into those engines is not proven here.
- A restore failure publishes no mutated domain state; the event emitter correctly
  returns `emitted: false`. Failure survives in Actions/logs, not as a domain mutation.
  A separate fault channel could support recovery without weakening event admissibility.
- The Step 24 canary uses a local cursor mirror, no network and no model calls.
  It verifies bounded deterministic continuation, not the full live hunt/build/
  independent-audit/canary/promotion/outcome loop requested now.

## Reuse, drift and authority

Truth and Value Memory adapters describe pinned upstream receipt/call contracts;
the universal graph is an envelope/projection, not a replacement native engine.
The live REPO-001 blobs for truth, value memory, Hunter bridge and production
learning engine still match their recorded pins despite a newer repository head.
No full upstream regression or live database integration was performed.

Live `governance/boundaries.json` is absent. `docs/ARCHITECTURE_CONTRACT.md` still
describes a foundation, while README/operating policies describe operational systems.
Historical optimization status says model routes are disabled, while the current
provider registry enables Luna/Terra/Sol. A enabled registry is not proof of usable
credentials or successful provider calls.

Current repo policy allows bounded customer email through scheduled ChatGPT Gmail
connector tasks and protected autonomous merge. Both conflict with the current
owner instructions for this audit. The Gmail path is also a ChatGPT task dependency,
even though core GitHub observation does not require interactive prompting.
Do not invoke either capability. Reconcile policy explicitly before expanding operation.
Preserve human-gated production/communications/financial/destructive/child-facing actions,
live-trading prohibition, sanitized-only public persistence and REPO-006 access review.

## Highest-value next step

**Restore trustworthy bounded canonical-state discovery through existing PR #207.**
It reconnects many already-implemented workers at once. Do not merely increase
page limits, silently discard conflicts, reset state, delete artifacts, or widen authority.

On CONTINUE: inspect PR #207's current delta and independent-verifier evidence,
add/run focused recovery regressions as needed, and follow the authorized protected
promotion gate. Then observe scheduled producer -> reducer -> next producer continuity
on the exact promoted main head with preserved state hashes and no ChatGPT intervention.
Audit-only work ends here; no repair or promotion was started.
