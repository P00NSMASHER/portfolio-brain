# Portfolio Brain

Autonomous portfolio intelligence control plane for PRJ-000.

**Status: OPERATIONAL CORE.** `PORTFOLIO_BUILD_STATE.json` preserves the historical Steps 0–25 build baseline. Current remediation acceptance is tracked separately in GitHub issue #210 and is not inferred from this README. Ordinary operation runs through GitHub automation and durable machine-readable state; neither interactive ChatGPT nor Gmail is a core runtime dependency.

## Operating mode

Portfolio Brain can autonomously:

- observe registered repositories through bounded read-only adapters;
- forward a repository observation to exactly one explicitly routed project without inheriting write/deploy authority;
- admit a bounded, deduplicated REPO-001 scout candidate into the existing Hunter research logic;
- observe ABVM repository automation health/progress without child-facing mutation, deployment, or school-content publication authority;
- rebuild deterministic learning, uncertainty, experiment and allocation state;
- run bounded public Hunter searches;
- select evidence-gated work with duplicate/lease suppression;
- enforce cost, retry and kill-switch limits; and
- produce deduplicated evidence-gated notifications.

Paid model execution is enabled for governed OpenAI Luna, Terra, and Sol routes. The checked-in portfolio ceiling is $10, 40 model calls, and 80 API calls per UTC day; PRJ-000 has a $5 project ceiling. Individual calls still require an eligible route, a credential, a pre-execution reservation, and a valid usage receipt. A successful workflow run alone does not establish that useful work occurred.

## Permanent authority boundaries

Project authority is deny-by-default and project-scoped by `governance/boundaries.json`; no downstream project inherits PRJ-000 privileges. Customer communication through Gmail requires an explicit per-request human approval reference and is optional transport, not core autonomy. Education/ABVM observation is health/progress only and cannot contact minors, collect child data, mutate child-facing state, deploy, or publish school content. Payment/cash movement, destructive actions, production deployment, and consequential child-facing actions remain human-gated; live trading and brokerage execution remain prohibited. Protected bot repair integration is limited to the existing PRJ-000 ruleset path after exact-head `validate` and the independent verifier App 5121826 check both succeed, with no bypass.

Because this repository is currently public, persistent state remains sanitized-only. Private customer/operational payloads, credentials, secrets and sensitive evidence bodies are not stored here.

Heartbeat means liveness/connectivity only. Notifications are alerts only. GitHub Pages is sanitized publication only. None of those signals creates technical, market, or revenue verification. The command center exposes source freshness, sequence, state hash, and stale/blocked state so a published page cannot silently turn stale evidence green.

## Evidence

- `PORTFOLIO_BUILD_STATE.json` — durable Steps 0–25 build/operating record.
- `operations/OPERATING_MODE_POLICY.json` — approved autonomous operating mode.
- `operations/OPERATING_MODE_STATUS.json` — historical post-promotion verification evidence plus current connector-policy annotation.
- `governance/boundaries.json` — machine-tested per-project capability and consequential-action matrix.
- `governance/STATUS.json` — generated/validated current configuration summary; acceptance proof remains tracked in issue #210.
- `.github/workflows/governance-remediation-controlled-proof.yml` — read-only controlled/live proof for exact-once forwarding, REPO-001 intake, and ABVM constraints.
- `hostile/ATTACK_MATRIX.json` — Step 23 adversarial threat coverage.
- `canary/CANARY_CONTRACT.md` — Step 24 no-prompt canary contract.
- `.github/workflows/foundation-ci.yml` — deterministic full-chain validation.

## Owner-requested license workflow preference

`hunting/LICENSE_ADMISSION_POLICY.json` is the admission authority for **Brain-only license workflow decisions**. In `ADVISORY_OWNER_ASSUMED` mode, missing, copyleft, restricted, or custom license classifications do not block Hunter proposals, transfer planning, or shadow-challenger admission. Dedicated Hunter license-text fetches are skipped. The basis is recorded as `OPERATOR_ASSUMED`, not independently VERIFIED.

Source classifications, copyright notices, hashes, license text, and historical rights states are not rewritten. A legacy `UNKNOWN_REQUIRES_REVIEW` source state describes evidence, not the current license-admission setting. This preference does not verify third-party permission, change downstream repositories, allow unauthorized access, or bypass budget, security, source-integrity, independent-verification, factory, action, deployment, or promotion controls.

`ENFORCE` remains available by explicitly changing both `mode` and `license_based_blocking`; unknown or inconsistent settings fail validation. Deterministic synthetic controls run with `python -m hunting.validate_license_admission`.
