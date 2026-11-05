# Portfolio Brain: verified capabilities and authorization gap

**Diagnosis from original GitHub Actions and source, November 5, 2026.**

## Existing functional core

- Runs GitHub Actions `brain-cycle-v2` on protected `main`.
- Reads public repository metadata and source-linked candidate references.
- Maintains a verified SQLite state branch with source-bound publication,
  integrity checks, bounded retention, and independent archive replay.
- May create narrowly reviewed Portfolio Brain PRs using existing guarded
  pathways. No independent right to write other project repositories.
- Two separate GitHub Apps verify `validate` and
  `portfolio-phase1-gate` on exact candidate heads. Do not weaken this.

## Not implemented in the existing runner

- A general code-writing agent which can investigate and patch arbitrary
  failures in the other product repositories, submit project-specific
  test-proven PRs, satisfy those repositories' independent review requirements,
  and measure behavior after release.
- Cross-project GitHub write or deployment credentials. The original v8
  runtime receipt explicitly declares `cross_project_code_write:
  NOT_CONFIGURED`, `cross_project_deploy: NOT_CONFIGURED`,
  and `runtime_actions_executed: 0`.
- Business/customer verification from source discovery alone.

Do not describe this architecture as fully autonomous multi-project repair.
The supported product until a separately authorized owner worker exists
is **verified observation and actionable incident detection**.

## Production admission contract added

The original main-branch CLI requires a **verified original failed main run**
with an exact SHA, first-attempt original run, original job and failed step
from the authorized GitHub reader before appending a new repair candidate
into the canonical v9 owner queue. Inconclusive check states, feature-branch
check failures, lack of original read budget, and missing data remain
nonactionable source signals. Previously committed queue events remain
untouched, including earlier diagnosis/evidence and immutable archives.

The historical synthetic/offline `run_cycle` test mode remains a diagnostic
helper. Only the original trusted main-branch workflow context enables
strict admission without changing the SHA-pinned workflow YAML.

## Real acceptance criteria for a future worker

1. Reproduce a concrete user-impacting defect on an exact project revision.
2. Produce a minimal code patch and a red/green test in an independently
   authorized project branch.
3. Verify exact-head CI, protected review, and the actual merged commit.
4. Verify the deployed/runtime outcome against its original provider.
5. Record an immutable artifact with before/after behavior and ownership.
6. Do not credit source observations, synthetic tests, CI green, or a merged
   evidence-only report as live value.

If the authorized cross-project worker is absent, the correct reporting
verdict is **BLOCKED_WORKER_NOT_CONFIGURED** rather than completed.
