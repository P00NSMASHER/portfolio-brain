# Persistent native intent storage and final-approval adapter

Status: executable storage component and tested adapter; NOT production gate activation.

## Durable behavior

`verification.native_intent_store.IntentStore` keeps a private SQLite database
with explicit creation, a separately configured store identity, rollback-mode
journaling, FULL synchronization, transactional claims, immutable ticket rows,
and an append-only event sequence. One intent is retained per repository/PR,
regardless of later labels or head revisions. It never silently creates a lost
store or substitutes generic CI success for an absent approval.

A caller records PREPARED, commits ATTEMPTED before any native POST, and records
a separately observed result. A second worker or restarted process cannot claim
that intent again. UNKNOWN requires original-provider reconciliation, not retry.
Revocation is sticky. Missing/foreign/tampered state, a different ticket, expiry,
or source/policy drift holds. Database locks serialize competing claims.

The database does NOT grant native mutation authority. Its hash chain detects
corruption, not an administrator who deliberately rehashes or rolls back the
entire store. The store identity must be retained independently, and original
independent GitHub App approval remains mandatory. Production recovery must not
restore a stale checkpoint and thereby erase an already attempted request.

## Final gate integration boundary

`verify_recorded_approval` loads the retained ticket, requires a confirmed
ENROLLED observation, calls the existing exact-PR/head/base/policy/issuer verifier,
and rechecks the ledger afterward. A revocation during provider reads holds.
Its result still has zero provider writes, no check publication, and no merge
authorization. A local ENROLLED assertion cannot forge the separate App check.

The protected publisher `verification/independent_verifier.py` and its workflow
are unchanged. They do NOT yet call this adapter. Installing the independent
admission producer, the trusted persistent service, and the final protected
publisher integration requires the governed control-plane migration; no failed
trust-anchor check may be bypassed. Generic successful regressions are not that
migration approval. There is no new service, scheduled task, or native POST here.

## Private storage on both platforms

POSIX requires current-user ownership, a private parent, private single-link
regular database, and no symbolic links. Windows uses native Win32 owner/DACL
reads, requiring current-user ownership and allowing only that user, SYSTEM,
and Administrators; it rejects other allow ACEs, null ACLs, unknown ACE types,
and junctions. It does not infer Windows security from POSIX mode bits or alter
existing ACLs. Windows API behavior must also be verified on the actual device.
No secrets, private keys, or customer records are needed by this component.

## Tests and provenance

Thirty database tests failed before implementation and passed afterward,
including separate spawned processes, reopen-after-attempt recovery, conflicts,
revocation during reads, source drift, corruption, and no generic-success fallback.
Eight Windows ACL-policy tests likewise failed before implementation and passed.
The Linux run executes all 38 cases. Five POSIX-specific operations are explicitly
skipped on Windows; that platform's native API result is separate evidence.
Provider records in these tests are synthetic, not live enrollment proof.

The final verifier dependency is the unchanged Git blob
`a296fa926f22ae2df7fc1e0da67f8d2a25190321` from PR #730.
This branch incorporates the exact documentation-only current-main canary commit
`36b5a28b69561d1fdbcfeabb501c930b418b8236`; it does not transfer any old source's
six-hour acceptance to that new source. Native write permission was separately
proven by owner-authorized PR #734; this storage work does not repeat that write.

SQLite transaction semantics:
https://www.sqlite.org/lang_transaction.html

## Original Windows device acceptance — October 21, 2026

On connected PAAM-L044 (Windows), the read-only Win32 ACL verifier was loaded
from the exact reviewed Git blob `87f57c31e6c0fd2317a0b5417310b356d80b923d`.
A nonexistent file and a normal temp file with inherited permissions both
failed closed. A newly created synthetic file with an explicitly protected,
current-user-only ACL passed. No pre-existing ACL was changed; disposable
fixtures were removed after the tests.

A separate end-to-end synthetic SQLite intent test loaded, with Git blob
identity independently checked, these *unchanged* candidate modules:

- `verification/native_final_approval.py`: `a296fa926f22ae2df7fc1e0da67f8d2a25190321`
- `verification/native_windows_acl.py`: `87f57c31e6c0fd2317a0b5417310b356d80b923d`
- `verification/native_intent_store.py`: `7bcd9693efc58a5fed6ef61114cfc177e871df4c`

The test created a disposable private Windows directory and SQLite database,
committed PREPARED and ATTEMPTED, recorded UNKNOWN, closed and reopened the
database, proved a repeated claim was denied, reconciled to ENROLLED, then
revoked and reopened to confirm sticky REVOKED. Exactly five events persisted.
The revoked record denied final-gate evaluation without invoking even one
provider read. All test state and temporary scripts were cleaned up.

**Disposition:** `WINDOWS_PRIVATE_INTENT_SQLITE_PASS` using isolated synthetic
inputs, zero GitHub writes, zero private credentials, zero changes to production
ACLs. This proves Windows API and database integration on this device, **not**
deployment of a trusted persistent service, original approval-check issuance,
independent production final-gate integration, or permission to enroll a PR.

## Current-main source separation — October 21, 2026

The draft has been reconciled onto protected `main` at
`37a0b9300a28e2f1fc19481a5351410709664302` while retaining all
existing inert source-bound model fixtures. That source was released through
owner-approved PR #736 with independently issued protected checks, but has
not yet completed the separate six-hour source-specific acceptance.
Earlier accepted `35ad7186...` evidence does not transfer.
No production control-plane source, workflow, issuer or permission is modified.
