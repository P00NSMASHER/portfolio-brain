# V8 health, cleanup, and capacity audit — 2026-10-16

## Scope and production evidence

Production main remains `d63efa3b36e1fe695b6f43480fb858a394897a9e` during issue #702 source-pinned acceptance. This change is a held candidate, not a production recovery or six-hour PASS. The post-merge push core 38906465622 passed; nine projects were observed and five owner handoffs generated, with zero runtime actions executed. Handoffs do not establish autonomous repair delivery.

Original state `270a5b71085600e26f114f4d63925eb0f2b1d9d0` was independently reconstructed from Git chunks and replayed: 119,312,384 bytes; SHA256 `93ef14967df22e9011b2c0b93df74f968347979af201e42d25308e780e340a60`; sequence 2291; zero pending events. Reports used 104,554,496 table bytes, versus 14,020,608 event bytes. There were 1,020 reports and no free pages. VACUUM alone would not address retained report growth.

## Corrections

- Private namespace admission now refuses record 257 before writing. Existing records, reconciliation, and rollback remain usable at capacity. This bound belongs to the private operational file store, distinct from the public SQLite database.
- Private automation reconciliation streams decoded records. A local workload of 64 records containing large prompts decreased peak Python allocations from 18,286,831 to 1,434,368 bytes (92.2%); this is not production RSS evidence.
- Hostile enum and research-history inputs raise contract errors rather than unhandled TypeError. One verified unused import was removed; legacy modules still required by CI were retained.
- Independent chunk/SQLite evidence tools explicitly support up to **5 GiB (5,368,709,120 bytes)**, exceeding the requested decimal 5 GB. Chunk size remains 8 MiB. Tree inventory and the explicitly selected current-state reader request budget scale to 640 chunks plus bounded metadata. Default generic reader budget remains 12. Historical default SQLite replay cap remains 25 MB.

## Safe cleanup

`python -m brain.state_maintenance --source SNAPSHOT --target NEW_COPY` prepares a separate public SQLite copy. It refuses existing destinations, symlink source/destination, active WAL/journal sources, corrupt SQLite, foreign-key violations, and mismatched report hashes. It retains the latest 128 reports, the latest report per source, and every non-PASS report. Events, ledger, attempts, metadata, schema, and sequence watermarks must remain identical. Receipt includes original/output image digests and every removed report ID/hash. It never publishes or mutates the input snapshot.

On the verified original above, the prepared copy decreased from **119,312,384 to 31,277,056 bytes**, retaining 141 reports and removing 879 derived report bodies. Independent canonical event/ledger validation and deterministic latest-report replay both passed on the copy. Historical source snapshots remain untouched. This is approximately 73.8% less storage for this snapshot, not a claim about every future database.

Release after #702 requires a fresh current-state snapshot, immutable archived original, new receipt, all independent replay gates, latest-state compare-and-swap publication through the existing protected workflow, and post-publication verification. Do not upload this older prepared snapshot over newer production state. The candidate integrates automatic retention into the existing guarded cycle; it remains inactive in production until release gates allow this PR to merge.

## Capacity qualification and constraints

A local synthetic SQLite image of **5,038,161,920 bytes** passed production chunk packing, independent original-Git-format reconstruction, SQLite integrity and event/ledger/report checks in 91.71 seconds: 601 chunks and 604 simulated Git reads. The generated payload was highly compressible zeroblob data (11,206,022 packed bytes); this demonstrates actual local byte-volume handling, not a network upload, production workload, quota, or incompressible 5 GB push. Separate manifest tests exercise maximum-size compressed overhead and overflow rejection.

The `state-capacity-qualification` workflow makes this a repeatable exact-source gate. One job creates and packs at least 5,000,000,000 real SQLite bytes with the production codec, transfers only the exact packed chunks through a one-day Actions artifact, and a separate job restores and replays them inside a network-disabled container. Its receipt deliberately remains `production_capacity_verified:false` until a durable backend is independently read back in production. Temporary Actions artifacts are qualification transport, not the database authority.

