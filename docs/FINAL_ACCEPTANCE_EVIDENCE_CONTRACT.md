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
receipt's exact-main SHA. Foundation must be check `validate` from App **15368**
and the independent gate must be `portfolio-phase1-gate` from App **5121826**,
both on the exact candidate head. The fixture must be harmless and authority-bounded.

## Step 22 — autonomous self-repair

The receipt requires a controlled reproducible fixture, no damage to production
main, isolated `factory/auto-repair-` implementation, a **new regression**, full
suite PASS, repair PR, exact-head Foundation check, hosted App 5121826 gate,
protected merge, and healthy subsequent runtime/reducer/scheduler cycles.

Any human or laptop verifier dependency fails closed. The repair PR must be
bot-created by `github-actions[bot]`. Foundation `validate`/App 15368 and
`portfolio-phase1-gate`/App 5121826 must be bound to the same exact repair head,
and the subsequent runtime/reducer/scheduler proofs must be bound to the protected
repair merge.

## Step 23 — sustained production soak

The acceptance window requires at least three successful **scheduled** cycles for
each required workflow. Cancelled/coalesced runs may appear only when explicitly
classified and are not counted as successful cycles or failures. Any actual
failure in the claimed soak window fails acceptance.

Canonical sequence samples must never regress and each sample must bind to a
distinct successful reducer cycle. Cancelled/coalesced runs require an evidenced
superseding run and pending events must drain to zero. REPAIR/TEST/VERIFICATION
execution claims must each bind an execution ID and artifact hash to an actual
successful scheduler run on the exact soak main; aggregate counters alone are
insufficient. Hunter substantive-work claims likewise must bind a non-heartbeat
work ID and artifact hash to an actual successful Hunter cycle on that exact main.
The command center must remain fresh and hash-traceable.

## Step 24 — independent least-privilege/security review

All twelve required security control areas must have fresh PASS evidence. The
reviewer and implementation independence groups must be distinct. Critical
findings must be resolved, not merely risk-accepted. The Step 24 receipt embeds
the complete hashed security-review report; the validator recomputes that report
hash, requires live evidence, requires zero CRITICAL/HIGH/UNKNOWN blockers, and
binds both expected and observed review SHAs to the receipt's exact protected
main. Artifact tamper-resistance proof must bind exact run/head/artifact identity,
prove the artifact is unexpired, and match the provider-reported SHA-256 to an
independently recomputed downloaded ZIP SHA-256; a syntactically valid digest
string is not evidence by itself.

## Step 25 — cleanup

Cleanup cannot start from this contract until Steps 21–24 are COMPLETE.
Canonical checkpoint/archive history and historical evidence are protected from
removal. Superseded-PR reconciliation and dead-path removal require a protected
cleanup PR whose merge SHA becomes exact main, with exact-head Foundation
`validate`/App 15368 and hosted `portfolio-phase1-gate`/App 5121826 checks
recorded as the regression coverage evidence.

The validators live in `acceptance/final_acceptance.py`; regression coverage is
in `tests/test_final_acceptance_contract.py`.
