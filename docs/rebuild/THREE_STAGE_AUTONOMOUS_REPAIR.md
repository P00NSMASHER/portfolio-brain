# Three-stage autonomous repair — bounded, source verified

These new capabilities are draft-only in Brain PR #687. They extend the
existing project-owner work, not protected V6 production or scheduled tasks.

## 1. Automatic code repair

The isolated repair builder (brain/repair_patch_executor.py) turns an original,
SHA-256-pinned source file into actual modified local code plus a new
failing-before/passing-after regression test. The first supported recipe fixes
untrusted actions/checkout@v4 in read-only pull-request CI, pins its reviewed
immutable source and disables persisted credentials. It also pins one
setup-node@v4 reference when present. Executing the --apply-root option edits
two files in a clean isolated local Git worktree, without committing or pushing.

It refuses changed source hashes, dirty worktrees, unknown users/repos/paths,
privileged workflows, ambiguous checkout options, deploys, scheduled or
manual-trigger workflows, stored secrets, and any source content outside its
reviewed recipe. This is a real but deliberately narrow code-fixing class, not
a general unsupervised arbitrary-code writer.

Command, after creating a private request.json whose source HEAD/file SHA
were read from the authorized original GitHub provider:

    python -m brain.repair_patch_executor --request /private/request.json \
      --source /private/checkout/.github/workflows/factory-ci.yml \
      --apply-root /private/checkout --output /private/patch-result

## 2. Test, independent gate, deliver, then verify source

The separate delivery evaluator (brain/repair_delivery.py) replays the
original source through the deterministic patch recipe, verifies both changed
blobs, authentic original same-repo PR source/head/base, real required source
CI from GitHub Actions App 15368, and independent verifier App 5121826.
A green draft, changed base, conflicting PR, missing reviewer, or failed
test is a HOLD. A clean authorized candidate yields only a SHA-guarded MERGE
REQUEST for an existing guarded owner; this module itself never merges.

After an actual GitHub merge, it requires the original merge commit, exact
current-main readback and a new independent full main-head CI. Passing
source checks is not proof of a live production service.

    python -m brain.repair_delivery \
      --bundle /private/original-github-evidence.json \
      --output /private/delivery-result

## 3. Real-outcome feedback

The repair learner (brain/repair_outcome_learning.py) replays original source
bytes and actual GitHub PR and CI evidence through the delivery validator.
It counts independent main-source technical successes and original failed
CI attempts from closed, unmerged PRs. Drafts and unresolved work are NOT
counted as failures. It rejects duplicate PRs, forged file hashes, wrong
provider app, unsupported customer-value claims and cross-source checks.

At least three distinct resolved source revisions must exist before a
bounded heuristic priority update (-8 to +5) affects only the matching
source-security or automation-reliability recipe. Real financial or buyer
outcomes remain UNKNOWN, never invented from technical CI.

    python -m brain.repair_outcome_learning \
      --episodes /private/original-repair-episodes.json \
      --project-report /private/current-project-report.json \
      --output /private/next-owner-actions

## Operating limits

All output remains source-bound and private. No existing scheduled task,
branch protection, budgets, provider credentials, customer data, financial
controls, website deployment, outbound communication or Roblox publishing
authorization is changed. Portfolio Brain's signed V6 production acceptance
remains frozen and independently governed. Actual customer-value learning
requires separate, consented original outcome evidence; this first learner
covers independently checked TECHNICAL repair results only.

## Completed technical stages and release status (October 15, 2026)

- **Stage 1:** Implemented and regression-tested source-hash-bound
  deterministic workflow repair, plus a verified failing-before/passing-after
  security test. Applies only inside an isolated clean worktree and cannot
  push or merge.
- **Stage 2:** Original PR, exact source, mandatory job and independently
  installed verifier identities, branch mergeability and post-merge main checks
  are assessed separately. GitHub's current PR base pointer may advance after
  a successful merge, so a genuinely closed+merged candidate is verified using
  the actual merge commit/main-head evidence instead of incorrectly requiring
  the original base pointer to stay unchanged. Open stale-base PRs still HOLD.
- **Stage 3:** Repeatable technical results feed only a bounded, matching
  repair recipe priority after at least three distinct source-verified
  examples. Pending drafts are not failures, and business outcomes cannot be
  inferred. No qualifying real buyer/revenue evidence has been collected.

These three implementation stages have a green hosted Foundation and separate
Brain independent check on the draft source, not a production cutover.
Protected Brain main remains fixed while V6 six-hour signed acceptance is
pending. RETALLY and App Factory also need actual source-specific
independent approval; Brain's own reviewer App check does not magically
establish downstream acceptance. Do not mark the outcome-learning stage
as live-calibrated until real original cases, not synthetic fixtures, exist.