### Verified durable production envelope

The actual `brain-state-v2` head `3de54070a8256073e667bfbf481170d693b6663a` was fetched back from Git on October 16 and independently reconstructed from 15 chunks. Its **120,512,512 raw bytes** and **20,602,941 compressed bytes** passed SHA-256, SQLite integrity, strict canonical event/ledger replay through sequence 2312, zero-pending-event verification, and deterministic latest-report replay against main `d63efa3b36e1fe695b6f43480fb858a394897a9e`. These measured sizes are the current verified production lower bound, not GitHub's theoretical limit.

Brain now uses that honest envelope for publication. Above 80 MiB raw, 75% of verified packed capacity, or 256 reports, the expendable working copy compacts derived reports before packing while retaining the latest 128, the latest report per source, and every non-PASS report. It then refuses publication if either raw or compressed output exceeds the independently observed production envelope. The exact live snapshot compacted to **30,883,840 bytes** in a copy-only test while all 2,312 events and ledger rows, 1,033 attempts, schema, canonical hash, and latest report replay remained unchanged. Historical Git state commits remain the full audit archive. The measured packed-size trigger uses the production codec and 8 MiB chunks, keeping compression memory bounded. Both raw and packed sizes must fit before replacing the working copy. Receipts expose exact remaining headroom and a warning at 80% utilization. These controls bound derived-report growth; immutable event history still grows and no indefinite storage lifetime is claimed.


Fresh follow-up readback of state commit `f89dfde5dc53b4154bf4081a15d001e53a9bddad` independently replayed sequence 2322 and compacted **121,315,328 → 31,068,160 raw bytes / 4,810,623 packed bytes**. Canonical hash `c96ca397ecf7930a4c22fb2296f862d685dc8ffcb58fcabb2e9e8c6aee4d23c8` and deterministic latest-report replay were preserved. The conservative earlier verified capacity bounds were retained, leaving 89,444,352 raw bytes and 15,792,318 packed bytes of measured headroom. This was a copy-only test, not a production mutation.

The production writer's nominal 64 GiB codec bound did not establish operational capacity: independent replay previously capped at 256 MiB. The new explicit audit bound removes that mismatch for the 5 GB target. Full event replay still materializes event history; large archive-byte tests do not establish bounded-memory replay for 5 GiB of actual event bodies. Both compressed overhead and full retained report columns are verified. No storage service was purchased, empty database preallocated, quota enlarged, or production capacity certified.

Git is a poor long-term transport for continually rewritten multi-GB SQLite snapshots. GitHub documents a 2 GiB maximum per push and recommends repositories stay below 1 GB, with below 5 GB strongly recommended. A 5 GB database can compress below the push limit, but arbitrary incompressible content cannot be assumed to do so. A reliable 5 GB production service therefore needs measured storage/quota, disk, restore-time and transport-budget qualification, or an existing funded database/object store with verified capacity. Never remove bounds or split commits to claim unavailable production storage.

Sources: https://docs.github.com/en/get-started/using-git/troubleshooting-the-2-gb-push-limit and https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github.

## Next upgrades, in priority order

1. Finish genuine current-source unattended acceptance, preserving original adverse attempts and independent evidence.
2. Deliver one real repair end to end: authenticated runtime capability, owner execution, regression test, protected merge, production recovery, recorded outcome. Expand only after it works.
3. Qualify durable 5 GB runtime storage and restore transport; then integrate reviewed periodic derived-report retention with source-pinned migration receipts and rollback.
4. Verify deployed user journeys and build identities across project owners, including genuine failures and recovery evidence.
5. Improve research and prioritization using independently authenticated sources, license/relevance checks, provider-denial circuit breakers, deduplication, and verified repair effectiveness.

No certified 100/100 or error-free claim is justified. Production execution and state integrity have evidence; arbitrary unattended project repairs, all runtime adapters, and current-source acceptance remain incompletely verified.
