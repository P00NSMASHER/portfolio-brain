# Portfolio Brain cross-path source admission and authorized verifier cutover

**Status: review-only draft PR #804; NOT deployed.** Issue #795 is still OPEN and historical issue #796 remains untouched.

## Verified root cause

Protected GitHub ruleset 24182301 has zero bypass actors and two required issuer-pinned checks: `validate` (GitHub Actions App15368) and `portfolio-phase1-gate` (App5121826). The deployed second verifier currently checks immutable trust anchors and tests, but *not* accepted predecessor source. The optional v9 auto-merge controller checks predecessor acceptance only in its special docs-only path. Therefore manual GitHub UI/API PR merges can pass the required rules while failing the separate app-specific source acceptance contract.

The deployed verifier rejects candidates changing `verification/independent_verifier.py`; that behavior is correct and must not be bypassed with a forged green status, direct protected update, forced Git push, or unilateral ruleset weakening. PR #804's genuine App5121826 check is currently red for that exact reason.

## Correct canonical receipt proof

The canonical active receipt producer **does NOT** use legacy `brain-acceptance-<sha8>-YYYYMMDD`. It creates `auto-repair/pb-01-acceptance-receipt-<sha8>-YYYYMMDD`, a single-child branch and an open non-mergeable-as-certification PR with one `acceptance/finish-soak-<sha8>-YYYYMMDD.json` file. The independent source-acceptance verifier reads original GitHub cycles, signed Cloudflare provenance, state, SQLite, terminal follow-through and artifacts, then posts App5121826 `portfolio-source-acceptance` on the exact receipt head with `external_id=source-acceptance:<main_sha>:<sha256(exact_receipt_bytes)>`.

PR #804 uses that **canonical** branch and independently issued check. It validates exact source, one child, one added file, raw Git blob hash, strict receipt schema, 43,200 completed seconds, gap at most 5,400s, required 30-minute follow-through, source/SQLite/ledger invariants, positive signed origin and the unique issuer-pinned receipt-hash binding. A prior source, a simulated receipt, 6-hour evidence, wrong App, duplicate check, wrong SHA, incomplete provider census or absent ref all FAIL CLOSED. It does not replay original cycles itself: it relies on the separately credentialed App's original full replay.

## Observation activation deadlock fixed in candidate, still OFF in production

The current main workflows retain literal `false &&`. Within PR #804 only, both observers replace the literal hold with an additional new, exact-source opt-in: `vars.PORTFOLIO_12H_AUTHORIZED_SOURCE_SHA == github.sha`, **in addition** to existing `vars.PORTFOLIO_12H_OBSERVATION_ENABLED == 'true'`. Current main and the candidate are different SHAs; no value is set by this PR. No 12-hour workflow is started or enabled.

After a genuine protected cutover, the user can explicitly approve starting the observation by setting **both** GitHub repository variables, with `PORTFOLIO_12H_AUTHORIZED_SOURCE_SHA` equal to the *then-current protected main full SHA*. A source change automatically invalidates that authorization. Never set these variables before the user's separate explicit approval. Observation must still genuinely pass the original 12h time/gap/follow-through and separate App acceptance requirements.

This ordering avoids needing another PR *after* source acceptance has been made mandatory, which would otherwise create a circular deadlock.

## Required protected trust-root bootstrap

This PR alters an anchor protected by the existing verifier, so Foundation success and simulations alone will never satisfy the currently required App5121826 gate. The owner has explicitly authorized the trust-anchor upgrade but not a downgrade of issuer guarantees. Safe installation requires an **independently signed, equivalent-or-stronger bootstrap gate** deployed and audited via a separate protected PR that does **not** edit the old anchor. An administrator then atomically configures the protected ruleset to require the temporary independently signed bootstrap check from App5121826 alongside the original Foundation check, verifying no protected PR other than the exact reviewed upgrade head can pass. The old normal gate cannot be taken out before this alternate protection is proven live and required. After exact-head protected release, restore the normal App5121826 `portfolio-phase1-gate` requirement and verify a real negative test. Never add a bypass actor or allow a time interval with only an unverified check.

GitHub's connected app has no ruleset-write endpoint. The available connected browser tool reported insufficient credits and performed no admin action. Do not claim server-side enforcement or merge #804 until the required admin-controlled trusted-root bootstrap is genuinely completed, original check issuers verified, and the two-flag observation hold audited.

## Required final evidence before closing #795

1. Exact-head Foundation App15368 and *authentic* independent issuer-pinned bootstrap App5121826 success with reviewed trust-root hash and app identity.
2. Original protected GitHub merge on the candidate head; no forced updates, admin bypass, or fabricated statuses.
3. Original postmerge Foundation and production core cycle successes, verified state publication and ancestry.
4. The two-variable observer jobs remain **skipped** after merge until the explicit authorization that sets both variables for the new source.
5. A real manual/REST PR against unaccepted protected main is blocked by the independent App gate; forged/old-source receipt or missing App check fails.
6. Zero unrelated open PRs after resolving them through their own independent green checks.
7. Keep original #794, #796 and all historical failure artifacts immutable. No retroactive PASS.

**Decision until all originals are available: NOT DEPLOYED, NO-GO FOR GOVERNANCE CERTIFICATION.**
