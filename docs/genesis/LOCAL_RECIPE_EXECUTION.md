# Durable local recipe execution

This second Genesis increment executes the existing allowlisted checkout-hardening
recipe and its generated regression. It creates a patch artifact in private local
storage; it does not edit a target repository, execute target application code,
call providers, open PRs, merge, deploy, or grant release authority.

## Real source demonstration

The original PermitPlate workflow at `cf0b459217245a7799550104cc37a9bad462bdf2`
uses named checkout and Node steps. The old recipe rejected it with
`AUTOFIX_CHECKOUT_V4_NOT_UNAMBIGUOUS`. The retained original 4,023 bytes have Git
blob `167cf0a263b41da50927b300decdbce6ecadeaf9`; the regression verifies this identity.
The narrow parser extension preserves every byte except the two action pins and
the inserted `persist-credentials: false`. Named steps must use the literal
jobs/job/steps hierarchy and canonical indentation. Block scalars, custom checkout
options, ambiguous names and expressions remain refused. Repository allowlists,
prohibited content and permissions are unchanged.

An actual local run on that source failed its generated regression before the
patch and passed afterward. A fresh CLI process reopened the journal and reused
the saved result, leaving journal bytes unchanged. See
[the implementation-session receipt](receipts/local-permitplate-recipe-20261018.json).
This is independently reproducible local evidence, not an independent acceptance
record or proof that the workflow ran in PermitPlate. Its file hashes identify
the final demonstrated implementation, including the reviewed recovery changes. Source heads are supplied
observations; the local runner does not authenticate them.

## Protocol and authority

`brain.v9.local_recipe.execute_recipe` requires a compiled mission, existing
private writable KernelJournal, exact recipe request/source bytes, observed heads,
and UTC time. Work fingerprint must equal the request digest; its resource must
equal the digest of the case-folded repository. The mission DAG is revalidated.

1. Acquire the existing private directory's nonblocking cooperative lock.
2. Validate current source, work membership, selection and resource ownership.
3. Append a deterministic claim and durable intent before running the fixed recipe.
4. Execute only the shipped generated Python regression against temporary files.
5. Fsync the exact generated patch, test and result into a journal-specific private
   outcome directory using the existing PrivateFiles writer.
6. Confirm the intent, advance only local stages, and release the claim.

`DIAGNOSED`, `REPRODUCED`, `PATCHED`, and `TESTED` refer solely to the local fixture.
They never mean target-repository modification, independent review or deployment.
Temporary directories and Python isolated mode are not an OS security sandbox.
The fixed regression executes no target source, receives no inherited credential
environment, and has the existing 15-second subprocess bound. The lock coordinates
cooperating callers using the same journal; it does not fence hostile same-user
processes or unrelated journal writers. A future external adapter needs stronger
transactional fencing and actual provider scope enforcement.

## Recovery

- Stored matching result after intent: finish missing confirmation/stages/release,
  without repeating the regression. Exact artifact and provenance must match.
- Intent with no durable result: stop with `V9_RECIPE_UNCERTAIN_RESULT_NO_REEXECUTION`.
  Lease expiry does not authorize a retry. Preserve original evidence.
- Claim before intent: stop with `V9_RECIPE_NOT_SELECTED`; inspection/reconciliation
  is needed. This increment deliberately does not guess whether work started.
- Corrupt/substituted artifact, stale source, foreign claim, pending dependency,
  future event or altered identity: fail closed. Do not edit or erase journal history.
- Local stages cannot become independent acceptance or release; external trust
  controls remain outside this adapter. Local hashes are not signatures.

## CLI

`python -m brain.v9 exercise --input recipe.json --mission mission.json --journal /private/kernel.sqlite --now 2026-10-18T04:00:00Z`

`recipe.json` has exactly `request`, `original_utf8`, and `source_heads`. The
request is the existing `READONLY_CI_CHECKOUT_HARDENING` schema. The mission must
already be compiled and its work observed in the private journal; the CLI does not
invent work or permissions. Output labels remain local-only, zero provider calls,
and no production acceptance. Input uses the existing bounded strict JSON loader.

## Validation and remaining work

Tests cover real negative/positive subprocess execution, fresh-process CLI reuse,
restart after each stage, result-storage failures, missing results after intent,
orphan claims, source/request substitution, tampering with recomputed hashes,
read-only journal refusal, simultaneous lock contention, and cross-repository
local fixture reuse with uncertain dependency recovery. Synthetic two-repository
fixtures are not two actual delivered repairs.

The complete v9 requirements remain unfulfilled. Next steps are independently
controlled execution admission, real repository adapters, original provider
readback, protected delivery, served-behavior checks and source-specific acceptance.
No workflow, task, Cron, credential, production state or security policy changes
are introduced. Keep PR #718 isolated while #702's d25 hold remains active.
