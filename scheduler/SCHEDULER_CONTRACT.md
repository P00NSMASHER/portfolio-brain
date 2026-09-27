# Autonomous Portfolio Scheduler — Step 19

Step 19 creates a persistent evidence-gated work queue. It chooses work without ChatGPT prompts but does not execute consequential actions.

## Work types

The scheduler can select HUNT, EXPERIMENT, REPAIR, TEST, RESEARCH, INTEGRATION and VERIFICATION. It creates work only when the source subsystem already shows an eligible state and the assigned Step 14 role already permits the goal type and authority.

Selection is not a weighted activity score. It first applies authority/resource/blocker/source-state gates, suppresses duplicates and active leases, then uses explicit gate precedence. Verification/test/repair of existing evidence chains outrank starting new discovery. Within a gate, explicit CONTINUATION work is selected before unrelated NEW_WORK, then the scheduler uses source Pareto layer, source rank and allocation share. Continuation classification cannot widen authority or bypass per-agent/open-queue ceilings.

## Current evidence state

Current evidence may enqueue bounded RESEARCH, HUNT, INTEGRATION, and external-validation preparation work subject to the scheduler's per-agent and per-cycle ceilings. StarBlox and ABVM adult-only external validation is no longer BLOCKED_APPROVAL: those experiments are bounded by the action engine and the adult-only education validation policy. Direct minor contact, child-data collection, production changes, and consequential child-facing changes remain outside the scheduler and action engine.

## Hunter proposal handoff

Quality-gated Hunter proposals are persisted separately from Hunter continuation state and may enter the scheduler only as OBSERVE-class RESEARCH work assigned to the Researcher. Those reviews are explicitly CONTINUATION work because they advance an already-started, quality-gated evidence chain; within the RESEARCH gate they are scheduled before unrelated new Researcher work. Proposal backlog ordering still prefers higher structural rank and then first-seen FIFO among equal-rank proposals. The scheduler never treats discovery as reuse permission. The executor re-reads public repository metadata and the exact immutable revision tree before completing the review, records license metadata only as evidence requiring review, and leaves rights as UNKNOWN/NOT GRANTED. It cannot authorize implementation, deployment, copying, or external action.

## Persistence and duplicate control

Scheduler state is restored from the GitHub Actions artifact portfolio-scheduler-state. QUEUED or ACTIVE fingerprints suppress duplicates. COMPLETE and CANCELLED are terminal dispositions for the same immutable source identity, so both remain suppressed until that source identity changes. A retry therefore requires a materially new source reference and receives a new fingerprint instead of silently recreating unchanged work. If an external lease appears expired, the scheduler does not create overlapping replacement work; the Step 14 agent runtime must reconcile the lease generation first.

## Activation and authority

The workflow runs hourly on the default branch and also supports explicit repository_dispatch/workflow_dispatch invocation. It deliberately does not fan out on ordinary push events inside the singleton cost-state concurrency lane. It has contents: read and actions: read only. The scheduler cannot write repositories, open PRs, send messages, move money, trade, deploy, merge, or grant authority.

The new upstream StarBlox scout workflow was inspected but its direct push-to-main behavior and StarBlox-specific mission are deliberately not inherited into Portfolio Brain scheduling.
