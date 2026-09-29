# Step 2 — immutable events and single-reducer migration

## Actual status

This candidate implements the event/reducer **shadow pilot**, not the completed
production migration. Step 1 remains the active serialization design. No existing
state publisher or reader is removed; no production authority, budget, scheduling
cadence, customer action, rights setting, or repository variable is changed.

The new path is gated by `PORTFOLIO_STATE_JOURNAL_ENABLED`. This PR does not enable
that variable. It does not include an invented `CHECKPOINT.json`. Initialization
requires a separately reviewed explicit checkpoint and an owner workflow dispatch.
The reducer refuses to initialize automatically when canonical state is absent.

## Implemented path

1. Eleven current producer workflows retain their normal persistence and record
   each real state-upload outcome under a stable step ID.
2. The emitter captures only domains whose upload step actually succeeded. It
   records validated before/after states, their hashes, and the exact original
   runtime companion receipt. Failed workflows can preserve already-finalized
   state without being called successful business work.
3. Each event ID binds repository, GitHub `run_id`, event type, and source SHA.
   Attempt numbers identify delivery artifacts, not separate business events.
   Same identity with different content is a collision, not a new success.
4. One `portfolio-state-reducer` workflow validates artifact digests, source run,
   main branch, repository, workflow path, attempt, job, and actual publication
   step results. It holds the Step 1 global mutex during the shadow transaction.
5. Only that workflow publishes `portfolio-canonical-shadow-state`. The complete
   checkpoint, unchanged events, provider evidence, and replayed projection are
   retained together. Canonical sequence is allocated by the reducer, not emitters.

The pure replay API accepts explicitly labeled fixtures for testing; those do not
constitute source authorization. The GitHub ingestion path only constructs
provider evidence after the independent API records and artifact bytes agree.
A source hash is an integrity identifier, not independent verification by itself.

## Conflict and delivery semantics

Identical event deliveries are idempotent. Reversed delivery order is resolved by
predecessor hashes rather than upload timestamps. Multiple domain changes in one
event are atomic. Missing predecessors, namespace violations, malformed receipts,
and competing noncommutative updates block publication; prior output remains.

Heartbeat batches are the one explicit commuting operation: the original before
and after states must first be reproduced exactly by the existing production
heartbeat function. Replay then preserves both batches from concurrent writers.
Ambiguous same-agent/same-time updates are rejected, not arbitrarily ordered.
Runtime forks remain blocked; this candidate does not invent a generalized merge
of learning state, reservations, queues, or cursor histories.

## Validation evidence and its limits

The regression suite exercises real runtime state advancement and native heartbeat
mutation, not marker strings alone. `state_journal.prove_archived` pins five real
production archives from merge `87a8ed87`, checks their ZIP SHA-256 digests, and
reconstructs runtime 125→126 and heartbeat 134→135→136. The final states must equal
the original saved states in both event-delivery orders; duplicate delivery must
have no effect. These reconstructed events are labeled fixture/replay evidence.
This is **archived production-state replay**, not a claim the old jobs emitted
new-format events, nor a live v2 cutover certificate.

Run locally:

```sh
python -m unittest discover -s tests -p 'test_state_journal*.py' -v
python -m unittest discover -s tests -p 'test_*.py' -v
python -m state_journal.prove_archived --fetch \
  --archive-dir /tmp/step2-archives --output /tmp/step2-archived-replay.json
```

The archived proof requires a read-only Actions token in `GITHUB_TOKEN` and fails
if the pinned source archives expire. It does not substitute different data.

## Required before Step 2 can be called complete

- Capture a consistent, source-bound checkpoint for all eleven state domains.
  Bind initialization and the artifact scan boundary to that checkpoint.
- Run the new emitters and reducer on real production deliveries; verify full
  projection parity, retries, interrupted/partial publication, and restoration.
- Enroll the actual caller of the reusable software-factory workflow. Unknown
  caller paths are intentionally denied, not inferred from an artifact name.
- Implement lossless journal archival/checkpoint rotation and a proved bounded
  snapshot-selection window. The pilot currently blocks at 16 MiB, 2,000 retained
  events, 20 artifact pages, 20 candidate snapshots, or its 100-request read budget.
  It never prunes unseen events or makes up a fresh seed to stay green.
- Switch readers and publishers together. Preserve durable paid reservations and
  prevent a producer from acting on stale state while a previous event awaits
  reduction. Do not remove the global mutex or legacy path before that barrier is
  proven. Recovery after a paid worker interruption must remain conservative.
- Verify the integrated exact revision and a live Hunter→Scheduler→Runtime cycle
  after the cutover, then retire legacy writers without deleting their evidence.

Steps 3–8 have not been started. Technical replay provides no market or revenue
credit. This checkpoint does not claim the complete Portfolio Brain is functional.
