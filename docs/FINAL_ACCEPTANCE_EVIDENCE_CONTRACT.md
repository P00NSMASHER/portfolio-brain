# Final acceptance evidence contract — Steps 21–25

This contract is preparation only. Its presence or a passing unit test does **not**
complete any final acceptance step.

It exists to prevent optimistic dashboards or one-off green runs from being
reinterpreted as proof later.

## Step 21 — full live acceptance canary

A PASS receipt must bind the ordered chain:

`discovery/hunt -> proposal -> scheduler work -> implementation candidate -> tests
-> independent verifier -> protected promotion -> verified outcome
-> feedback/learning -> next scheduling cycle`.

Every stage carries machine-readable run/PR/check/artifact/state/SHA evidence
plus an ordered timestamp. Candidate PR/head identity must remain continuous
through tests and App **5121826**, and the protected promotion SHA must equal the
receipt's exact-main SHA. The receipt must also bind the exact candidate head to
Foundation `validate` from App **15368** and `portfolio-phase1-gate` from App
**5121826**; a free-standing App ID claim is not accepted. The fixture must be
harmless and authority-bounded.

## Step 22 — autonomous self-repair

The receipt requires a controlled reproducible fixture, no damage to production
main, isolated `factory/auto-repair-` implementation, a **new regression**, full
suite PASS, repair PR, exact-head Foundation check, hosted App 5121826 gate,
protected merge, and healthy subsequent runtime/reducer/scheduler cycles.

Any human or laptop verifier dependency fails closed. The repair PR must be
bot-created, Foundation `validate` must be App **15368**, the independent
`portfolio-phase1-gate` must be App **5121826**, both must bind to the same
exact repair head, and the subsequent runtime/reducer/scheduler proofs must be
bound to the protected repair merge.

## Step 23 — sustained production soak

The acceptance window requires at least three successful **scheduled** cycles for
each required workflow. Cancelled/coalesced runs may appear only when explicitly
classified and are not counted as successful cycles or failures. Any actual
failure in the claimed soak window fails acceptance.

Canonical sequence samples must never regress and each sample must bind to a
distinct successful reducer cycle. Cancelled/coalesced runs require an evidenced
superseding run, pending events must drain to zero, REPAIR/TEST/VERIFICATION must
each execute, Hunter must do substantive work, and the command center must remain
fresh and hash-traceable.

## Step 24 — independent least-privilege/security review

All twelve required security control areas must have fresh PASS evidence. The
reviewer and implementation independence groups must be distinct. Critical
findings must be resolved, not merely risk-accepted.

## Step 25 — cleanup

Cleanup cannot start from this contract until Steps 21–24 are COMPLETE.
Canonical checkpoint/archive history and historical evidence are protected from
removal. Superseded-PR reconciliation and dead-path removal require regression
coverage evidence.

The validators live in `acceptance/final_acceptance.py`; regression coverage is
in `tests/test_final_acceptance_contract.py`.
