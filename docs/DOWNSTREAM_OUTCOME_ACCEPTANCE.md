# Portfolio Brain: downstream repair completion

## Invariant

**An exact-head PR, a protected merge, green tests, and a green workflow do
not count as a complete downstream repair.** The offline owner continuation
ledger preserves MAIN_TECHNICALLY_VERIFIED only as a technical stage; that
state stays pending and may not be silently archived as a completed repair.

The module brain/v11/downstream_outcomes.py is the audited, read-only path
added by this change that can return VERIFIED_REAL_WORLD_REPAIR. For each
explicitly registered candidate it independently re-reads:

1. An active repository ruleset without bypass actors, strict checks from
   two distinct pinned GitHub App identities, and the original PR's
   exact head/merge/source identities.
2. The immutable first parent of the merge commit, and an **already existing**
   approved JSON behavior contract at repair/downstream-outcomes/<PR>.json
   on that parent. Mutable PR descriptions and post-hoc contracts are not proof.
3. The actual candidate head's successful checks from both pinned Apps.
   Main must still equal the exact protected merged commit: drift is a hold,
   not inferred ancestry or automatic completion.
4. Original GitHub deployment records for that merge SHA, the exact
   environment and the newest successful deployment status.
5. Fresh HTTPS, no-redirect, allowlisted build-info with source_sha
   equal to the merged SHA.
6. A different, real HTTPS functional endpoint whose response SHA-256
   matches the **pre-repair** behavior contract. HTTP 200 alone is insufficient.

The live probe never sends credentials. Reads are bounded. There are no
writes, payments, messages, automatic environment changes or schedule changes.

## Approval and availability

The candidate registry is repair/V11_DOWNSTREAM_CANDIDATES.json
(maximum three). It starts empty: no prior repair is claimed to meet
these conditions. Counts cover only registered candidates, not all repairs.

Preapproved contract JSON example (NOT deployed or endorsed):

    {
      "schema_version": 1,
      "repository": "P00NSMASHER/portfolio-brain",
      "pr_number": 999,
      "environment": "github-pages",
      "build_url": "https://p00nsmasher.github.io/portfolio-brain/build-info.json",
      "behavior_url": "https://p00nsmasher.github.io/portfolio-brain/functional-proof.json",
      "expected_behavior_sha256": "0000000000000000000000000000000000000000000000000000000000000000"
    }

The URLs and digest illustrate the schema, not a real deployed endpoint.
Approve real expectations from independent, reproducible defect evidence.
Never invent a hash to produce a pass.

Current independent issuer enrollment is only Portfolio Brain's
validate (App 15368) and portfolio-phase1-gate (App 5121826). Other
repositories are held until independently checked issuers and live
verification contracts are established.

## Read-only use

From an exact protected checkout with a read-only GitHub token granting
deployment read access:

    python -m brain.v11.downstream_outcomes \
      --batch repair/V11_DOWNSTREAM_CANDIDATES.json \
      --output /tmp/brain-downstream-outcomes.json

The batch preserves individual holds and reasons. The single candidate CLI
accepts --repository, --pr, and --output. Do not copy a claimed success into
durable completion history without original provider and live readbacks.
Older technical receipts remain technical receipts.

## Separate storage investigation (November 4, 2026)

The main source branch has no state/ directory. Durable state advances
separately in the unprotected brain-state-v2 branch, as compressed chunks
and a manifest. At commit 3be1261dfe3d63d522598d88756bdd36b46b7b73,
the manifest reports 98,557,952 raw bytes, 12,895,189 compressed bytes,
and 12 chunks. Versus 6d6b01afb06512922745bb262606e771f0cfc661,
raw state decreased 4,239,360 bytes: changes include an intervening
compaction/reduction, not just monotonic growth.

A separate original-GitHub object inventory over the six consecutive
snapshots ending at 3be1261d shows 44 distinct state-chunk blob identities,
totaling 56,241,760 bytes of compressed payload across those six snapshots.
This directly establishes retained blob diversity in recent state history,
not the total on-disk Git pack size or the size of all repository refs.

The GitHub repository metadata size of roughly 5.2 GiB is NOT the same as
the current working state. It likely includes Git object history and other
refs; the precise source of that reported size has not been reconstructed.
Do not delete history or mutate state on this evidence.

GROWTH_EXCEEDS_80_MIB is a threshold warning in the archive code; it is not
proof of corruption. Storage findings are not downstream repair results.
