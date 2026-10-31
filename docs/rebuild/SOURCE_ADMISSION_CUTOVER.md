# Source-admission gate cutover: protected draft, not deployed

**Scope:** Portfolio Brain governance issue [#795](https://github.com/P00NSMASHER/portfolio-brain/issues/795). This is a proposed, source-bound admission control for **every** ordinary GitHub PR merge route, not a reliability acceptance result.

## Observed defect

The existing protected `main` ruleset #24182301 requires two successful checks: `validate` (GitHub Actions App 15368) and `portfolio-phase1-gate` (independent App 5121826). It does **not** itself require an accepted predecessor source. The existing v9 `accepted_source()` check only applies to opt-in documentation-only native auto-merge enrollment, not owner/manual GitHub UI or REST merges. Historical PR #794 merged without the matching observed predecessor acceptance ref. That original event and every recorded failure remain immutable.

## Proposed fail-closed admission

The draft makes the trusted-main independent verifier require `verify_predecessor_acceptance(main_sha, read)` before publishing a successful **existing required** App5121826 `portfolio-phase1-gate` check. It reuses the reviewed `brain/v9/guarded_merge.py::accepted_source` proof: exact one-child receipt branch, valid one-file source-specific receipt, 43,200 completed seconds, 5,400-second gap cap, 30-minute terminal follow-through, correct Git ancestry/SQLite evidence and independent App5121826 receipt-hash attestation. Missing, ambiguous, forged, stale, wrong-source, unavailable-API or improperly issued evidence **denies** the check. It does not accept user comments, manual actions, synthetic local successes or successful 6-hour evidence as a substitute. The read-only adapter allows only five fixed GitHub route families, with a hard eight-read cap.

The verifier protects its own implementation, the read-only adapter and the underlying reviewed acceptance engine as immutable trust anchors. Any PR that modifies those anchors is blocked by the existing protected gate, rather than changing verification rules under candidate control.

## Known deployment and bootstrap blocker

This draft necessarily changes `verification/independent_verifier.py`, which the *currently deployed verifier* forbids any normal PR candidate from changing. Therefore **the candidate's independent App check must not be described as green or mergeable**. Do not bypass or remove that protection, fabricate an App check, force push, direct commit to protected main, or expand credentials. An owner-reviewed, independently governed *separate trust-root bootstrap* must be planned and explicitly authorized before installing this change. A green offline test suite or Foundation CI alone does not authorize merging.

A second ordering constraint: the current source has no completed 12-hour acceptance and the observation/receipt producer intentionally contain literal `false &&` user holds. Switching on unconditional predecessor admission immediately would block all later PRs, **including a PR to enable the observation**, until an authentic accepted source exists. The approved cutover must explicitly solve this sequencing without a fake acceptance, waiver based on a PR label, or an insecure exception for manual merges. A new protected source after any merge requires its own independent 12-hour acceptance.

## Negative tests required before final close

1. A same-repo PR with both normal CI tests passing, but **no** predecessor source acceptance, must be denied by App5121826 and cannot merge through GitHub UI, REST or automation.
2. A verified predecessor source must have valid original ZIP/CRC evidence, source SHA, valid acceptance commit ancestry and *independent* issuer-pinned source receipt. A wrong App, different source, stale 6-hour receipt or missing terminal follow-through must deny.
3. A PR modifying trusted verifier, acceptance engine, new adapter, ruleset or CI controls must not bypass this admission.
4. Re-run the existing no-bypass, strict issuer-pinned branch ruleset proof. Neither existing check may be removed or replaced.
5. Verify actual unmodified Cloudflare/GitHub automatic core cadence and exact-source durable state. Preserve issues #795 and #796 until independently evidenced resolution.

## Current operator restrictions

**Do not enable, start or backdate the 12-hour observation.** Both `.github/workflows/reliability-day.yml` and `.github/workflows/portfolio-source-acceptance-producer.yml` retain literal `false &&` plus `vars.PORTFOLIO_12H_OBSERVATION_ENABLED`. No credential, schedule, payment, production deployment or branch-ruleset changes are part of this draft. Final status: **cross-path enforcement designed and testable, not installed**; issue #795 remains open.
