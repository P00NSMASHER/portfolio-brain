# V8 follow-up health audit — October 16, 2026

## Production evidence

Protected main remains `d63efa3b36e1fe695b6f43480fb858a394897a9e`; #702 current-source unattended acceptance is open. This audit does not start or certify an acceptance clock. Optional corrections remain on draft #709.

The latest three observed production cores (38932569112, 38936428439, 38940287010; October 16 16:31–17:31 UTC) passed every job step, including the v8 engineering handoff. The latest log verifies the configured Cloudflare signature and successful exact-source preflight, doctor, and publication. This does not independently corroborate all provider Cron activity or establish six-hour acceptance. Two GitHub research branch lookups returned 404; the cycle remained successful. These are unavailable source observations, not evidence of useful research or repaired projects.

Durable state `e75ea2c87e95ae39dad7af1f087736207c08e39e` was fetched from Git, reconstructed from 15 original chunks, and independently replayed. Raw bytes: 122,937,344. SHA-256: `45065a4ba685295e6d242866890a90c44af9f1c7b35a59b9eec07196ba55935b`. Counts: 2,345 events, 2,345 ledger rows, 1,051 attempts, 1,047 reports. Pending events: zero. Canonical hash: `055bc66f5de6ee20c6d90d584d9ad2247d1539b828d86276cf552ee568b6742a`. Source binding, SQLite integrity/foreign keys, canonical event identities, contiguous ledger and deterministic latest-report replay all passed.

The held candidate's copy-only cleanup produced **31,547,392 raw bytes / 4,891,147 packed bytes**, with canonical tables and replay unchanged. It fits the earlier conservative verified envelope (120,512,512 raw / 20,602,941 packed), leaving 88,965,120 raw and 15,711,794 packed bytes of headroom. No capacity ceiling was raised and no production state was modified.

## Reproduced and corrected

1. The CLI replaced `OWNER_BRIDGE_READY_WITH_GAPS` with generic `PASS`. It now preserves operational status and reports successful command execution separately as `command_status`. Coverage gaps remain visible.
2. Missing provider timestamps raised unhandled `KeyError`. They now fail through the UTC contract as `BrainError`.
3. A digest-valid private automation record containing a malformed status raised `TypeError`. Type checks reject malformed durable identities, changes and statuses before provider access.
4. Outcome aggregation materialized the entire private history. It now streams records into fixed counters, preserving count semantics and zero independently authenticated actual-success claims.
5. The kernel journal could commit growth beyond its 64 MiB reopening limit. An in-transaction SQLite page-size check now rejects growth before commit. Regression verifies rollback, byte preservation and successful read-only reopening.

All five regression cases failed on the original implementation, then passed after correction. Focused integration/security/state tests: 61 PASS. Full local suite: 2,053 tests PASS, with two explicit platform skips. Exact-source independent CI results are recorded in the PR. Public SQLite and the owner-private kernel journal are distinct stores; this correction does not migrate production state.

## Ten-category status

| Category | Evidence | Remaining requirement |
|---|---|---|
| Production reliability | Latest three original jobs and all steps PASS | Complete current-source unattended acceptance |
| Autonomous recovery | Existing watchdog and guarded recipe/owner bridge | Prove one real cross-project repair through deployed recovery |
| Research quality | Bounded source selection, relevance tests, unknowns retained | Useful independent corroboration and tested source/licensing provenance |
| Architecture | Active Brain package bounded; local regressions corrected | Dependency-proven legacy retirement; broad maintainability audit |
| Security and permissions | Protected source, private ownership, isolated verification | Verify real executor capabilities and deployed access boundaries |
| Durable state | Original state integrity and strict replay PASS; candidate cleanup PASS | Release held retention and independently verify production readback |
| Independent testing | Negative/positive regressions and separate CI/App gate | Real deployed journeys and explicit platform skips |
| Cross-project intelligence | Nine registry-bound project contracts and owner jobs | Actual authorized owner execution and verified downstream delivery |
| Actual outcomes | Simulated/reported actual outcomes distinguished | Provider-authenticated repair and usefulness evidence |
| Efficiency | Streaming outcomes; chunked capacity checks; copy cleanup saves 74% raw storage | Monitor canonical-history growth and verify released retention behavior |

No zero-defect, fully autonomous or 100/100 certification is justified by this bounded audit. Production execution is passing, but implementation and local tests do not prove deployed recovery or missing runtime access.

## Next upgrades, in order

1. Complete independent source-bound acceptance, then release #709 through existing gates and verify fresh durable readback/rollback.
2. Deliver one real repair end to end in an owned project: provider-authenticated incident, reproducer, minimal patch, independent CI, protected merge, deployed journey recovery and outcome receipt.
3. Connect owner execution through explicit per-project capability checks, idempotent intents, source reobservation, bounded retries and reconciliation. Expand only after the first repair works.
4. Add deployed browser/runtime journey verification, including ABVM phone/tablet/print and Roblox Studio checks through actually available owners.
5. Authenticate repair/usefulness outcomes, then improve research ranking with verified source identity, license, relevance, independent corroboration, deduplication and provider budgets. Focus on project maintenance value.
6. Build a dependency inventory of active legacy modules and CI consumers; retire unreachable paths in reversible batches after behavior parity is demonstrated. Retain immutable history and required regressions.

## Reproduction

- Fetch the exact state commit above; archive it to an isolated directory and run `python -m brain.state_archive restore --root DIRECTORY`.
- Run `soak_v3.audit.verify_sqlite` with strict event IDs, exact source/sequence/hash above and an explicit adequate byte bound; independently reproduce the latest report using its original timestamp.
- Run copy-only `brain.state_maintenance`, pack/restore the copy, validate its publication envelope and repeat independent replay.
- Run `PYTHONPATH=tests:. python -m unittest tests.test_brain_v8_audit_regressions`.
- Run `python -m unittest discover -s tests` and `python -m operations.validate_operating_mode`.
- Confirm both Foundation and the distinct verifier App checks bind the published candidate SHA. Never reuse old-source checks as new-source acceptance.
