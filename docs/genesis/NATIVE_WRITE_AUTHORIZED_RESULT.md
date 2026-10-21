# Owner-authorized native enrollment: confirmed

Observed October 20, 2026, 9:28 PM America/New_York (October 21 01:28 UTC).

Owner explicitly authorized contents:write only for the guarded merge job,
retaining all existing branch protections and required checks. This run applied
that new grant only to isolated job guarded-enrollment; workflow defaults stayed
contents:read. No permanent production workflow permission was changed here.

Original run: 39527279455; job: 118984791182.
Probe source: 278a9a714a29be3e0a008972d7c4b584cbed2567.
Fresh docs-only canary: PR 734.
Exact canary head: 4b874598aa00815c0fa0e63ec4a7159892654b01.
Original protected base: 35ad71868f74e6d4f749a35630a1b86802b91ed0.

Original runner log confirms Contents: write, PullRequests: write, Metadata: read.
Ten offline regressions passed on PAAM-L044 and again in the GitHub-hosted job.
The original helper was verified against Git blob 041056175a90d67bb05550d3696021871d72b0ac.
The sole canary document was verified against blob 107eb06dacf94e402900d4f968cb7c5d1d4385fd.

At preparation, validate/App15368 was SUCCESS and the mandatory independent
portfolio-phase1-gate/App5121826 was not yet issued. The PR was genuinely BLOCKED;
strict main checks and the zero-bypass ruleset were checked before the request.
The intent upload completed at 01:28:43Z, before the expectedHeadOid-bound POST.

At 01:28:47Z the original one-shot result was:
NATIVE_ENROLLMENT_CONFIRMED; attempted_native_posts=1; readback_same_head=true;
rest_enrolled=true; rest_merged=false.

Independent original timeline event 33801629429 records auto_squash_enabled by
github-actions[bot] at 01:28:46Z. This proves native enrollment, not merely viewer
eligibility. Final protected merge must be corroborated separately; it was not
claimed in the initial enrollment readback.

Original provider sources:
https://github.com/P00NSMASHER/portfolio-brain/actions/runs/39527279455
https://github.com/P00NSMASHER/portfolio-brain/pull/734

Intent artifact 12313448471:
sha256:6f2018939f1eedde7f22f21f2776efd240aee7f01bf636a65397bb506f44e249
Result artifact 12312973703:
sha256:0550d41972ce033dba378d392ce1e10f696dc161b762b368faa0f44933c718bd
Artifact metadata and digests were read back. ZIP bytes were not independently
rehashed here. The artifacts retain evidence for 30 days; this record preserves
reported identities beyond their expiry.

The one-shot workflow is removed after successful enrollment. Do not rearm it.
The production controller, final-check issuer and general approval storage are
not activated by this canary. A protected merge changes main's source SHA, so
historical source acceptance must not be represented as acceptance of new main.
