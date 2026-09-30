# Step 6 — recovery independent of canonical restore

Acceptance evidence for remediation tracker Step 6 / GAP-005.

## Production implementation

The watchdog runs `operations.workflow_liveness --without-cost-state` before attempting canonical cost-state restore. The pre-restore lane can dispatch only governed non-paid WORKLOAD targets, grants no authority, and emits a separate liveness receipt. The watchdog itself is not an enrolled state-journal producer and contains no immutable-event emitter/upload step.

## Live outage evidence

During the canonical-state outage, watchdog run `36697382312` executed on main SHA `97c01463696f24c3a3971fd332aa2b5922a900b3`.

Its pre-restore step completed successfully before the canonical restore step was cancelled:

- pre-restore evidence artifact: `11088600834`
- artifact digest: `sha256:2478fd42da680210c670495a1d559eeb74a51e0f59a2a2b1185f65c25802c486`
- receipt status: `RECOVERY_DISPATCHED`
- `hard_stop_reason`: `COST_STATE_UNAVAILABLE`
- `cost_state_proof`: `null`
- `authority_granted`: `false`
- dispatched scheduler from prior failed run `36680482876`
- dispatched heartbeat from prior failed run `36691869857`

Those dispatches created real workflow-dispatch runs:

- scheduler run `36697406585`
- heartbeat run `36697409433`

Both target workflows passed their independent workload-control step, then were unable to restore canonical state during the outage. Their immutable-event capture reported `emitted: false`; the upload-event step was skipped and neither run produced a state-event artifact. Therefore the recovery path did not manufacture a domain mutation when canonical state was unavailable.

## Regression guarantee

`tests/test_workflow_liveness.py::test_controlled_canonical_outage_recovers_without_journal_mutation_authority` simulates unavailable canonical cost state, requires a bounded recovery dispatch with `authority_granted == false`, verifies the watchdog remains outside `WORKFLOW_PRODUCERS`, verifies it contains no state-journal emitter/upload path, and verifies pre-restore recovery remains ordered before canonical restore.

This closes the audit's recovery-dependency gap without weakening journal admissibility.
