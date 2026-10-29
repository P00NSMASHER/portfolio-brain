# Engine red-team hardening

## Native enrollment held under current governance

The create-once marker design integrated by PR #750 is NOT an authorized
production mutation. The deny-by-default `governance/boundaries.json` grants
Portfolio Brain candidate PR writes under `factory/` and `auto-repair/`,
but contains no authorization for `refs/heads/brain-native-intent/`.

Until an independently reviewed authorization or an independently verified
already-authorized durable replay barrier is established, the production
GitHub adapter refuses marker creation **before network I/O** and its HTTP
allowlist rejects all git-ref POSTs. Native auto-merge enrollment consequently
fails closed, reporting a blocked candidate rather than an uncertain write.
No permission, protected-branch rule, credential, or deployment authority is
broadened. No old marker is deleted or retried.

Network-free `FakeProvider` unit tests of proposed create-once semantics
remain algorithm-only simulations; they do not establish approval for use or
prove a production native enrollment. This hold must not be lifted without
fresh exact-head Foundation, App 5121826 and independent adverse-case review.
GitHub's required checks and source-specific six-hour production acceptance
remain separate requirements.

## Acceptance receipt provenance

Self-declared PASS fields and one-child ancestry are insufficient. The independent
verifier App 5121826 must issue a distinct `portfolio-source-acceptance` successful
check on the exact receipt commit, with external ID:

`source-acceptance:<full-source-sha>:<sha256-of-raw-receipt-bytes>`

This attestation is separate from `portfolio-phase1-gate`, which validates CI and
does not attest a production soak. The producer must verify the original automatic
run census, first-attempt success, six-hour span, maximum gaps, source and state
lineage, original retained artifacts and terminal SQLite/report replay before
issuing it. A writer cannot substitute a different source, receipt, issuer or CI
check. Existing unsigned receipts remain held. No attestation is manufactured by
the controller or by these synthetic tests. The independent producer's issuance
and fresh acceptance remain release gates; this change does not provision tokens
or activate a new verifier workflow.

## Blocked work is visible

Any denied selected candidate produces `CANDIDATES_BLOCKED` and exit 2. An uncertain
write keeps its distinct reconciliation status and exit 2. No candidates remains a
successful observation, not a claim of completed repair or released production.

## Queue lifecycle and storage

At the 256-item active bound, a newer observation may retire only untouched
OBSERVED entries of the same project, repository, path and fingerprint from older
sources. Claimed entries (including expired leases), progressed work, evidence,
effects and pending/unknown operations are retained. Distinct unresolved work
cannot be silently evicted to make room.

Rotation preserves every original event in compressed, hashed archive segments
inside the same SQLite state image. It does not remove canonical core events or
require a second external artifact. Replay validates sequence, chain, timestamps,
archive hashes and retirement safety; normal snapshot, backup and restore include
the archives. Archive insertion and active-log rotation share the same IMMEDIATE
transaction as admission. A rejected new observation rolls rotation back.

Storage remains bounded: 64 archive segments, 16 MiB total decompressed archive
history, 4 MiB active history and 256 active items. Metrics expose archive raw
bytes and warn at 75% active-item, segment or decompressed-history capacity.
Truly full unresolved work or archive capacity requires
reconciliation; it cannot grant retries, discard evidence or increase spending.

## Validation

`tests/test_brain_v9_red_team.py` reproduces the original failures and tests lost
responses, process recreation, issuer/source/receipt substitution, source churn,
restart/restore, unknown-effect retention, clock reversal and archive corruption.
All provider mutations in that suite are synthetic and network-free.
