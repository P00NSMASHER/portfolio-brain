# Candidate worker: implementation and acceptance boundaries

## What this change actually adds

`python -m scheduler.engineering_executor` retains the existing scheduler CLI,
leases, receipts and eight-attempt ceiling, and supplies its missing REPAIR
handler. Other handlers and Hunter continuation ordering remain unchanged.

For one separately approved, exact-revision repair recipe, the worker reads the
Git snapshot without changing the checkout; reproduces a specific unittest
assertion failure; applies bounded, hash-bound text replacements; runs the same
new regression and the existing unittest suite; and emits a usable patch, changed
files, test logs and a content-bound build receipt. No model call is involved.

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
verification and no production change. The artifacts still need an independent
verifier and the existing factory submission/PR path. Those transitions are not
implemented by this slice. Merge, deployment, business actions, payments and
trading remain outside its authority.

Production activation also requires a reviewed exact task, a pinned checked-out
repository and an installed image made available to the runtime. The scheduled
job currently has no approved task/image provisioning. Missing inputs produce a
specific deferred result, not a fabricated success. This PR must not be presented
as a running end-to-end product factory.

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
