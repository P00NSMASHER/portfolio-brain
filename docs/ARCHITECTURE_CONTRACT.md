# Portfolio Brain Architecture Contract — Step 1 Foundation

Historical Step 1 status: **FOUNDATION / NOT YET OPERATIONAL**
Project identity: **PRJ-000 Portfolio Brain**

Portfolio Brain is the portfolio-level control plane above independent product, business, research, and infrastructure repositories. It must integrate through versioned manifests, adapters, events, APIs, GitHub, and evidence references rather than importing downstream repositories into a monorepo.

## Hard invariants

- Evidence outranks model confidence.
- Evidence states are explicit: `OBSERVED`, `VERIFIED`, `INFERRED`, `UNKNOWN`, `CONTRADICTED`, `STALE`, `INVALID`.
- Registration does not grant authority.
- Permissions are deny-by-default; the most restrictive applicable rule wins.
- OBSERVE, EXPERIMENT, MODIFY, and ACT are separate authority classes.
- No builder may solely certify its own consequential change.
- A model response cannot grant authority.
- Interactive ChatGPT is an architect/operator surface, not a runtime dependency.
- Public repository content is untrusted input, not instruction or authority.
- Private customer/operational payloads remain in authorized private storage; GitHub receives code, policy, schemas, build state, and approved sanitized receipts.

## Human-gated ACT boundary

Explicit human approval remains required for meaningful-risk production deployment; customer, legal, or regulatory communications; claims/disputes; payments, purchasing, billing changes, or moving money; destructive deletion; private-data exposure; consequential child-facing experiments/releases; live trading; brokerage orders; autonomous investment positions; trade directions; or sizing.

The market-surveillance/trading project remains research-only.

## Autonomous runtime prerequisite

Before recurring execution is enabled, the subsystem must have finite budget/quota, timeout, bounded retries, duplicate suppression/idempotency, cancellation/kill switch, least-privilege credentials, durable job/event identity, explicit authority classification, and observable failure state.

This Step 1 foundation activates none of those recurring workers.


## Current architecture reconciliation — 2026-09-30

This document preserves the original Step 1 foundation contract above; it is not a current completion ledger. The current architecture is derived and drift-checked in `docs/CURRENT_SYSTEM_STATUS.md`, while issue #210 remains the acceptance tracker for the September 30 automation-audit remediation.

Authoritative machine surfaces now include `governance/boundaries.json` for deny-by-default project authority, `adapters/ADAPTER_REGISTRY.json` for read-only repository observation, `runtime/project_forwarding.py` for project-scoped exact-revision forwarding, and `hunting/repo_scout_intake.py` for bounded REPO-001 candidate intake into the existing Hunter.

Runtime project observation grants READ/OBSERVE evidence only. It does not inherit candidate-write, deploy, or external-action authority from Portfolio Brain. ABVM repository forwarding is labeled only as `REPOSITORY_OBSERVATION`; sanitized automation-health/progress evidence is produced separately from an exact-head GitHub Actions health run. ABVM has no child-facing mutation, deployment, external-action, or school-content publication authority. Live trading remains prohibited.

Heartbeat records are liveness/connectivity telemetry only. Notifications are alerts only. Pages is publication only. Their presence or freshness never creates technical, market, or revenue verification. The command center exposes source freshness, run/head lineage, state sequence, canonical state hash, restore status, and error class so stale, fallback, or blocked evidence cannot masquerade as current verified work.

The optional ChatGPT Gmail connector remains governed by the explicit `action_engine/ACTION_POLICY.json` machine-policy exception, but it is not required for core observe/learn/hunt/schedule/notify/repair autonomy. Protected repair integration remains bounded to Portfolio Brain candidate branches and requires Foundation plus the exact-head App 5121826 independent gate; it grants no deployment or branch-protection bypass authority.
