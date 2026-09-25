# Highest-Value Uncertainty Engine — Step 11

The engine answers one question:

> What unresolved question would create the greatest decision value if answered next?

It does **not** answer "what else can we build?"

## Components retained for every candidate

1. importance
2. uncertainty
3. test cost
4. time to evidence
5. reversibility
6. downstream impact
7. strategic reuse
8. external-validation value

Each component keeps an ordinal value, basis type, rationale and evidence references. Cost/time values marked `POLICY_ESTIMATE` are planning estimates, not observed dollars or elapsed time.

## Ranking

There is no weighted sum and no opaque score.

Eligible questions are separated into Pareto layers across all eight dimensions. Within a Pareto layer, the deterministic tie-break is explicit in `UNCERTAINTY_POLICY.json`, beginning with external-validation value and then importance/uncertainty/downstream impact/reuse before burden and reversibility.

Blocked questions remain visible but cannot be selected.

A human-gated question may rank highest because it has high decision value. That selection is advisory and **does not grant permission** to perform the external action.

## Current portfolio implication

Because the evidence-conservative graph contains no verified CUSTOMER / REVENUE / OUTCOME nodes, external-validation questions are generated for active businesses/products. This is a gap in recorded verified evidence, not a claim that no real-world validation has ever occurred outside the current evidence system.

Capability-coverage questions are also generated when a project lacks an evidence-backed `HAS_CAPABILITY` edge. Graph absence is uncertainty, not proof of capability absence.

The no-prompt runtime canary remains visible but blocked by the explicit Step 24 gate.
