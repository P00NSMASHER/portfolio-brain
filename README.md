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

Paid model execution is enabled for governed OpenAI Luna, Terra, and Sol routes. The checked-in portfolio ceiling is $10, 40 model calls, and 80 API calls per UTC day; PRJ-000 has a $5 project ceiling. Individual calls still require an eligible route, a credential, a pre-execution reservation, and a valid usage receipt. A successful workflow run alone does not establish that useful work occurred.

## Permanent authority boundaries

Autonomous operation allows only narrowly bounded customer email through the action-engine policy. Education-product validation is limited to verified adult stakeholders and cannot contact minors, collect child data, or make consequential child-facing changes. Payment/cash movement, live trading or brokerage execution, deployment, merge authority, secret changes, and unapproved consequential child-facing changes remain human-gated or prohibited.

Because this repository is currently public, persistent state remains sanitized-only. Private customer/operational payloads, credentials, secrets and sensitive evidence bodies are not stored here.

## Evidence

- `PORTFOLIO_BUILD_STATE.json` — durable Steps 0–25 build/operating record.
- `operations/OPERATING_MODE_POLICY.json` — approved autonomous operating mode.
- `operations/OPERATING_MODE_STATUS.json` — post-promotion verification evidence.
- `hostile/ATTACK_MATRIX.json` — Step 23 adversarial threat coverage.
- `canary/CANARY_CONTRACT.md` — Step 24 no-prompt canary contract.
- `.github/workflows/foundation-ci.yml` — deterministic full-chain validation.

## Owner-requested license workflow preference

`hunting/LICENSE_ADMISSION_POLICY.json` is the admission authority for **Brain-only license workflow decisions**. In `ADVISORY_OWNER_ASSUMED` mode, missing, copyleft, restricted, or custom license classifications do not block Hunter proposals, transfer planning, or shadow-challenger admission. Dedicated Hunter license-text fetches are skipped. The basis is recorded as `OPERATOR_ASSUMED`, not independently VERIFIED.

Source classifications, copyright notices, hashes, license text, and historical rights states are not rewritten. A legacy `UNKNOWN_REQUIRES_REVIEW` source state describes evidence, not the current license-admission setting. This preference does not verify third-party permission, change downstream repositories, allow unauthorized access, or bypass budget, security, source-integrity, independent-verification, factory, action, deployment, or promotion controls.

`ENFORCE` remains available by explicitly changing both `mode` and `license_based_blocking`; unknown or inconsistent settings fail validation. Deterministic synthetic controls run with `python -m hunting.validate_license_admission`.
