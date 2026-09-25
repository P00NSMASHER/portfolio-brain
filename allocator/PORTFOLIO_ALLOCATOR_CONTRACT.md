# Explainable Portfolio Allocator — Step 15

Step 15 allocates **attention and normalized resource shares**, not real money/hours/calls.

Nine resource classes are explicit:

1. model calls;
2. engineering capacity;
3. testing;
4. research;
5. Hunter runs;
6. art production;
7. human review;
8. API/infrastructure;
9. cash.

## No invented resource pool

No owner-approved real resource pool was supplied to Step 15, so the checked-in recommendation uses 10,000 normalized basis points per resource. These are proportions only. They are not claimed engineering hours, dollars, API calls, art hours, or human hours.

Real quantities require a later concrete pool and the applicable governance/approval boundary.

## Evidence and ranking

The allocator reuses the AI Business OS allocator's evidence provenance, concentration, freshness, plan-binding and governance principles, but **does not reuse one composite cross-project score as truth**.

For each resource independently:

1. determine evidence-backed eligibility;
2. preserve the complete eight-component Step 11 uncertainty vector;
3. compute Pareto layers;
4. use the explicit Step 11 tie-break;
5. convert Pareto layers to normalized shares using fixed public layer weights;
6. enforce a 50% per-project concentration cap;
7. leave unused capacity as HOLD.

The share conversion happens **after** multi-component ranking and is not a hidden success score.

## Current allocation consequence

Current evidence creates a legitimate recommendation for:

- RESEARCH — read-only evidence-acquisition experiments;
- HUNTER_RUNS — capability-evidence gaps;
- HUMAN_REVIEW — human-gated experiments, with RecoveryWorks first because its external-validation uncertainty dominates the other current human-review candidates.

Current evidence does **not** justify allocating:

- MODEL_CALLS — Tier 1–3 providers are disabled;
- ENGINEERING_CAPACITY / TESTING — no ready isolated synthetic implementation/test experiment currently exists;
- ART_PRODUCTION — no art-specific uncertainty/experiment exists;
- API_INFRASTRUCTURE — no approved infrastructure expansion need exists;
- CASH — no approved concrete cash pool/governance receipt exists.

This is intentional. The allocator must not create busywork merely to consume capacity.

## Authority

Recommendations are advisory. A HUMAN_REVIEW share means "review this question first," not "approved."

Cash remains human-governed. Customer communication remains human-gated. The allocator cannot move money, send messages, deploy, modify downstream repositories, enable model providers, or authorize ACT.
