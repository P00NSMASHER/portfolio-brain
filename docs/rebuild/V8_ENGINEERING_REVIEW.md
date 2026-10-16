# V8 engineering review and evidence

Base: e6a218920b88a30b6004a13f54099ab0aa8e3bb5.
Reviewed source:3db12c943cc1285c0097acc608ceb9626f1d5c60.
One fresh read-only reviewer examined the complete integration, plan and spec.
No Critical findings; three Important findings. All three were reproduced before
correction and fixed in one pass, without a second reviewer/self-approval claim.

| Finding | Reproducing control and correction |
|---|---|
| An UNKNOWN provider write did not reserve its task against another already-staged operation | Delayed apply and rollback regressions failed before; persisted unresolved intents now exclude other operations on the same task across restart |
| A recent manual or unrelated same-name workflow could refresh automatic health | Manual-only, old-scheduled-plus-manual, wrong workflow path and wrong branch controls failed before; exact workflow/main/repository and native schedule are required for automatic freshness, dispatch provenance remains unknown |
| Supported incompressible8MiB chunks exceeded4MB JSON bound | Real-size deterministic random chunk with wrapped base64 failed before; bounded response ceiling now accounts for supported compressed bytes, base64 and escaped line wrapping |

Final focused review suite:35 tests PASS. Full integrated suite:2019 tests PASS,
2 explicit platform skips, exit0,55.255seconds. The earlier pre-review full suite
ran2015 tests PASS/2 skips. Six prerequisite source diffs preserve original-head
provenance in separate commits. Published trees must match the tested local trees.
Original draft/CI failures and #699 remain historical adverse evidence.

## Rulings and practical limits

- Exact reviewed diffs were integrated separately because shallow history could
  not octopus-merge every candidate. Cost if wrong: semantic integration defect;
  combined regressions and independent checks are required, not presumed parity.
- Configured owner roles are not authenticated task/runtime identities. Require
  fresh original ownership/capability evidence before action. Cost: delayed
  delivery where ownership cannot be established.
- V8 diagnostics are optional beside the established canonical core. A failed
  optional step remains failed/missing v8 evidence even if the core succeeds.
  Cost: engineering routing can be unavailable without stopping state recovery.
- Reviewer declined to certify real provider ownership, private persistent volume,
  unattended execution, deployed journeys, current-source six-hour acceptance or
  release eligibility from code. These remain explicit unverified gates; no
  fixture, local file or declared role grants those capabilities. Cost: the ten
  upgrade areas cannot be called production-complete until original evidence
  proves them. This is a deliberate safety boundary, not a passed gate.

No deferred Minor findings were reported. No paid integration, privilege change,
new schedule, production-state rewrite or unsupported task API was introduced.
