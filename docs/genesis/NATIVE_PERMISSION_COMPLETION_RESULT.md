# Native permission completion test: actual provider denial

Observed October 20, 2026, 8:54 PM America/New_York (October 21 00:54 UTC).

- Original probe run: 39523869868; job: 118973870341.
- Probe source: adac606c99957f865ef0263e5b754dff0c03d5db.
- Documentation-only canary: PR 733, head 6ebe7d1523c96c2752ae7608ca662dc1c9192b7f.
- Protected main: 35ad71868f74e6d4f749a35630a1b86802b91ed0.
- Actual token permissions: contents:read, pull-requests:write, metadata:read.
- Exact document and ancestry verified; original main protections remained active.
- The PR was genuinely BLOCKED, viewerCanEnableAutoMerge=true, validate/App15368
  SUCCESS, independent final portfolio-phase1-gate/App5121826 not yet issued.
- An intent artifact was successfully uploaded before one expectedHeadOid-bound
  SQUASH enablePullRequestAutoMerge mutation.
- Actual result: NATIVE_POST_REJECTED_FORBIDDEN.
- attempted_native_posts=1; readback_same_head=true; rest_enrolled=false;
  rest_merged=false. No retry or alternate credential was used.
- Canary PR was returned to draft. No protected main update or deployment.

Original provider evidence:
https://github.com/P00NSMASHER/portfolio-brain/actions/runs/39523869868

Intent artifact 12311903979:
sha256:39ac817960782e377f3f0f85cc1a7ff4fc200348f1974b44cfefc59a25a5019d

Result artifact 12311873980:
sha256:11f94665272e6384e1ea90c650f8fa20cb34c08dc2fce85865a85cfac20e203b

The artifact metadata/digests were independently read back; this session did not
independently download or hash the ZIP bytes. Artifacts expire after 30 days.
The original log retained the sanitized provider rejection type; it did not
expose a token or claim that one specific permission change is proven sufficient.

Positive viewer eligibility is therefore not mutation authority. A separately
authorized credential/permission decision is required; permissions were not
expanded. General durable approval storage and final-check deployment remain
unfinished. The probe's intent artifact is not a general production ledger.

The one-shot workflow is removed from this branch after the test. The original
run and source commit remain available for audit; never rearm or retry it.
