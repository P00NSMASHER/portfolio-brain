# V5 original ZIP evidence bundle — manual and non-authoritative

This is an **on-demand** verification tool for previously downloaded original GitHub Actions artifact ZIP files, not a scheduled job, additional clock, runtime component, provider API client, or production acceptance writer. It performs no network requests or writes to the inspected inputs.

## Purpose and invocation

The existing soak_v3.audit.verify_artifact function already checks each ZIP SHA-256, its embedded delivery identity, preflight and doctor results. The new soak_v3.original_zip_bundle module reuses that algorithm for an ordered set of original archives, adding checks for mandatory workload reports and the consecutive state commit chain.

Use: python -m soak_v3.original_zip_bundle --manifest /path/to/manifest.json

Every output is explicitly labelled OFFLINE_ORIGINAL_GITHUB_ARTIFACT_BYTES_ONLY. Even six hours of perfectly formed input can return only EVIDENCE_INSPECTED_NOT_ACCEPTED, never a terminal V5 PASS.

## Required local JSON manifest

Each of these fields must be grounded in original provider data collected independently, not invented:
- source_sha: frozen forty-character protected production source SHA
- first_state_parent: exact Git commit prior to the first archive
- expected_last_state_commit: expected original provider state tip (optional)
- artifacts: ordered list of one to 100 objects. Each includes run_id (positive integer), path (original locally downloaded ZIP), provider_digest (provider's sha256:... from actual GitHub artifact metadata), and state_commit (exact recorded resulting Git SHA)

Example, with placeholders that are **not proof**:

    {
      "source_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "first_state_parent": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "expected_last_state_commit": "cccccccccccccccccccccccccccccccccccccccc",
      "artifacts": [
        {
          "run_id": 12345678,
          "path": "/tmp/original-github-artifact-12345678.zip",
          "provider_digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
          "state_commit": "cccccccccccccccccccccccccccccccccccccccc"
        }
      ]
    }

An operator must independently acquire and inventory GitHub artifact ID/name, run head SHA, genuine event and completed status, digest, and any original Cloudflare provider record. A caller-written provider_digest does not prove it came from GitHub.

## Verification performed

1. Bound manifest byte count, number of ZIP files, original ZIP size, number of ZIP members, uncompressed member total and each additional original JSON member.
2. Recompute each original ZIP SHA-256, compare with independently supplied GitHub artifact digest, and reject duplicates/unsafe ZIP paths via the existing strict artifact reader.
3. Check exact original delivery source/run/parent/new-commit and publication_verified, with no claimed soak completion.
4. Require preflight, monitor, research, experiment and doctor PASS on the same source, doctor mandatory workloads, canonical hash field, increasing sequence and zero pending events.
5. Examine the signed-origin JSON **as an embedded claim only**, requiring the expected Cloudflare Cron schema/type and signed_origin field; never equate this with independent Cloudflare scheduling or cryptographic signature verification.
6. Require strictly increasing run ID, embedded scheduled/doctor times and a continuous state parent chain from original first parent to reported last tip.
7. Fail the entire batch on one bad archive, inaccurate parent, broken report or missing original bytes. Output fixed diagnostic codes, not private local paths, URLs or exception messages. No partial PASS.

## Excluded from this tool's claims

It does **not** fetch or authenticate provider metadata, independently verify the Cloudflare P-256 signature, retrieve original remote Git SQLite bytes, replay the remote canonical event/ledger chain, inventory every scheduled/failed/excluded provider run, or qualify six hours of actual successful complete cycles. Those independent terminal checks remain mandatory in docs/rebuild/V5_CONTROLLED_CUTOVER.md and docs/rebuild/V5_EVIDENCE_INSPECTION.md.

This change remains a separate **draft review candidate** outside protected production. No brain runtime, workflow, Cloudflare Worker, credential, cron, scheduled ChatGPT task, paid service, trading authority or durable state is altered. Do not merge this source change into main during the current exact-SHA V5 acceptance window.
