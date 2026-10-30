# Native final approval: review-only integration candidate

Status: NOT DEPLOYED; NO NATIVE WRITE AUTHORITY; PRODUCTION RELEASE HOLD.

## Purpose and current boundary

PR #729 binds the enrollment mutation to the initially reviewed head. PR #730's
monitor can detect subsequent drift but cannot prevent a platform merge that
finishes before the monitor runs. A check on the new head must not inherit an old
head's approval merely because its ordinary regression tests pass.

`verification/native_final_approval.py` provides a separately testable, read-only
approval verifier. It does not change or import the production check publisher,
controller, workflow, branch protection, permissions, credentials, or scheduling.
The existing required `portfolio-phase1-gate` does NOT yet call it. Its positive
result is deliberately `APPROVAL_MATCHED_NOT_ENFORCEMENT`, never release approval.

## Evidence contract

An enrollment ticket binds the repository ID and name, PR node ID and number,
head branch and commit, target main and base commit, accepted controller source,
independently deployed policy revision, and a ten-minute maximum validity window.
The ticket must be retained by trusted control-plane storage independently of
mutable PR labels, branch contents, and candidate-supplied data.

A self-computed fingerprint is NOT evidence. An authenticated original GitHub
GET must return a successful, exact-head `portfolio-native-admission` check from
App 5121826 whose `external_id` binds the entire ticket. The provider-assigned
check ID is excluded from the fingerprint to avoid an issuance circularity; it
is still validated against the ticket and canonical repository check URL.
Neither this check producer nor its ticket storage is installed by this change.
An existing generic `portfolio-phase1-gate` check cannot substitute for it.

The independent producer must first verify the original low-risk document blobs,
complete diff and ancestry, current source acceptance and no-bypass protection.
Only an independently governed producer may issue admission checks. Existing App
identity alone cannot authorize an unreviewed change to that producer.

The reader performs at most seven fixed-path GETs. It validates current PR,
protected main, exact independent approval, and a complete exact-head check
census including successful `validate` from App 15368. It then rereads main, PR,
and approval. It rejects missing/ambiguous checks, wrong issuers, source or policy
changes, removed opt-in, unproven enrollment, and expiry during provider reads.
It freezes the validated ticket before callbacks and applies a thirty-second
observation deadline. Provider errors are sanitized and never retried here.

The injected reader MUST be trusted-main code, authenticated to this repository,
response-size bounded, and must not forward credentials to redirects. Test
readers are synthetic fixtures, not live provider proof.

## Required deployment work -- intentionally NOT completed

1. Independently review and install the ticket issuer/store and final-check
   integration. Route EVERY previously enrolled PR lineage through this check,
   even after label removal, head changes, retries, or restart. No generic green
   fallback is permitted when approval is missing or does not match.
2. Preserve the issuer-pinned required final checks, strict up-to-date policy,
   no-bypass rules, and candidate/credential isolation. A producer or candidate
   must not approve its own verifier trust-anchor update.
3. Prove the platform's behavior for same-writer head replacement, retargeting,
   existing green checks, label removal, and approval revocation. Double reads,
   expiry, this helper, and asynchronous disablement do NOT freeze mutable
   metadata or guarantee revocation after a final success has been published.
4. Only after separately governed authorization, test one actual restricted-token
   native enrollment and its provider readback. Positive viewer eligibility is
   not successful mutation authority. Do not retry the earlier uncertain POST.
5. Any protected release still requires its own source-specific reliability
   acceptance. No historical acceptance is transferred to this candidate.

## Validation and provenance

The new 25-test suite uses synthetic original-provider shapes and performs no
network operations. A missing-implementation test failed before implementation.
An additional ticket-substitution regression failed before the input was frozen,
then passed after the repair. Positive cases verify only an approval match and
assert zero provider writes, no protected check issuance, and no merge authority.

Local compatibility runs also passed the 14 existing verifier tests and 36
existing controller tests on the available archived 7ad50146 source snapshot.
That archive is NOT the full current PR #730 tree; these local results are not
represented as exact-head hosted CI. Hosted evidence must be read separately
for the actual uploaded commit and its platform virtual-merge source.

The deployed verifier source inspected on protected main
`35ad71868f74e6d4f749a35630a1b86802b91ed0` has Git blob
`42c1ca7072fdb48f3cc96d03c00e2144e87a19ac`; it was not modified here.

GitHub's current documentation describes native auto-merge as waiting for
required reviews/checks and describes automatic disabling for changes by users
without write access. It is not evidence of immutable same-writer enrollment:
https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/automatically-merging-a-pull-request

GitHub requires status checks on the latest commit and supports strict
up-to-date enforcement; neither fact alone proves PR-specific approval storage:
https://docs.github.com/en/enterprise-cloud@latest/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks
