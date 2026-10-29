# Source-bound reuse-knowledge reconciliation (2026-10-29)

## Scope and governance

- Preserve all historical evidence from PRs #688, #737 and #782. These 3 candidate datasets contained 23 rows representing **19 distinct source keys**; duplicate keys had matching recorded implementation Git blob identities.
- Twelve sources below were re-fetched at the recorded immutable public repository head SHA. Each returned original implementation Git blob SHA matched the recorded blob SHA. At least one recorded test-path file for each was separately found at the same head SHA. This confirms source identity and file presence, **not** execution of external tests or software quality.
- The exact historical `code_sha256` strings and licenses remain *reported metadata*; this reconciliation did not independently re-hash raw implementation bytes, validate license grants, or execute any third-party code.
- `brain/REUSE_KNOWLEDGE.json` intentionally remains capped at **12 source rows**, schema v2, structural-only scope. The other seven are preserved in the original immutable PR heads and cataloged below, not silently discarded.
- No rights, commercial utility, customer revenue, production use, execution, new spending, secrets, or merge authority is inferred. Any later change requires current-main independent App checks and protected PR governance.

## 19-source census

| Status | Source key | Target | Recorded license | Original evidence PR(s) |
|---|---|---|---|---|
| Historical hold | `Misterio070/scanpay:examples/x402_facilitator_payer.py` | agent-products | UNKNOWN | #782 |
| Selected | `Kalmi91/kimacha:lib/schedulePreview.ts` | school-tools | NOASSERTION | #782, #688, #737 |
| Selected | `kirill-markin/flashcards-open-source-app:apps/backend/src/progress/reports/loaders/reviewSchedule.ts` | school-tools | MIT | #782, #737 |
| Selected | `AwokenLazarus/Lightning-Stream-py-channel:docs/x402/check_vectors.py` | agent-products | Apache-2.0 | #688 |
| Historical hold | `HadiYoussef2005/LeetLeitner:src/engine.ts` | school-tools | UNKNOWN | #688 |
| Selected | `MangroveTechnologies/mangrove-agent:server/scripts/inspect_x402_payment.py` | agent-products | MIT | #688, #737 |
| Selected | `dhyabi2/nano-invoice:examples/x402_seller.py` | agent-products | MIT | #688 |
| Selected | `Rishichamp/lumen:backend/app/api/routes/review.py` | school-tools | MIT | #688 |
| Selected | `econdash/econdash-python:src/econdash/_payments.py` | agent-products | MIT | #688 |
| Historical hold | `maydinidil/aydinlearns:core/scheduler.ts` | school-tools | NOASSERTION | #688 |
| Selected | `financedistrict-platform/fd-prism-sdk:python/packages/core/prism_sdk_core/payment_replay_guard.py` | agent-products | MIT | #688 |
| Historical hold | `msb7-jpg/flashcard-app:src/composables/useStudySession.ts` | school-tools | UNKNOWN | #688 |
| Selected | `inamprotocol/inam-protocol:examples/x402-verify-before-pay.ts` | agent-products | Apache-2.0 | #688 |
| Selected | `pieralukasz/true-recall:packages/obsidian/src/features/study/services/ReviewSessionController.ts` | school-tools | NOASSERTION | #688 |
| Selected | `Austin-Brock/FreightLens:backend/app/api/audits.py` | freight-recovery | UNKNOWN | #737 |
| Selected | `yyyqqqhh/attention-kernel-lab:src/attention_kernel_lab/benchmark.py` | research-methods | UNKNOWN | #737 |
| Historical hold | `livastic-vm2-primary-20260911/livastic-vm2-primary-20260911.github.io:tools/build_vm5_agent_bazaar_manifest.py` | agent-products | NOASSERTION | #737 |
| Historical hold | `sethbang/venice-py:examples/x402/solana_settlement.py` | agent-products | MIT | #737 |
| Historical hold | `shipking-ai/BonaMind:auramind-gemini/src/pages/study/studyPreview.ts` | school-tools | NOASSERTION | #737 |

## Source integrity and selection

Selected evidence independently re-read: original implementation `blob_sha` matched at pinned `head_sha`; at least one original test path exists. The stored SHA-256 field is carried from the earlier evidence unchanged and is not a new independent digest certification.
All selected original source and test paths remain linked through their `repository`, `head_sha`, `path`, `test_paths`, `blob_sha` and historical `code_sha256` fields in `brain/REUSE_KNOWLEDGE.json`.
The selected set includes 6 agent-products, 4 school-tools, 1 freight-recovery and 1 research-methods record; source order follows a deterministic target round robin. A different ranking/selection requires a new source-bound PR, not silent overwriting.

## Protected release boundary

Candidate base: `f9cf5a15452896246cfdef78cca38053734bafab`. Candidate fingerprint: `6fea60150a7c028c9dc64f356e24a3398019c3c3ec7e415907a95981ac0acd5f`.
This remains non-authoritative metadata pending exact-head Foundation/independent App checks and integration *after* the current source's ongoing 12-hour observation. Historical #688/#737/#782 must not be closed as integrated until this consolidation is actually merged.
