# Step 7 — Canonical Checkpoint / Archive Lifecycle Evidence

Status: **COMPLETE**

Acceptance date: **2026-09-30**

Tracker: GitHub issue #210, Step 7 / GAP-001.

## Purpose

Step 7 makes canonical journal recovery independent of indefinite GitHub Actions artifact retention. Expired producer/reducer artifacts that are already covered by a validated repository checkpoint are routine history, while uncovered or ambiguous evidence remains fail-closed.

No acceptance in this document depends on ChatGPT, a laptop, PAAM-L044, local Git, or the local verifier. Protected integration used Foundation CI plus the hosted independent verifier (GitHub App 5121826), and live acceptance used GitHub-hosted workflows/artifacts on protected main.

## Durable implementation

The protected implementation chain includes:

- PR #248, merged as `180a5ab9ba8b6ddc1acf74198401a83d140032b3`: repository-persisted canonical archives, immutable manifests, compact checkpoint rollover, archived-event/provider de-duplication, production-reader overlap handling, recurring reducer refresh, and protected checkpoint-candidate generation.
- PR #250, merged as `fc1b978ab7596a6b7ec0fb3e633573dc35f8ef4c`: fail-closed sanitization for public archive/checkpoint bytes.
- PR #255, merged as `a0c08aef0c30de17fdfba8bbb4d23dd78696c411`: first protected archive candidate, canonical sequence 32.
- PR #267, merged as `c025793ecde06e4f057f98cdd7d0db8ccbae3006`: immutable checkpoint identity, predecessor lineage, freshness, explicit six-hour replay overlap, exact checkpoint+replay reconstruction, and distinct fail-closed recovery classifications.
- PR #281, merged as `511596f0c419df5147594e4f26d4e67fdca07cb6`: bounded same-run artifact fallback plus lossless heartbeat-fork recovery.
- PR #294, merged as `1b1956aeeece4f867f88cb4e29e290d7efd3af10`: lossless command-center history fork replay without arbitrary winners.
- PR #297, merged as `1677693941a1c1da9e1a6fcef0c34847b0fa895d`: retain in-flight producers that cross the reducer overlap boundary without increasing request/page limits.
- PR #300, merged as `4fc583fb57cf5769d0fc3c68e3ccc9acf6d3ba16`: allow later native events to continue from validated losslessly merged canonical predecessors.
- PR #302, exact head `9e925de12c7e99665d95f3996daa2d3afaac3d1f`, merged as `2bcb90aee8f8a66ac8b0be95a6dbcea2aa2733ec`: final protected production-reader continuation proof. Foundation check `110012621336` and hosted App 5121826 check `110013754064` both passed.

The acceptance commit `2bcb90aee8f8a66ac8b0be95a6dbcea2aa2733ec` was still an ancestor of main `1d9e880702a3a04742da270b7072a49a0688e2a1` when this evidence file was prepared. The five intervening commits contained no changes under `state_journal/**` or `tests/test_state_journal*`.

## Checkpoint and lineage contract

`state_journal/archive.py` validates the durable lifecycle and emits archive schema 1.1 successors while remaining compatible with the checked-in 1.0 archive.

The manifest binds:

- immutable `checkpoint_id`;
- `archived_sequence` and exact one-step `checkpoint_sequence`;
- `archived_state_hash`, projection hash, archived checkpoint hash, and new checkpoint hash;
- previous manifest hash/path and previous checkpoint hash;
- source reducer run ID, source artifact ID, source head SHA, artifact digest, and artifact creation time;
- checkpoint freshness time;
- an explicit `replay_overlap_seconds` value (six hours) and the corresponding bounded scan start;
- archived event hashes and provider artifact digests.

Archive/checkpoint files are stored in the repository, including the immutable archive path under `state_journal/archive/`, active `ARCHIVE_MANIFEST.json`, and `CHECKPOINT.json.gz`.

Validation fails closed for archive/checkpoint digest tampering, predecessor hash mismatch, sequence regression, conflicting lineage, missing predecessor manifests, root substitution, incomplete replay, missing replay, and unconsumed expired evidence. Covered expired artifacts are excluded from replay only when their exact evidence identity is already bound into the validated archive.

## Required regression coverage

The merged regression suite covers every Step 7 acceptance requirement.

