# Read-only pending draft reconciliation

This increment observes whether GitHub contains exactly the intended draft change.
It never creates a branch/PR, executes target source, confirms a journal intent,
releases a claim, retries a write, merges, deploys, or promotes capability maturity.

## Interfaces

`observe_draft(intent, token=..., now=...)` performs direct authenticated GETs using
the fixed-host v9 observer transport. The intent contains exactly schema_version1,
repository, base_sha, head_sha, pull_number, expected_files (path to Git blob SHA),
and actor_login. Those intended values must come from original authorized work;
matching a supplied intent does not prove its authorization or test correctness.

The observer validates repository-specific pull permission, current default branch,
open same-repository draft identity/author, actual candidate branch ref, a direct
single-parent candidate commit, exact changed-file set, nontruncated regular-file
Git tree entries and actual content blob hashes. It rechecks PR, candidate ref,
default ref and permissions after reading files. A renamed/deleted/extra file,
source or branch drift, unexpected actor, symlink/submodule, missing response or
provider error stops observation. Missing data never means no write occurred.

`review_pending_draft(mission, readonly_journal, intent, token=..., now=...)` binds
that observation to one existing mission work fingerprint, original source,
repository resource, pending operation and matching claim. It checks original
journal ancestry through replay, file identity and unchanged chain tip around
provider observation. Existing SQLite transactions are refused defensively.
The read-only journal is never mutated; expiration does not confer retry authority.
Concurrent appends or replacement of the journal path invalidate the readback.

`python -m brain.v9 review-pending --mission mission.json --journal /private/kernel.sqlite --intent intent.json`

Uses an already authorized `V9_GITHUB_READ_TOKEN`; missing credentials return
BLOCKED without journal mutation. No token is printed, persisted or passed on the
command line. No runtime credential or additional permission is provisioned here.
Actual ChatGPT connector permissions do not establish unattended runtime access.

## Evidence and limits

Tests use explicitly labeled injected transport and real private SQLite journals.
They cover exact readback, extra or renamed changes, wrong actor/repository/source,
PR closure/merge, branch drift, revoked permission, invalid tree/blob, unknown
provider result, changed intent, concurrent append, replaced journal inode,
preexisting transaction, missing credential and preservation of pending state.
Tests do not establish authenticated runtime execution or a real delivered repair.
Original hosted test evidence and exact candidate revisions are retained on the PR.

Up to16 files and27 GETs, each response at most1MiB; cooperative15-second response
and60-second observation budgets inherited from the observer. These are not hard
OS DNS/process deadlines. Large or truncated recursive trees block. Sequential
reads are point-in-time observations, not an atomic provider snapshot or fencing
lock. Same-user hostile file replacement after the final check is not prevented.
No credential-independent signature, trusted external admission or release proof
is manufactured from these receipts.

## Recovery and next boundary

Keep original journal/claim on every failure. Correct source/input or obtain fresh
original provider evidence before any separately authorized reconciliation. Never
clear uncertainty by deleting history, waiting for a lease to expire, or blindly
repeating provider writes. A future write adapter must enforce independent admission
and transactional ownership, then use authenticated original provider readback.

Production remains e29ec867 while its own source-specific acceptance runs. This
increment stays isolated and must pass exact-source independent checks before any
later protected adoption. No scheduled workflow, Cron, credential or policy changes.
