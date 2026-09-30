# Candidate worker: implementation and acceptance boundaries

## What this change actually adds

`python -m scheduler.engineering_executor` retains the existing scheduler CLI,
leases, receipts and eight-attempt ceiling, and supplies its missing REPAIR
handler. Other handlers and Hunter continuation ordering remain unchanged.

For one exact-revision repair recipe, the worker reads the Git snapshot without
changing the checkout; reproduces a specific unittest assertion failure; applies
bounded, hash-bound text replacements; runs the same new regression and the
existing unittest suite; and emits a usable patch, changed files, test logs and a
content-bound build receipt. The candidate worker itself is deterministic. When a
real scheduler REPAIR is selected, the separate governed planner may use one
bounded Tier-2 model call to propose that recipe; deterministic validation binds
the proposal to the admitted target paths and exact source bytes before any test
execution.

Production test execution requires an installed immutable Docker image ID.
Containers have no network, credentials, writable source mount, Docker socket,
privileged capabilities or root UID. Runtime, memory, output and process counts
are bounded. There is no automatic fallback to running candidate code on the
host. An injected runner appears only in trusted unit tests.

## Not an autonomous coding or delivery claim

The first driver is `exact-replacement-v1`, not an LLM programmer. It executes an
approved recipe; it does not discover an arbitrary bug or invent its own approval.
The separate build-task registry is empty in this change. No production work,
downstream onboarding or new spending is authorized by adding these files.

A `CANDIDATE_BUILD_TESTED` result completes the candidate-building stage only.
Every result explicitly records zero delivered improvements, no independent
verification and no production change. The artifacts still need independently authorized review and remote submission.
A separate read-only CI job now replays the exported patch and prepares a local
factory record in VERIFYING, but does not perform remote submission or approve
its own work. Merge, deployment, business actions, payments and
trading remain outside its authority.

Production activation is event-driven rather than embedded in the scheduler.
After a successful main `portfolio-autonomous-scheduler` run, the separate
`repair-candidate-cycle` consumes that exact run's scheduler artifact. If no
queued REPAIR exists, the cycle stops before paid planning. If one exists, it
restores durable cost/plan state, generates or reuses the exact-lineage plan,
builds and independently replays the candidate in isolated containers, submits or
reuses only the isolated candidate branch, then completes only that scheduler
work item. Missing or inconsistent inputs fail closed.

## Evidence

Local tests use a trusted integer-parser fixture and real Python subprocesses.
They cover red/green tests, application of the emitted patch, no-op/wrong fixes,
source/approval drift, baseline infrastructure failures, suite failures, timeouts,
zero-test runs, log limits, immutable tests, path guards and unchanged controls.
The full scheduler integration test requires the complete repository in CI.

The CI pilot uses actual Brain source at
`bb60815ba1ed25c6914752eee03882c6d183e607`: `_path_allowed` accepts a backslash-based
path on Linux. A frozen regression must fail on that source and pass after a
narrow candidate repair. The pilot passes one explicitly injected work item
through the actual scheduler execution/lease/receipt path and Docker test runner.
It is not a live allocation, independent approval, downstream deployment or
commercial outcome. Its exact worker revision, base revision, image ID, run,
attempt, candidate patch and test logs are retained in the CI proof artifact.

Existing paid-model ceilings, project limits, task caps, factory repository
permissions, schedules and kill switches are not raised or removed. Foundation
CI retains all existing validations and gains the candidate proof under its
existing five-minute job bound. Do not merge/deploy this branch or close issue
#65 based on green tests alone.

## Separate-job replay and factory handoff

The `candidate-replay` job consumes the exact artifact ID returned by the build
job, not the newest artifact with a matching name. It checks the current source
revision, run, attempt, frozen task and immutable test image. Artifact-name hashes
are not treated as source identity. The producer also retains a Git source bundle
and task input so the proof is reproducible without a developer's working tree.

`software_factory.candidate_replay` verifies receipt and log contents, applies the
actual exported patch to a fresh Git index, compares every file and mode against
the approved task and pinned source, and reruns baseline, candidate regression
and the entire existing unittest suite in new isolated containers. Existing tests
cannot be removed, altered or skipped to pass. Rehashed but contradictory output
is rejected. The baseline still must reproduce an assertion failure, not an
import/runtime error.

After the fresh tests pass, it creates a real local Git commit and importable
`candidate.bundle`, preserving the exact tested tree and source parent. It calls
the existing factory enqueue/claim/commit-record APIs in an isolated temporary
database, emits the corresponding branch/commit packets and a `factory_work.json`
snapshot in VERIFYING, and proves the factory refuses PR creation without review.
No production ledger is updated and no remote Git executor is invoked.

The separate job is a technical cross-check, not an independently authorized
reviewer: the implementation and workflow are still controlled by this PR. It
must not produce a PASS approval, train a verified outcome, open a production PR,
or enable merge/deployment. Its handoff explicitly records no remote submission,
no independent verification and zero delivered improvements. The prepared v1
GitHub commit packet may create a different provider commit identity; a future
submitter must reread provider parent/tree/head and verify the actual commit before
recording remote success. Local commit evidence must not be relabeled as that
remote receipt.

Both jobs keep read-only permissions and five-minute limits. Production task
registry, repository onboarding, budgets, kill switches and schedules are
unchanged. General model-generated repair and production activation remain
unfinished.

## Governed model planning and remote candidate submission

`software_factory.model_repair_planner` accepts only a scheduler-admitted
`READY_FOR_REPAIR` lineage. Its model request is Tier 2 `DEBUGGING`, public-data
only, capped at $0.08 and 2,500 output tokens, and remains under the existing
portfolio cost governor. The model may propose only exact text replacements
inside the repair task's admitted target paths plus a new deterministic unittest.
It cannot edit existing tests, workflows, policies, secrets or governance files,
and its output grants no review, merge, deployment, or evidence authority.

The repair lineage is stable across reruns. A prior plan for the same exact source,
repair-task hash and base revision is reused without another model call. Provider
failures preserve the updated cost state, so failed parsing or validation cannot
silently erase incurred usage.

`software_factory.candidate_submitter` is idempotent on repository, base revision,
task hash, patch digest, candidate tree and isolated branch. It creates the branch
and candidate commit at most once, rereads provider state, and requires the remote
commit to be exactly one commit ahead of the base with the replayed Git tree and
changed-path set. A rerun reuses that exact remote candidate. Unrelated branch
state, tree drift, changed-path drift, or tampered packets fail closed.

The submit job is the only repair-cycle job with `contents: write`. The scheduler
remains `contents: read` / `actions: read`; it never calls the write-capable
workflow directly. The repair cycle is triggered by a successful
`workflow_run` for `portfolio-autonomous-scheduler` on main and verifies the
triggering repository, branch, conclusion, run ID, artifact and source commit.
No PR is created by this cycle. Independent verification, PR opening, merge and
deployment remain separate gates.
