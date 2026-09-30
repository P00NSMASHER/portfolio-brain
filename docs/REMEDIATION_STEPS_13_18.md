# Remediation Steps 13–18 — Current Contract

This document describes the current implementation contract. It does not mark GitHub issue #210 complete by itself.

- **Step 13:** `adapters/project_forwarder.py` routes a validated repository observation to one explicit project and suppresses the same forwarding identity on replay.
- **Step 14:** `hunting/repo_scout_intake.py` admits at most one eligible REPO-001 scout candidate per cycle, dedupes on source repository revision plus deterministic finding identity, and reuses the existing Hunter inspection/classification/ranking/proposal functions.
- **Step 15:** `adapters/abvm_observer.py` emits PRJ-006 automation health/progress evidence only and exposes no child-facing mutation, deployment, or school-content publication authority.
- **Step 16:** heartbeat, notification, and Pages semantics carry no technical/market/revenue verification credit; the command center surfaces source age, sequence, hash, and stale/blocked state.
- **Step 17:** `governance/boundaries.json` is the deny-by-default authority matrix. Customer communication/Gmail, financial, destructive, production, and child-facing actions are human-gated; live trading is prohibited; Gmail/interactive ChatGPT are not core autonomy dependencies.
- **Step 18:** README, architecture contract, and generated `governance/STATUS.json` describe the current machine policy without rewriting historical receipts.

Acceptance remains external to prose: deterministic Foundation CI, the hosted App 5121826 gate, and the controlled/live proof workflow are required before issue #210 may be marked complete.
