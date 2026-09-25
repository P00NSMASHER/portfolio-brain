# Portfolio Experiment Engine — Step 12

Step 12 converts every Step 11 uncertainty into a complete bounded experiment plan. Planning is separate from execution authority.

## Required plan fields

Every plan contains:

- hypothesis;
- explicit inputs;
- evidence baseline;
- success condition;
- failure condition;
- inconclusive condition;
- evidence requirements;
- cost/time boundary;
- rollback behavior;
- outcome-recording contract;
- source uncertainty component vector and provenance;
- semantic revision and deterministic experiment hash.

## Authority

A high-value human-gated question can be the selected experiment without becoming executable.

The current RecoveryWorks external-validation plan is `HUMAN_APPROVAL_REQUIRED`. It requires `CUSTOMER_COMMUNICATION` approval, an execution-time private target reference, and grants:

- autonomous cash spend: 0;
- autonomous model calls: 0;
- autonomous external messages: 0;
- autonomous downstream writes: 0.

The engine does not draft or send outreach, choose a contact, deploy software, move money, submit claims, or perform any other ACT.

StarBlox and ABVM external-validation plans inherit `CONSEQUENTIAL_CHILD_FACING_CHANGE` approval requirements. Market-surveillance research inherits `NO_AUTONOMOUS_TRADING` and `NO_BROKER_ORDER_EXECUTION`.

## Outcomes

The checked-in outcome ledger starts empty because a plan is not an outcome.

Definitive `PASSED` or `FAILED` results require:

1. `evidence_state = VERIFIED`;
2. durable evidence and event IDs;
3. an independent verifier distinct from the experiment actor.

Missing/ambiguous evidence stays `INCONCLUSIVE`. The experiment engine does not force binary answers from silence or unavailable evidence.

## Runtime integration

Step 8 daily mode now builds the Step 11 uncertainty snapshot and then deterministically emits `experiment_plan.json`. It does not execute the plans.