| Requirement | Durable regression |
|---|---|
| Old event artifacts expire but are covered by a validated checkpoint | `test_expired_old_artifact_covered_by_checkpoint_is_routine` |
| Event after checkpoint still replays | `test_event_after_checkpoint_replays_from_explicit_overlap` |
| Event racing checkpoint/reducer publication is retained | `test_event_racing_checkpoint_publication_is_retained_exactly` plus the in-flight producer overlap regression from PR #297 |
| Corrupted checkpoint hash fails closed | `test_corrupted_checkpoint_hash_is_distinct_failure` |
| Checkpoint sequence regression fails | `test_successor_rejects_predecessor_hash_mismatch_and_sequence_regression` |
| Mismatched predecessor hash fails | same predecessor-lineage regression above |
| Missing required replay fails | `test_missing_post_checkpoint_predecessor_is_distinct_failure` |
| Incomplete replay fails | `test_incomplete_archived_prefix_replay_fails_closed` |
| Conflicting checkpoint lineage fails | `test_conflicting_live_checkpoint_lineage_fails_closed` |
| Checkpoint cannot silently change root state | `test_checkpoint_root_cannot_be_silently_substituted` |
| Checkpoint + replay reconstruct exact canonical state | successor lineage/replay tests in `tests/test_state_journal_checkpoint_race.py` and archive lifecycle tests |
| Bounded discovery remains bounded | `test_bounded_discovery_limits_are_not_raised` |
| Complete Actions history may disappear after checkpoint | `test_reducer_rebuilds_from_checkpoint_when_actions_history_is_empty` |
| Archived overlap evidence is not reopened or replayed twice | `test_archived_overlap_artifact_is_not_pending_or_replayed` |
| Archive tampering fails closed | `test_repository_archive_tamper_fails_closed` |

## First protected archive

PR #255 archived canonical sequence **32** from reducer run `36720433600` and snapshot artifact `11099595035`.

- archived canonical state hash: `sha256:f15c34429dde9bb6cbcde01990358a01e71a6b6205d89b487fdd9f999f454c86`
- compact checkpoint sequence: **33**
- compact checkpoint hash: `sha256:ebb1200e30537e04b9aef15de81b354cac465a3b1a24f730974d59b00d5a9214`
- archive manifest hash: `sha256:adc48e60761914656e4a427bbf5db72d0272a5ecd1a4a868b5ffd66f431f3dc1`

This checked-in archive is sufficient to make expiry of older covered Actions artifacts non-catastrophic; uncovered evidence remains a distinct fail-closed condition rather than being silently discarded.

## Live acceptance

The final protected-main continuation chain proved the exact required order.

### 1. Checkpoint/archive restore

Reducer run `36751247379` on protected main completed successfully at canonical sequence **40** with:

- `checkpoint_recovery_status=VALID_CHECKPOINT`;
- production authority true;
- legacy parity PASS across 11 domains.

The active archive was `canonical-archive-seq-00000032`.

### 2. Fresh producer event

Runtime producer run `36751247931` succeeded and emitted immutable event:

`PSE-e7ba6a5ba6356ea49216ad1c2e9921517b3f83d87d4bb255752a67862fd3ad3c`

Artifact `11114329110` had ZIP digest:

`sha256:2eec16818a1a9e3ca7b041cc3871fd30b49d28fb269ed99c901c8b98598ab311`

### 3. Reducer consumed the producer

Reducer run `36751578413` explicitly included producer run `36751247931` in recovery input and completed:

- status `PASS`;
- mode `CANONICAL`;
- `production_authority=true`;
- canonical sequence advanced to **41**;
- `new_deliveries=1`;
- `events_total=13`;
- canonical projection hash `sha256:b8e989c28307e1156a1c6b7fb2ad2e31836f33e3f7f4d20265d6ea3ddc12020a`.

Canonical snapshot artifact `11113879739`:

`sha256:ed39177faefb058911e15a3514d70e2bc25c6307fb5c1a1b79625721b025c09b`

Reducer receipt artifact `11114982102`:

`sha256:9f3572f5c19d04e613ec9e5e6d780a78ebe6f934254004eb6748ac8cac4e8c06`

Sequence-41 domain projection hashes used for continuation were:

- runtime: `sha256:50f4287d98edd6321758f941c4770c71425fc4c2528c8848f209a1d49ffac168`
- heartbeat: `sha256:28d0110ff062f49b2144cfae0d187d6a3527bf43633dcb9651c77d12a741bb9c`

### 4. Production reader restored sequence 41

After protected merge of PR #302, exact-main runtime run `36752372013` succeeded.

The production reader reported `RESTORED_CANONICAL` after sequence 41 had been published. Its runtime and heartbeat `before_hash` values exactly matched the sequence-41 domain hashes above.

The continued cycle emitted immutable event:

`PSE-64020ae943a52d36f15b9bb9c51eee38fded922ead1960f1d84a76d7ab83acae`

Event artifact `11115540494` digest:

`sha256:9e06a3bebb21448a88c501154958ef19547d173025d1ddbb543d06eac2cf1b5f`

Runtime artifact `11115950057` digest:

`sha256:c358e09698d46ac7a88ea031bfbc29f0983ff4fd6e518d4c4bd85c8facafb5d7`

The acceptance artifacts were independently digest-checked against GitHub provider digests.

## Acceptance conclusion

Step 7 satisfies the required live chain:

**validated checkpoint/archive -> fresh producer event -> canonical reducer -> new snapshot -> production reader restore**

with sequence/hash continuity, explicit replay overlap, bounded discovery, retained in-flight evidence, immutable lineage, and fail-closed handling of corruption, missing replay, expired uncovered evidence, and conflicting lineage.

GitHub Actions artifact expiry is therefore routine for evidence already covered by the validated checkpoint/archive and remains a hard failure for evidence that has not been safely consumed.
