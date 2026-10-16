# V8 Engineering Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Steps use checkbox syntax.

**Goal:** Connect the tested kernel to existing project intelligence and add bounded, independently testable engineering adapters across the ten requested upgrade areas.

**Architecture:** Reuse existing source collection, deterministic recipes, state, project owners and verifier. Add small adapters with explicit uncertainty; only the existing Chat owner can execute unsupported provider operations. No parallel scheduler or invented unattended API.

**Tech Stack:** Python standard library, existing GitHub Actions, SQLite canonical state unchanged.

**Spec:** docs/superpowers/specs/2026-10-15-brain-v8-design.md; user-approved ten-upgrade list in the current conversation.

## Global Constraints
- No new spending, credentials, customer communications, financial actions or Work-credit workflows.
- Keep the existing 24-GET ceiling and bounded provider retries.
- No v8 change inherits an older version's acceptance.
- Private records must never enter public canonical state.
- Do not erase incidents, acceptance receipts, state branches, source provenance or valid user changes.
- Supplied observations and source checks do not grant release authority.

## Review Focus
- Provider timeout after an externally successful write: reconcile before retry (Task 4).
- Two project IDs sharing one repository must retain distinct ownership (Task 2).
- A failed original attempt followed by a green rerun must remain adverse (Task 5).
- A source marker or HTTP 200 alone must not establish deployed recovery (Task 3).
- Missing project observations and incomplete research must remain unknown (Tasks 6,9).

## Tasks

### Task 1: Existing source-bound repair and regression integration
Files: existing #696/#697/#701/#703/#704/#705 changes; preserve source attribution in separate commits.
Interfaces: existing deterministic recipe `brain.repair_patch_executor.generate`; follow-through and independent original-state audit APIs unchanged.
- [ ] Apply exact reviewed diffs independently, reconcile shared files without replacing unrelated work.
- [ ] Run the full existing suite; compare integrated behavior and preserve all negative controls.
- [ ] Commit integration provenance; do not close predecessors until replacement checks pass.

### Task 2: Project engineering maps
Files: brain/v8/inventory.py; tests/test_brain_v8_engineering.py.
Interface: `project_maps(observations: list) -> list`; registry identities plus fixed owner/test/verification contracts, observed source or explicit unknown.
- [ ] Write/run RED tests for complete nine-project coverage, shared-repository distinct owners, substituted/duplicate/future-invalid identity refusal.
- [ ] Implement exact registry binding and bounded source mapping; never infer write capability.
- [ ] Run GREEN tests and commit.

### Task 3: Source-bound independent deployed observation adapter
Files: brain/v8/verification.py; tests/test_brain_v8_engineering.py.
Interface: `probe_asset(read, *, project_id, source_sha, url, expected_sha256) -> dict`; read returns original status/bytes, fixed host allowlist and byte bound.
- [ ] Write/run RED tests for matching original asset, redirected/nonmatching/oversized response, unauthorized hosts and HTTP200 without digest parity.
- [ ] Implement GET-only observation with no acceptance/authority grant. Provenance is source-bound input, not a forged gate.
- [ ] Run GREEN tests and commit.

### Task 4: Private automation reconciliation
Files: brain/v8/private_state.py, brain/v8/automation.py; tests/test_brain_v8_automation.py.
Interface: `AutomationReconciler(root, owned_ids)`; `stage(task_id,before,changes) -> id`; `apply(id,read,update) -> receipt`; `rollback(id,read,update) -> receipt`.
- [ ] Write/run RED tests for durable before-image, idempotence, mismatch, timeout ambiguity/restart, conditional rollback, serialization, unknown fields and private storage refusal.
- [ ] Implement private atomic files, exclusive lock and before/intent/readback records; never automatically retry unknown provider writes or expose prompt bodies in receipts.
- [ ] Run GREEN tests and commit.

### Task 5: Recovery supervision
Files: brain/v8/supervisor.py; tests/test_brain_v8_engineering.py.
Interface: `supervise(inventory, *, source_sha, now) -> dict`; complete original GitHub run page, no privileged mutation.
- [ ] Write/run RED tests for original adverse attempts, incomplete census, stale automatic core, active work, future timestamps, source drift and no failure laundering.
- [ ] Implement bounded diagnosis and existing-owner/watchdog requests; never self-accept a repair.
- [ ] Run GREEN tests and commit.

### Task 6: Need-driven research
Files: brain/v8/research.py; tests/test_brain_v8_engineering.py.
Interface: `research_actions(projects, candidates, history) -> dict`; existing hash-inspected source records and project need map.
- [ ] Write/run RED tests for relevance, unrelated tests, uncertain license, duplicates, previously unsuccessful unchanged evidence and unavailable results.
- [ ] Reuse source-inspection/relevance signals, distinguish inspectable from licensed/independently useful, and emit bounded owner experiments without executing third-party code.
- [ ] Run GREEN tests and commit.

### Task 7: Durable outcome learning
Files: brain/v8/learning.py; tests/test_brain_v8_engineering.py.
Interface: `record_outcome(private_root, record) -> dict`; exact fields/IDs, actual/simulated/unknown kept separate, no causal or revenue claim.
- [ ] Write/run RED tests for restart deduplication, contradictory same-identity result, failed outcomes, unknown/live distinction and private redaction.
- [ ] Persist bounded private digest-addressed observations; aggregate verified technical outcomes separately from reported/simulated results.
- [ ] Run GREEN tests and commit.

### Task 8: Isolated repair test interface
Files: brain/v8/engineering.py; tests/test_brain_v8_engineering.py.
Interface: `prepare_repair(request, original_bytes) -> dict`; trusted deterministic recipe only; owner action artifact includes exact source and regression digest, no shell/external calls.
- [ ] Write/run RED tests for real recipe positive/negative controls and attempted arbitrary command/code injection.
- [ ] Wrap existing recipe and project test contracts; retain isolation and independent release gates. Browser/runtime gaps explicit.
- [ ] Run GREEN tests and commit.

### Task 9: Unified fair portfolio loop
Files: brain/v8/engineering.py, brain/v8/__main__.py, .github/workflows/brain-cycle.yml; tests/test_brain_v8_engineering.py.
Interface: `build_cycle(report, *, source_sha, cycle, now) -> dict`; CLI `cycle --input --source-sha --cycle --now` reads already-collected project report, returns bounded owner jobs and coverage gaps.
- [ ] Write/run RED tests for all-project fair rotation, adverse-first selection, source substitution, unknown evidence, zero provider calls and stable source-bound work IDs.
- [ ] Reuse kernel planning and existing mission; add one optional diagnostic step to existing cycle, no extra scheduler/authority or canonical DB schema.
- [ ] Run GREEN/full regression and commit.

### Task 10: Operational consolidation and delivery
Files: docs/rebuild/V8_ENGINEERING_LOOP.md, docs/rebuild/ARCHITECTURE.md, review record.
- [ ] Trace runtime, CI and dynamic CLI dependencies before retiring anything; retain active legacy tests and signed state paths.
- [ ] Document one supported engineering entry point, capabilities, rollback and genuine remaining acceptance gaps.
- [ ] Fresh whole-branch review, one reproducing fix pass, full suite, exact-head protected checks; no fictional live acceptance.

## Completion boundaries
Implementation and synthetic verification can finish independently of missing runtime APIs. Fully autonomous live repair, real browser acceptance, unsupported provider access and source-specific unattended acceptance remain unverified until original deployed evidence exists. Never mark those complete because an adapter or fixture passes.
