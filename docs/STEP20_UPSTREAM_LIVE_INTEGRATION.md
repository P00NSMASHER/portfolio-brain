# Step 20 — Upstream identity vs live integration proof

This proof exists because a matching checked-in pin is **not** evidence that the upstream integration is currently usable.

## Separate proofs

Every target produces two independent results:

1. **Pin/blob identity proof**
   - resolves the exact pinned repository revision;
   - fetches every pinned source/component file;
   - requires every resolved Git blob SHA to match the checked-in pin.

2. **Live read-only integration proof**
   - resolves the upstream default branch independently of the pin;
   - fetches the live target paths without mutation authority;
   - verifies required classes/functions/constants/methods against a versioned interface contract;
   - reports upstream repository movement separately from target-file/interface drift.

A target cannot be green because its pin matches alone.

## Drift classification

- `NONE` — upstream head equals the pinned revision and target blobs/interfaces match.
- `REPOSITORY_HEAD_ADVANCED_TARGETS_STABLE` — upstream repository head advanced, but every pinned target blob and required interface remains byte/schema compatible.
- `TARGET_BLOB_DRIFT` — one or more tracked upstream target blobs changed. The proof fails closed until reviewed/reconformed.
- `INTERFACE_SCHEMA_DRIFT` — a required live or pinned symbol/method disappeared or the source no longer parses. The proof fails closed.
- unsupported target/pin schema versions fail closed.

Repository-only movement is recorded rather than confused with target drift. Actual tracked blob or interface drift is never reported as healthy.

## Authority

The live probe is `OBSERVE` only.

- GitHub access is public/read-only.
- No write-scoped credential is required.
- No repository, issue, PR, deployment, customer, financial, or child-facing action is available to the probe.
- `writes_attempted` is recorded as zero in each target receipt.

## Exact-main acceptance

Step 20 is complete only after this workflow is protected-merged and an exact-`main` run uploads a PASS receipt containing:

- repository SHA;
- workflow run ID/attempt;
- all pin revisions and blob identities;
- upstream head revisions;
- target drift classification;
- live interface checks;
- receipt hash.

CI or a checked-in pin without the live receipt is insufficient.
