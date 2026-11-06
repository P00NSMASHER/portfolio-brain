# Phase 1: authenticated owner inbox (November 6, 2026)

## Live scope

The existing GitHub brain-cycle-v2 is the only writer of the bounded
brain-state-v2 event-sourced SQLite image. Its original-main incident
admission is performed by brain.v9.batch_cycle; it samples original provider
jobs and requires a failed original protected-main job, not aggregate checks
on a commit. Do not bypass these controls.

The additive brain.v11.owner_inbox stage runs in the EXISTING
post-core results job and reads the immutable v9 result downloaded from the
same original completed core. It emits a content-addressed, restart-stable
owner handoff artifact with original repository, run ID, job ID, failing step,
work ID, state checkpoint, and an exact source revision. It uses zero external
requests, no tokens, no model calls, no GitHub writes and no new scheduler.
It never changes a work item's stage or asserts production acceptance.

The previously accumulated OBSERVED count is not evidence of actionable
defects. Only the narrowly verified current owner_jobs enter the owner
inbox, and even these require rereading the original source/job logs before
diagnosis and reproducing an original failing test before patching.

## Execution boundary

- The existing GitHub | Brain & PR Finisher Chat scheduled owner is the
  only code owner for Portfolio Brain. Separate product owners retain their
  repositories. The owner inbox is a source-pinned input to these owners,
  not an impersonated independent review or a second code owner.
- The existing V10 reviewed recipe factory may patch eligible Brain-only
  source under SHA locking, red/green isolated tests, and scoped draft PRs.
  The independent GitHub check issuers and branch protection still govern
  promotion. An eligible failure is not proof that an approved recipe exists.
- General cross-project code writing and deployment remain
  BLOCKED_WORKER_NOT_CONFIGURED. Do not infer those permissions from the
  GitHub Actions workflow's success or the presence of a task prompt.
- A failed production canary can be an intended protective rejection. The
  original PermitPlate scoring-readiness failure on 2026-11-05 reported
  CURRENT_CATEGORY_PARITY_FAIL and CURRENT_BEST_FIT_PARITY_FAIL.
  Reproduce and investigate parity instead of weakening its guardrails.
- Workers may not send outreach, buy anything, trade, force-push, alter
  protected-main rules, submit unapproved external disclosures, or deploy
  downstream code without repository-specific authorization.

## Per-item lifecycle acceptance

1. OBSERVED: original main run, original job and failed step verified
   from GitHub; no code authority.
2. DIAGNOSED: an original user-impacting defect reproduced with a precise
   path, expected-versus-actual behavior, and negative controls; intentional
   gating remains a hold rather than a patch target.
3. PATCHED: source-bound minimal candidate patch on an isolated branch
   with nonprivileged original-source reproduction.
4. TESTED: actual RED-before / GREEN-after plus independent exact-head
   checks and negative controls; a successful CI run alone is not a release.
5. DELIVERED: protected merge verified from original GitHub provider
   data. Deployment/production impact remains unknown until independently
   read back.
6. LIVE VERIFIED: original runtime/readback proves intended behavior
   after merge/deployment, with before/after evidence saved and checked.

Failures to obtain evidence or credentials produce a specific BLOCKED state
without changing earlier evidence or fabricating successful repairs.

## Exit criteria (not yet met)

A new, genuine, independently reproduced defect traverses the entire
pipeline to an independently verified deployed repair without manual coding,
and the owner task recovers the same work after one interrupted run. Until
those observations exist, Phase 1 is implemented only in part. This document
and a green test suite are NOT evidence that a general executor is configured.
