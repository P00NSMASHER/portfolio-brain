# Portfolio Brain Architecture Contract — Step 1 Foundation

Status: **FOUNDATION / NOT YET OPERATIONAL**
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
