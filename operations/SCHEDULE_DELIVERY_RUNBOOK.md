# Scheduled-event delivery recovery

The October 5 22:00-23:00 UTC Step 23 soak on ca2ae77fa0314777bbc8591e3b2507b2effa43b5 is abandoned by its owner. Existing artifacts remain historical evidence, not release acceptance. No next soak start is configured.

## What changes

The eight production workflows keep their reviewed ordinary schedules. Expired October 5 retries are removed rather than recurring annually. The reducer remains active and reads both native and reactive reducer completions; canonical cost restoration before notifications is preserved. Watchdog, reporting and repair no longer suppress ordinary reactive recovery during the retired hour.

The independent `portfolio-schedule-delivery` probe runs at minutes 7,17,27,37,47,57 UTC each hour. It has no canonical-state, model, Hunter, publication, or shared-writer dependency. Scheduled inspection is read-only. Its main-push-only recovery job can request cancellation of the exact retired branch auditor and re-enable only an identity-checked core/probe workflow confirmed disabled. Active registrations are not blindly toggled. A successful enable response is not delivery proof.

After a reviewed main push, recovery calls the existing bounded non-paid workflow-liveness dispatcher. At most the already-policy-authorized number of overdue targets are dispatched; active work is not duplicated. These real `workflow_dispatch` runs restore operations but never satisfy native `event=schedule` acceptance. No financial, deployment, verifier, or paid-model authority is added.

## Evidence and decision

Each probe publishes a transport receipt with the current main SHA, its actual provider event, registration state, latest native run and current-revision run status for every core workflow. Missing events, queued execution, failures/skips and recent native completions are separate states. Green diagnostic CI means the inspection executed, not that transport recovered. `acceptance_complete` is always false and per-workflow `soak_credit` is zero.

A new soak requires reviewed arming only after actual native delivery, successful substantive application work, reducer drain, current-source publication and stable main are demonstrated. A single new probe run establishes only the probe's transport. It does not prove delivery for all eight production workflows. If the probe itself has no native run while push/dispatch runs succeed, preserve its artifacts and registration history as evidence of an unresolved native scheduling issue; do not replace missing evidence with manual runs or move the test clock again.

## Boundaries

The GitHub independent-verifier workflow and verifier implementation are unchanged. Existing serial-write locks, artifact lineage, fail-closed workload controls, and strict acceptance validator are unchanged. The new monitor does not launch a soak, create a PASS receipt, or certify a previously abandoned attempt.
