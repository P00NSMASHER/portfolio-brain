# Phase 1: evidence trust and protected integration

Scope: PB-01 through PB-04 only. Implementation branch `phase1/trust-boundary-20260928`, PR #167. Administration issue #65 remains open. No mainline integration, deployment, paid model calls, rights-policy change, or Phase 2 state repair is authorized by this code.

## Current disposition

The baseline is main `bb60815ba1ed25c6914752eee03882c6d183e607`. Its foundation CI run 36450048810 and Pages run 36450048427 succeeded, but runtime-event-observe 36450049847 failed. The downloaded Pages preview artifact 10983215515 reports bridge `DEGRADED`; runtime and agents have restore errors, cost and scheduler are stale. These are Phase 2 findings, not fixed by a new page timestamp.

PB-01: ownership and current evidence reconciled. PB-02: release-verifier implementation is prepared, but provider enforcement and an independent verifier/reviewer are BLOCKED. PB-03/PB-04: proposed code and regressions on this draft branch, not production acceptance. Full Phase 1 completion requires all four acceptance gates, not just green branch CI.

Existing repairs #161/#160/#155/#154 retain their Phase 2 ownership and must be reconciled then. Existing unrelated PRs #151/#150/#149/#140 are not merged, closed, or duplicated here. This file is a scoped handoff, not a competing persistent task queue.

## What is now checked

Replay schema 2 stores the actual input records, policy, evaluation-contract hash, provenance and complete opportunity denominator. Its validator reconstructs every derived field and rejects duplicates, malformed types, nonfinite costs, stale contracts and rehashed contradictory metrics. Empty execution metrics stay unknown and exclusions remain visible. Structural validation does not establish source authenticity.

Challenger schema 2 builders return CLAIM_ONLY, not PASS. Trusted consumption must bind discovery, policy, source revision and evaluator revision; resolve actual adapter measurements, replay inputs, decision-time snapshots and unique forward cycles; and reconstruct the final assessment. A synthetic fixture can exercise the logic but never qualify for production review or allocation. The three-cycle floor proves only a bounded technical smoke, not statistical superiority. Forward performance improvement remains explicitly unestablished.

Attribution schema 2 validates original records and recalculates its snapshot before exposing dimensions. `preview_dimensions` is explicitly unverified. `allocator_dimensions` requires independently resolved production evidence. Contribution accounting and policy evaluation improvements remain Phase 4.

## Trust is a deployment boundary, not a JSON field

`verification/evidence.py` accepts an EvidenceResolver supplied by trusted orchestration code. Candidate JSON cannot choose the resolver, issuer, code revision, policy, clock, network functions or credentials. The resolver, release gate, configuration and their dependencies must execute in an independently protected environment, without checking out or executing candidate code. Arbitrary Python under the verifier identity would invalidate the boundary. Unit-test dependency injection is not proof of that environment.

The GitHub artifact adapter checks an explicit repository/workflow/revision/branch/principal allowlist, provider run and artifact identity, run-attempt chronology, provider digest, bounded ZIP bytes, strict JSON, subject bindings and freshness. Unknown sources fail closed before network access. The provider principal is linked to a reviewed pinned workflow; a checksum alone never authenticates a claim. Raw private data, credentials and signed artifact download URLs must not be persisted.

`EVIDENCE_TRUST_POLICY.json` has no approved sources. `RELEASE_GATE_POLICY.json` has no trusted gate App, approved reviewer or required check specs. This is intentional: administration read returned HTTP 403 and the available browser session was not signed in to GitHub. No identity, approval, protection result or production evidence has been fabricated.

## Issue #65 remaining requirements

Establish an authorized admin path and a genuinely independent verifier/reviewer. Run this read-only release-verifier logic from that protected identity; pin its implementation and configuration outside the candidate's write authority. Configure a required gate from that issuer, required PRs/current-base evidence, conversation resolution, force-push/deletion restrictions and an explicit audited emergency path. The supplied library does not install a GitHub check or enforce repository settings by itself.

Use fresh provider data to reject missing/skipped/neutral/cancelled checks, wrong issuers or workflows, unexecuted required steps, stale/dismissed/self approvals, unresolved change requests, incomplete API coverage and head/base changes during verification. A positive unit fixture is not an independently approved PR. Then prove both negative enforcement and a legitimate positive integration without bypass; do not count a no-op push as proof of a rejected write.

## Migration and rollback

Legacy receipts without recoverable original input evidence are retained as historical/unverified, not silently upgraded. Rebuild from exact preserved source records to issue schema 2. Preserve user-confirmed results and OPERATOR_ASSUMED business-rights provenance at their original scope; neither substitutes for technical verification.

If a source is unavailable, block its consumer and retain the evidence. Do not restore the old permissive validator to recover a green dashboard. No changes to cost/scheduler ceilings, paid admission, workload/state writers, actions or license-admission policy are included.

## Validation boundary

The initial exact-branch GitHub source archive b04710f31ef7b883086e7d9389be1641dee68716 passed 700 existing regressions. The new replay adversarial test file was run unchanged against that baseline and failed, then passed against the patch. Provider, release and forward-evidence fixtures are explicitly simulated; they prove code behavior, not live admin access or a real completed canary. Exact final-head CI and artifact digests are recorded in PR #167 and the execution tracker, without treating the implementation author as an independent approver.
