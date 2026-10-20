# Two-stage GitHub-native auto-merge admission (REVIEW ONLY)

Date: October 20, 2026
Protected production source: 35ad71868f74e6d4f749a35630a1b86802b91ed0
Status: isolated design and synthetic tests; no production controller release authority.

## Authenticated original provider evidence

The original controller insists on a CLEAN PR with BOTH exact-head protected checks already SUCCESS. GitHub then reports viewerCanEnableAutoMerge=false, because native auto-merge is unavailable when the PR may merge immediately. The previous uncertain native POST for PR #723 cannot safely be retried.

Original restricted-token read-only run:
https://github.com/P00NSMASHER/portfolio-brain/actions/runs/39470448907

It used contents:read plus pull-requests:write, the same production permissions:
- Non-draft PR #688: BEHIND, viewerCanEnableAutoMerge=true; one required status check missing.
- Non-draft PR #641: BEHIND, viewerCanEnableAutoMerge=true; one required status check missing.
- Non-draft PR #723: CLEAN, both required status checks SUCCESS, viewerCanEnableAutoMerge=false.
- Draft PR #729 and old clean PR #472: viewerCanEnableAutoMerge=false.

These observations prove provider VIEWER ELIGIBILITY on a blocked PR, not mutation authorization. BEHIND is explicitly unsafe for first admission under strict up-to-date protected checks; it may require another push.

GitHub's official docs state that enrollment is available while merging is blocked by incomplete requirements:
https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/automatically-merging-a-pull-request

A GitHub community report says actually executing the native GraphQL mutation can require both contents:write and pull-requests:write, but this is NOT verified for this repository, and it does NOT justify widening privileges:
https://github.com/orgs/community/discussions/24686

## Stage zero: existing immutable source safety

Keep accepted protected main SHA, repository identity 1387747549, source-bound six-hour acceptance receipt, active ruleset 24182301 with zero bypass actors and strict checks, both issuer identities, no unresolved review threads, trusted PR author, explicit opt-in label, source/branch ancestry, and exact Git tree and document blob comparison. No untrusted PR code checkout, external links, new secrets, network routes, labels or schedules.

Require same-repository non-draft PR, source-pinned main and base SHA, immutable head SHA, and only narrowly bounded regular UTF-8 Markdown under the existing low-risk allowlist. Re-read original evidence before any later enrollment boundary.

## Stage one: early PR admission before FINAL check completes

Only a strictly original-provider BLOCKED (not BEHIND, UNKNOWN, CLEAN or DIRTY), mergeable OPEN PR can qualify, and only when actual restricted principal returns viewerCanEnableAutoMerge=true.

Require precisely one of the two independent, issuer-pinned, exact-head required checks completed SUCCESS and the other genuinely QUEUED/IN_PROGRESS with null conclusion. Both final checks green is too late; both pending is insufficient; absent, duplicate, wrong-issuer, wrong-SHA, cancelled, skipped or failed checks hold. No temporary failed checks, fabricated review requirements, or protection relaxations are allowed. Re-read head/base SHA, policy, acceptance, label, required check states, review threads and actual viewer eligibility immediately before any future enrollment.

The pure function model in brain/v9/native_enrollment_plan.py illustrates admission classification ONLY. It receives simulated caller-supplied observations; these cannot confer authority. Its only positive return is REVIEW_ONLY_EARLY_ADMISSION_CANDIDATE with provider_writes=0 and merge_authorized=false. There is NO native mutation, production workflow or runnable enrollment. Live integration must rederive all evidence from original authenticated provider reads.

## Stage two: GitHub-enforced protected completion

A future separately authorized, reviewed trusted-main controller could attempt one SQUASH auto-merge enable operation while the other required check is still pending. Only after original GraphQL readback proves enrollment may it report native enrollment. GitHub, NOT the planner, must enforce BOTH independently issued final checks and strict up-to-date protected branch at merge.

The final GitHub merge (if any) requires independent original event, protected-main SHA, exact PR head and check-issuer verification, plus a separate governed release-acceptance decision. Network uncertainty is UNKNOWN_AFTER_POST, never success or a license to retry. Do not use REST direct merge as a substitute.

## Threat model and holds

- Same-author PR modifications after enrollment could invalidate the initially vetted document without GitHub automatically disabling auto-merge. A real rollout must address reliable revocation and source reapproval, not merely rely on earlier snapshot evidence.
- An external PR head, changed base, opt-in label revoked, stale acceptance, changed original ruleset or head, unresolved threads, nonzero bypass actor or ambiguous provider response fails closed.
- The current token may report viewer eligibility=true but still lack write authority for GraphQL auto-merge. A real native POST remains unproven. Do not increase scopes or re-POST on #723, #688 or #641.
- Any protected merge changes the accepted source SHA and requires a fresh source-specific six-hour reliability observation before new autonomous action.
- This model is NOT connected to production or deployed by its CI. It deliberately preserves protected main and its existing workflow.

## Before any live mutation

1. Exact-head Foundation CI and both issuer-pinned check results for this design branch.
2. Independent code/security review of the proposed two-stage read/write sequencing, including revocation, source-race and token privilege risks.
3. Real restricted-principal read-only probe on a fresh, current-base, non-draft BLOCKED documentation-only PR while one genuine required check is outstanding.
4. Separate owner/governance authorization for a single tightly bounded real mutation test; confirm no bypass, no new credential scope and no direct merge.
5. Separately reviewed production integration, new protected-main source-specific six-hour reliability acceptance, original artifacts/Cloudflare/SQLite replay.
6. Genuine native enrollment and GitHub protected merge proof for a docs canary before any engineering/deployment expansion.

Outcome: DESIGN_ONLY / ZERO_GITHUB_MUTATIONS / NO_AUTO_MERGE / NO_RELEASE_APPROVAL.
