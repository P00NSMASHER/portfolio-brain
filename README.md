# Portfolio Brain

Autonomous portfolio intelligence control plane for PRJ-000.

**Status: OPERATIONAL.** Steps 0–25 are complete. Ordinary operation runs through GitHub automation and durable machine-readable state; interactive ChatGPT is not a runtime dependency.

The historical Steps 0–25 build ledger is distinct from the 2026-09-30 audit-remediation sequence tracked in issue #210. Current architecture facts are derived in `operations/ARCHITECTURE_STATUS.json` from the project registry, adapter registry, runtime policy, notification policy, and `governance/boundaries.json`; hosted gates and live receipts remain separate acceptance evidence.

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

`governance/boundaries.json` is deny-by-default and contains explicit per-project `READ_OBSERVE`, `CANDIDATE_PR`, `DEPLOY`, and `EXTERNAL_ACTION` capabilities. Observation never inherits Portfolio Brain write/deploy authority. The runtime project-forwarding layer is read-only; only PRJ-000 has protected candidate-PR capability there, and that is not merge authority.

Autonomous operation may use only narrowly bounded external actions explicitly granted by a separate machine policy, such as the existing action-engine email policy. Gmail/ChatGPT is not a core autonomy dependency and observation cannot grant email authority. Education-product validation is limited to verified adult stakeholders and cannot contact minors, collect child data, or make consequential child-facing changes. Payment/cash movement, financial actions, destructive actions, live trading or brokerage execution, meaningful-risk production deployment, secret changes, and unapproved consequential child-facing changes remain human-gated or prohibited. Protected bot repair integration remains subject to exact-head required checks and the independent verifier with no protection bypass.

Heartbeats are connectivity telemetry, notifications are alerts, and GitHub Pages is sanitized publication. None of those classes independently counts as technical, market, or revenue verification. The public command center exposes source freshness, sequence, state hash, and stale/blocked provenance instead of treating publication success as substantive work.

Because this repository is currently public, persistent state remains sanitized-only. Private customer/operational payloads, credentials, secrets and sensitive evidence bodies are not stored here.

## Evidence

- `PORTFOLIO_BUILD_STATE.json` — durable Steps 0–25 build/operating record.
- `operations/OPERATING_MODE_POLICY.json` — approved autonomous operating mode.
- `operations/OPERATING_MODE_STATUS.json` — historical Step 25 promotion/post-promotion verification evidence.
- `operations/ARCHITECTURE_STATUS.json` — current config-derived architecture status; not a substitute for hosted/live acceptance evidence.
- `governance/boundaries.json` — machine-tested portfolio/project authority matrix.
- `hostile/ATTACK_MATRIX.json` — Step 23 adversarial threat coverage.
- `canary/CANARY_CONTRACT.md` — Step 24 no-prompt canary contract.
- `.github/workflows/foundation-ci.yml` — deterministic full-chain validation.

## Owner-requested license workflow preference

`hunting/LICENSE_ADMISSION_POLICY.json` is the admission authority for **Brain-only license workflow decisions**. In `ADVISORY_OWNER_ASSUMED` mode, missing, copyleft, restricted, or custom license classifications do not block Hunter proposals, transfer planning, or shadow-challenger admission. Dedicated Hunter license-text fetches are skipped. The basis is recorded as `OPERATOR_ASSUMED`, not independently VERIFIED.

Source classifications, copyright notices, hashes, license text, and historical rights states are not rewritten. A legacy `UNKNOWN_REQUIRES_REVIEW` source state describes evidence, not the current license-admission setting. This preference does not verify third-party permission, change downstream repositories, allow unauthorized access, or bypass budget, security, source-integrity, independent-verification, factory, action, deployment, or promotion controls.

`ENFORCE` remains available by explicitly changing both `mode` and `license_based_blocking`; unknown or inconsistent settings fail validation. Deterministic synthetic controls run with `python -m hunting.validate_license_admission`.
