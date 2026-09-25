# Persistent Portfolio Agents — Step 14

Ten stable roles are registered: Portfolio Manager, Hunter, Researcher, Product Analyst, Engineer, Tester, Auditor, Red Team, Data Steward and Commercial Analyst.

The control plane reuses the proven AI Business OS semantics for durable identity, explicit goal/work state, heartbeats, generation-based stale-lease fencing, append-only hash-chained events, snapshots and independent verification without copying the upstream runtime.

No role has ACT authority. Only Engineer is builder-eligible for candidate software modification and is capped at MODIFY. Portfolio Manager is the only Step 14 delegator, and delegation cannot exceed the target role's goal allowlist or autonomy ceiling.

Work follows `PENDING -> RUNNING -> VERIFYING -> COMPLETE|FAILED|BLOCKED`. Submission cannot complete work. Tester, Auditor, Red Team and Data Steward are verifier-eligible but not builder-eligible. Builder and verifier identities and independence groups must differ. Engineer is capped below Tier 3; Auditor and Red Team may request Tier 3 subject to the Step 13 router, whose checked-in Tier 1-3 providers remain disabled.

The runtime persists stable agent identities, work queues, lease/run identity, evidence references, output/report hashes, verification receipts, snapshots and an append-only SHA-256 event chain. Expired leases requeue work and fence stale generations. Snapshot restore changes operational state references without erasing historical events.

The checked-in seed contains 10 identities and no work/evidence. Private payload bytes remain outside this public repository. Customer communication, payments, billing/money movement, claims/legal communications, live trading/brokerage, destructive deletion, private-data disclosure and consequential child-facing ACT remain human-gated outside agent authority.
