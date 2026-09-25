# Continuous Portfolio Learning Contract — Step 10

Portfolio Brain normalizes learning across nine domains:

- SEARCH
- ENGINEERING
- TEST
- REGRESSION
- PRODUCT
- CUSTOMER
- EXPERIMENT
- MODEL
- RESOURCE

The engine is **observe-first and advisory**. It cannot deploy, modify downstream repositories, change authority, or automatically promote a policy.

## Evidence hierarchy

A learning observation can be stored without being allowed to train value.

Only observations that are all of the following can update Q-values:

1. `phase = TRAIN`;
2. `measurement_quality = PROSPECTIVE | BENCHMARK`;
3. `evidence_state = VERIFIED`;
4. nonzero value-bearing signal class.

Weight order is:

`VERIFIED_EXTERNAL_VALUE > VERIFIED_TECHNICAL > COST_RESOURCE > INTERNAL_ACTIVITY`.

Internal activity receives zero learned-value credit. Inferred, stale, contradicted, unknown, invalid, retrospective, and evaluation-only observations receive zero Q-value credit.

## Generalization

TRAIN updates do not authorize policy use. A record needs at least 5 measured TRAIN observations / 20 samples **and** 2 independent CONFIRM observations / 6 samples with nonnegative confirmation behavior and at least one positive confirmation.

CONFIRM never trains the Q-value. EVALUATION_ONLY never trains or promotes. Negative confirmation produces an explicit overfit/regression alert rather than being averaged away.

Global and project-scoped memory identities are different; success in one project does not silently generalize to another.

## Production seed

The checked-in observation ledger starts empty. No historical search, engineering, product, customer, model, or commercial event is reconstructed from prose merely to populate the learner.

The Step 8 daily runtime rebuilds and emits `portfolio_learning_state.json` deterministically from the ledger. When later steps add verified observation producers, the same engine can consume them without changing its evidence or promotion rules.
