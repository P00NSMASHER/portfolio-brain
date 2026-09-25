# Portfolio Brain

Autonomous portfolio intelligence control plane for PRJ-000.

**Status: OPERATIONAL.** Steps 0–25 are complete. Ordinary operation runs through GitHub automation and durable machine-readable state; interactive ChatGPT is not a runtime dependency.

## Operating mode

Portfolio Brain can autonomously:

- observe registered repositories through bounded read-only adapters;
- rebuild deterministic learning, uncertainty, experiment and allocation state;
- run bounded public Hunter searches;
- select evidence-gated work with duplicate/lease suppression;
- enforce cost, retry and kill-switch limits; and
- produce deduplicated evidence-gated notifications.

The checked-in paid/model/API budget remains zero and no non-Tier-0 model is enabled.

## Permanent authority boundaries

Autonomous operation does **not** grant customer communication, payment/cash movement, live trading or brokerage execution, deployment, merge authority, secret changes, or unapproved consequential child-facing changes. Those remain human-gated or prohibited.

Because this repository is currently public, persistent state remains sanitized-only. Private customer/operational payloads, credentials, secrets and sensitive evidence bodies are not stored here.

## Evidence

- `PORTFOLIO_BUILD_STATE.json` — durable Steps 0–25 build/operating record.
- `operations/OPERATING_MODE_POLICY.json` — approved autonomous operating mode.
- `operations/OPERATING_MODE_STATUS.json` — post-promotion verification evidence.
- `hostile/ATTACK_MATRIX.json` — Step 23 adversarial threat coverage.
- `canary/CANARY_CONTRACT.md` — Step 24 no-prompt canary contract.
- `.github/workflows/foundation-ci.yml` — deterministic full-chain validation.
