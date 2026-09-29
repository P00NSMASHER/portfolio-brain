# Step 2 — immutable events and single-reducer migration

## Actual status

This candidate advances the event/reducer work to a **live shadow parity**
stage, not the production cutover. Step 1 remains the active production
serialization design. Legacy publishers/readers still carry production authority;
budgets, schedules, permissions, kill switches and external-action boundaries are
unchanged.

Shadow event capture is now always instrumented on admitted state-producing runs.
A reviewed `CHECKPOINT.json.gz` is generated from all eleven legacy domains by
their existing production restore/validation modules. The checkpoint is source
bound and its artifact scan boundary is explicit. The sole reducer must replay all
new events and then prove all eleven projected domain hashes equal the still-live
legacy state while holding `portfolio-state-writer-v1`; otherwise it publishes no
shadow snapshot.

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

Completed in this candidate:
- A source-bound checkpoint for all eleven state domains is generated through the
  existing production restore/validation code. The scan boundary is bound to that
  checkpoint, and checkpoint integrity is covered by regression tests.
- A mandatory legacy-parity gate blocks shadow publication when even one domain
  differs. The shadow reducer remains the only shadow snapshot publisher.

Still required:
- Merge this exact candidate through protected CI/verifier gates and exercise real
  producer → immutable-event → reducer → restore parity on main. The one-shot
  smoke workflow dispatches the existing Hunter, Scheduler, Runtime and heartbeat
  workflow_dispatch entrypoints sequentially; it does not add forbidden push
  fan-out to Scheduler or heartbeat.
- Exercise retries, partial/interrupted publication and restoration in the live
  stream. A failed producer may preserve a domain it really published, but cannot
  claim successful business work.
- The reusable software-factory workflow has no observed recent live runs; its
  unknown caller therefore remains fail-closed rather than receiving invented
  authority. Enroll a real caller only when one exists and can be provider-bound.
- Finish lossless archival/checkpoint rotation before the finite event/byte/API
  bounds can be reached; evidence must never be silently pruned.
- Switch readers and publishers together with a stale-state barrier, preserve paid
  reservation semantics, prove the replacement Hunter→Scheduler→Runtime loop, and
  only then retire legacy state publication without deleting its evidence.

Steps 3–8 have not been started. Technical replay provides no market or revenue
credit. This checkpoint does not claim the complete Portfolio Brain is functional.
