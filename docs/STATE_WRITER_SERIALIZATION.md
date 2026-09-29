# Step 1: temporary shared-state writer serialization

Every job publishing a canonical continuation snapshot holds the repository-wide
`portfolio-state-writer-v1` concurrency group for its entire restore, mutation,
and upload transaction. The group has no branch, event, workflow, or mode suffix.

Existing per-service entry groups and the paid cost group remain in place, with
`cancel-in-progress: false` and `queue: max`. Writer jobs acquire the shared mutex
after their entry group; no caller holds that mutex while invoking a reusable
writer workflow. Runtime callers cannot cancel an active child writer.

Eleven publisher workflows are covered, including bootstrap, operator, factory,
notification, and command-center history writers, not just Hunter and Runtime.
The emergency-stop operation uses separate run-scoped entry/job groups and cannot
publish scheduler state; it must not wait behind a writer it needs to cancel.
The independent watchdog only reads cost state and publishes a liveness receipt,
so it remains outside the writer mutex. CI and isolated proof artifacts do too.

GitHub's `queue: max` permits up to 100 waiting runs/jobs per group, not an unlimited
queue. Queue overflow, explicit cancellation, kill switches, and timeouts are not
disabled. Budgets, workload admission, permissions, and artifact validation are
unchanged. See GitHub's workflow-syntax concurrency documentation.

This change prevents new concurrent-writer forks; it does not reconcile existing
conflicting artifacts. Do not choose by upload time, delete a fork, reset a seed,
or relabel a conflicting state as valid. Drain legacy writer runs before protected
activation, then separately verify the exact deployed revision and durable state.
Step 2's event/reducer migration and Steps 3-8 are not implemented here.
