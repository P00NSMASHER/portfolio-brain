# Continuous Repair / Self-Improvement — Step 17

Step 17 connects failure evidence to bounded repair without allowing self-certification or automatic promotion.

## Lifecycle

`learning alert -> NEEDS_REPRODUCTION`

or, only for an immutable reproducible verified failure packet:

`VERIFIED failure + reproduction steps + evidence + required regression test -> READY_FOR_REPAIR -> Step 16 isolated factory -> independently verified PR_OPEN candidate -> HELD_OUT_PENDING -> independent held-out PASS -> INDEPENDENT_AUDIT_PENDING -> separate auditor PASS -> CANARY_PENDING -> zero-regression / zero-authority-violation canary PASS -> PROMOTION_ELIGIBLE`

`PROMOTION_ELIGIBLE` is **not promotion**. It records:

- automatic promotion: false;
- required approval: INTEGRATOR_APPROVAL;
- promotion action: null.

There is no merge/deploy/promote operation in the Step 17 engine.

## Failure gating

A statistical overfit/regression alert is not a repair authorization. It may create only a reproduction task. A mutation-ready repair requires a FAILURE_PACKET whose evidence state is VERIFIED and which already contains reproduction steps, evidence references, and a concrete regression-test requirement.

Failures involving sensitive material or benchmark contamination are blocked.

Step 17 repairs only Portfolio Brain (`REPO-008`) in v1 and refuses protected governance/workflow/provider/build-state targets. Downstream repositories remain outside automated repair authority.

## Isolated implementation

Repair implementation is delegated to the Step 16 factory. The candidate must reach `PR_OPEN`, meaning:

- Engineer built on an isolated candidate branch;
- regression evidence was attached;
- exact commit/diff identity was recorded;
- the factory-bound independent verifier passed the candidate;
- no merge occurred.

## Independent evaluation chain

Held-out evaluator must not be the builder. Independent audit must be performed by Auditor or Red Team and must differ from both builder and held-out evaluator. All evaluation packets bind the exact candidate commit and diff hash.

The canary must execute at least one check and must show:

- PASS;
- all checks passed;
- zero regressions;
- zero authority violations.

Any FAIL/UNKNOWN/regression/authority violation blocks the repair rather than averaging it away.

## Production seed and runtime

The checked-in repair ledger starts empty. Step 10's empty learning ledger currently produces no learning alerts, so Step 17 creates no fabricated repair tasks.

Step 8 daily mode emits `repair_state.json` from current verified failure packets plus reproduction-only learning alerts. It detects repair work continuously but does not execute, canary or promote repairs by itself.
