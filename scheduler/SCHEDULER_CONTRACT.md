# Autonomous Portfolio Scheduler — Step 19

Step 19 creates a persistent evidence-gated work queue. It chooses work without ChatGPT prompts but does not execute consequential actions.

## Work types

The scheduler can select HUNT, EXPERIMENT, REPAIR, TEST, RESEARCH, INTEGRATION and VERIFICATION. It creates work only when the source subsystem already shows an eligible state and the assigned Step 14 role already permits the goal type and authority.

Selection is not a weighted activity score. It first applies authority/resource/blocker/source-state gates, suppresses duplicates and active leases, then uses explicit gate precedence. Verification/test/repair of existing evidence chains outrank starting new discovery. Within a gate it uses the source Pareto layer, source rank and allocation share.

## Current evidence state

Current evidence enqueues three work packets only: one RESEARCH item, one HUNT item and one read-only INTEGRATION assessment. The six external-validation experiments remain BLOCKED_APPROVAL because they require customer communication approval. There is no current evidence-backed REPAIR, TEST, VERIFICATION or isolated EXPERIMENT job, so none is fabricated.

## Persistence and duplicate control

Scheduler state is restored from the GitHub Actions artifact portfolio-scheduler-state. QUEUED or ACTIVE fingerprints suppress duplicates. Completed fingerprints remain suppressed until the immutable source identity changes. If an external lease appears expired, the scheduler does not create overlapping replacement work; the Step 14 agent runtime must reconcile the lease generation first.

## Activation and authority

The staged workflow runs hourly when promoted to the default branch, plus repository_dispatch/workflow_dispatch. It has contents: read and actions: read only. The scheduler cannot write repositories, open PRs, send messages, move money, trade, deploy, merge, or grant authority.

The new upstream StarBlox scout workflow was inspected but its direct push-to-main behavior and StarBlox-specific mission are deliberately not inherited into Portfolio Brain scheduling.
