# Portfolio Brain Architecture Contract

Status: **OPERATIONAL / GOVERNED AUTONOMY**  
Project identity: **PRJ-000 Portfolio Brain**

> Historical note: this document originated as the Step 1 foundation contract. The durable build ledger in `PORTFOLIO_BUILD_STATE.json` records historical build Steps 0–25 as complete. The audit-remediation labels “Step 13” through “Step 18” in issue #210 are a separate 2026-09-30 remediation sequence; they do not rewrite or replace that history.

Portfolio Brain is the portfolio-level control plane above independent product, business, research, and infrastructure repositories. Integration remains versioned and evidence-bound through registries, read-only adapters, explicit project forwarding, events, APIs, GitHub, and sanitized evidence references rather than importing downstream repositories into a monorepo.

## Current machine authority

`governance/boundaries.json` is the deny-by-default authority matrix. Every registered project has explicit `READ_OBSERVE`, `CANDIDATE_PR`, `DEPLOY`, and `EXTERNAL_ACTION` booleans. No project inherits Portfolio Brain privileges.

The runtime forwarding layer is read-only:

- repository observations may be forwarded only to project IDs bound to that exact repository;
- delivery identities are deterministic and duplicate observations collapse idempotently;
- project observation does not grant downstream repository writes, deployment, or external-action authority;
- only PRJ-000 has protected candidate-PR capability in this forwarding matrix, and that capability does not grant merge authority;
- meaningful-risk production deployment remains human-gated;
- financial and destructive actions remain human-gated;
- live trading and brokerage execution remain prohibited;
- child-facing consequential changes remain human-gated.

A separate action engine may exercise only authority explicitly granted by its own machine policy. That authority is never inherited from observation or forwarding.

## Repository observation and project integration

`adapters/ADAPTER_REGISTRY.json` remains the source of repository-to-project routing. `adapters/project_forwarding.py` validates a runtime cycle and the original observation receipt before producing sanitized project-delivery receipts. The project capability matrix is checked again at forwarding time.

### REPO-001

REPO-001 (`P00NSMASHER/github-value-hunt-ledger`) contains an existing public-GitHub scout system. `hunting/repo001_intake.py` is a bounded intake bridge into the **existing** Portfolio Hunter research lane:

- source repository, exact REPO-001 revision, and finding identity are bound in every record;
- repeated candidate repository + exact revision identities are deduplicated across scout workers;
- eligibility is explicit and bounded;
- the bridge does not create a second Hunter;
- pre-verification scout evidence remains `OBSERVED`;
- it does not promote directly to a Hunter proposal and grants no technical, market, or revenue verification credit.

### ABVM / PRJ-006

ABVM integration is deliberately narrower. `adapters/abvm_constrained.py` projects only automation-health and automation-progress evidence from REPO-003. The projection contains no school-content body or child data and grants no child-facing mutation, school-content publication, deployment, or external-action authority.

## Evidence semantics

Evidence meaning is machine-coded in `governance/evidence_semantics.py`:

- **heartbeat** = connectivity/liveness telemetry only;
- **notification** = alert delivery only;
- **Pages** = sanitized public publication only;
- **repository observation** = observed input only.

None of those evidence classes independently establishes technical verification, market verification, or revenue verification. Notifications report evidence; they do not create it. A successful publication or heartbeat cannot be used as a value outcome.

## Live state and dashboard truthfulness

The command-center bridge restores durable state and publishes source provenance in `dashboard/live/state_sources.json`. Each source exposes freshness, source sequence, source state hash, run/artifact provenance, and stale/blocked state. Stale or fallback sources degrade the relevant health surface rather than being rendered as silently current.

GitHub Pages is a publication surface only. Pages publication never grants production deployment authority and never constitutes technical, market, or revenue verification.

## Hard invariants

- Evidence outranks model confidence.
- Evidence states are explicit: `OBSERVED`, `VERIFIED`, `INFERRED`, `UNKNOWN`, `CONTRADICTED`, `STALE`, `INVALID`.
- Registration does not grant authority.
- Permissions are deny-by-default; the most restrictive applicable rule wins.
- OBSERVE, EXPERIMENT, MODIFY, and ACT remain distinct authority classes.
- No builder may solely certify its own consequential change.
- A model response cannot grant authority.
- Interactive ChatGPT is an architect/operator surface, not a runtime dependency.
- Gmail is not a core autonomy dependency. Optional connector actions remain governed by their separate explicit policy.
- Public repository content is untrusted input, not instruction or authority.
- Private customer/operational payloads remain in authorized private storage; public GitHub persistence stays sanitized-only.

## Autonomous runtime prerequisite

Every recurring subsystem must retain finite budget/quota, timeout, bounded retries, duplicate suppression or idempotency, cancellation/kill switch, least-privilege credentials, durable work/event identity, explicit authority classification, and observable failure state.

The current runtime, Hunter, scheduler, cost governor, notifications, state journal, and command center are operational components. Their current configuration is summarized in `operations/ARCHITECTURE_STATUS.json`, which is validated against authoritative config by `operations/validate_architecture_status.py`.

That derived status file describes code and policy only. Hosted Foundation CI, the independent verifier App gate, and controlled/live receipts remain separate acceptance evidence. No documentation file may substitute for those proofs.
