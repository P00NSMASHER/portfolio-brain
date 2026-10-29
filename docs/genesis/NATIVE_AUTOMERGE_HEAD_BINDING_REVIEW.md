# Native enrollment exact-head binding and remaining release gates

October 20, 2026. Review-only extension of PR #729; not a production release or approval of the new source.

## Verified API contract

Original read-only GitHub Actions run 39499292186 used unchanged contents:read and pull-requests:write permissions and introspected EnablePullRequestAutoMergeInput. GitHub returned expectedHeadOid as the GitObjectID scalar. The probe performed no native mutation and does not prove permission to enable auto-merge.

Source: https://github.com/P00NSMASHER/portfolio-brain/actions/runs/39499292186
Official API: https://docs.github.com/en/graphql/reference/pulls#enablepullrequestautomergeinput

The original exact candidate source 7ad50146267e4ed573230537b1450ded5c245d96 was independently exported in artifact 12297754815. Original ZIP SHA256 a1510178e7b40967a01508cd63f2781f570d0b0fc8dfab986e4c109bf5561f37, CRC, inner archive digest, and controller Git blob identity were checked before local regression testing.

## Implemented safety correction

The native GraphQL request now supplies expectedHeadOid equal to the original admitted head, typed as GitObjectID!, and the transport rejects missing, malformed or extra mutation variables before network activity. This closes the missing request-side compare-and-set condition; the local test models a head changing after the final reads and verifies that the replacement cannot be enrolled by the modeled server.

After the response, enrollment readback must identify the same PR number, node ID, head, repository and target main branch. A still-open enrollment must also retain the accepted base SHA, opt-in label, non-draft state and unmerged state. Disagreement is uncertain POST evidence, never successful enrollment or permission to retry.

Explicit single provider rejection types FORBIDDEN, UNPROCESSABLE and NOT_FOUND are retained as fixed diagnostic codes without logging free-form messages. They remain AUTO_MERGE_ errors, so the existing runner stops with UNKNOWN_AFTER_POST and never silently retries or reports zero writes. A new diagnostic cannot reconstruct the discarded error from the earlier incident.

## Test scope

Twelve additional network-free tests exercise the actual controller and its native transport. Baseline: 36 existing tests passed. New missing-binding and changed-head tests failed on the original candidate, then passed after the patch. The total focused set is 48 tests plus policy-pin validation. Hosted whole-repository checks must independently pass at the new exact head before any release.

## What this does not solve

expectedHeadOid is an operation-bound condition, not a permanent branch lock. It must not be represented as preventing every later writer push, later base retarget, label removal, or source-policy change. A post-write readback detects disagreement after the operation; it cannot retroactively prevent an already-completed merge. Asynchronous disabling alone is not a sufficient final authorization gate.

Before early enrollment from PR #730 is activated, the platform-enforced final merge gate must be bound to independently authenticated approval of the exact PR/head/base and source policy, and revalidate changed heads even when their ordinary tests pass. An immutable head branch plus separately governed retarget protections is an alternative requiring explicit protection governance. Neither protection has been installed here.

The present required App check only verifies tests/current-main ancestry; it does not enforce a persisted enrollment-specific approval. Its verifier code and workflow are immutable trust anchors in the current independent verifier. Do not bypass that protection or silently edit the anchor to publish this feature. A separately governed anchor revision and its own acceptance are required for that route.

Actual positive native mutation permission remains unproven. No native write was attempted, no opt-in label restored, no PR merged, no verifier anchor or token scope changed. PR #730 and its owner/reviewer attestation remain on their original reviewed head. The existing CLEAN/all-green admission policy is unchanged by this safety patch; two-stage enrollment is not activated.
