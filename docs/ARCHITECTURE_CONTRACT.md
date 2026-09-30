# Portfolio Brain Architecture Contract

Status: **OPERATIONAL CONTROL-PLANE CONTRACT**
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

Recurring workers may run only under their checked-in machine policy, quota, kill-switch, idempotency, and evidence contracts. Historical Step 1 language is retained in git history rather than treated as current status.

## Project-scoped authority and forwarding

`governance/boundaries.json` is the machine authority matrix. Every registered project has an explicit `READ_OBSERVE`, `CANDIDATE_PR`, `DEPLOY`, and `EXTERNAL_ACTION` vector. No project inherits PRJ-000 authority. Repository observation forwarding validates the adapter-to-project route and uses a deterministic forwarding identity so duplicate delivery is suppressed exactly once.

Observation capability does not imply candidate-write, PR, deployment, or external-action authority. Protected bot repair integration is a distinct PRJ-000 path bound to exact-head Foundation `validate` and independent verifier App 5121826 checks; it does not grant production deployment authority.

## REPO-001 scout intake

REPO-001 scout queue documents remain `PRE_VERIFICATION_DISCOVERY_ONLY`. The intake bridge is bounded, source-revision/finding-identity deduplicated, and targets only explicitly mapped projects. Eligible candidates are deep-inspected through the existing `hunting.autonomous_hunter` provider/classification/ranking/proposal functions. The bridge is not a second Hunter engine and grants no reuse, write, deploy, market, or revenue authority.

## ABVM boundary

PRJ-006/REPO-003 may be observed for repository automation health/progress evidence only. Child-facing mutation, deployment, and school-content publication remain human-gated and are machine-tested as absent capabilities.

## Telemetry and publication semantics

A heartbeat is liveness/connectivity telemetry only. A notification is an alert only. GitHub Pages is sanitized publication only. None of these signals creates technical, market, or revenue verification. The public command center exposes source freshness, state sequence, state hash, and stale/blocked state.

## Current status source

`governance/STATUS.json` is generated/validated from authoritative machine config by `python -m governance.status --check`. It intentionally does not self-certify GitHub issue #210 acceptance; controlled/live proof and the required hosted checks must complete before the tracker is updated.
