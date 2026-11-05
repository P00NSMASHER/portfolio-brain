# Original-provider owner-work stage reconciliation (one scoped positive control)

**Case enrolled:** the original Portfolio Brain owner observation
`938e4a2975ef04adbdf95c78b15aa701bbdb9917940d8a4f4aa2997bc5ab9cc9`
on protected source `b333d9685373a51ee8e567a4d0768950660bcc29`,
owner `brain-engineering`, was recorded as `OBSERVED` in original core
42108594544. The verified technical defect concerned missing-monitor
unverified-result accounting, repaired under [PR #871](https://github.com/P00NSMASHER/portfolio-brain/pull/871).

The reviewed exact candidate head `892349571e16d26fc7cc59f336003ec1a7303b42`
received both original GitHub checks `validate` (App 15368) and
`portfolio-phase1-gate` (App 5121826), and merged via the protected
GitHub PR #871 process into commit
`7e4f483c8595437342d510bcfdca9f4fbfb5660b` whose immutable
first parent matches the original observed source.

The **existing** Brain core (no new workflow or credential) is allowed to
spend at most three unreserved GitHub GETs to independently re-read the
original PR, merge ancestry and exact-head checks. Only the one explicit
historical work item may be claimed and moved sequentially through
`DIAGNOSED → PATCHED → TESTED`, each transition bearing a digest of
the original provider facts. The queue still enforces owner claims, lease
fencing, immutable journal replay, and source identity. A missing provider
receipt/budget or a conflicting work identity makes no transition. Once
tested, no further provider calls are spent on this item.

This **does not** claim a live behavior replay, automatic deployment,
client value, earned income, or promote the item to `LIVE_VERIFIED`.
The separate original result dashboard records stages from a genuine
successful core artifact; it never converts green CI or a queued item into
an operational outcome.

This is a narrowly enrolled positive control proving the owner-work
handoff can progress from a real reviewed fix. Other observed items remain
unverified until individually matched to original release evidence.
