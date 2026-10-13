# V7 Candidate: Evidence-gated decision queue (review only)

**Status: DRAFT / NOT DEPLOYED / NOT A V6 SOURCE REVISION.** This is a
small, intentionally read-only product-quality improvement, evaluated on a
branch forked from exact accepted-in-progress V6 production source
`f39a8b2ad88b6e1f0db246b586c89a9d611a566c`.

## Why this is the next improvement

The first genuinely scheduled V6 core's original complete report contained
**77 structurally inspected code candidates**, **10 generic business opportunity
hypotheses**, and **zero recorded feedback outcomes**. The prior report layout
listed candidates mainly by structural score, allowing x402-related sources to
crowd out freight-recovery and school-tools evaluation.

This pilot adds an evidence-sensitive *human review shortlist* in the existing
private `report.md` and `report.html`, without asserting commercial value.
It helps distinguish a directly observed check deterioration from a merely
changed issue tally and from a public code sample worth independent evaluation.

## Hard gates and ordering

- Only a genuine canonical report with `status=PASS`,
  `schema_version=2` and an exact source SHA yields proposals. Other reports
  and failure views contain no action shortlist.
- An **actual/fresh** comparison with a uniquely observed completed adverse
  check can prompt `INVESTIGATE_CHECK_CHANGE`. This does not establish root
  cause, financial harm or a safe fix.
- An observation labeled `NON_ACTUAL`, `HISTORICAL` or
  `ACTUAL_STALE_BASELINE` cannot become a recent production incident, even
  when its change types mention a check failure. It becomes an explicitly
  blocked `REVALIDATE_EVIDENCE` proposal.
- Fresh observed revision changes, check recoveries and issue/PR count deltas
  are lower-priority *review prompts*, not incident diagnoses or completed
  improvements. GitHub open-issues counts include pull requests.
- Public code candidates require `ACTUAL`, `CURRENT`, an exact content
  hash and observed related test paths. They remain **unexecuted** external
  sources. Any attached license label is metadata, not legal permission.
  Operator-reported `NOT_USEFUL` or `INTEGRATED` candidates are omitted from
  new proposals, without treating operator feedback as independently audited.
- Candidates are deterministically sorted within each target by their existing
  **structural** score, then selected **round-robin across target projects**,
  maximum two per target and six total. A target with no eligible observations
  does not receive invented proposals.
- Ten proposals maximum. Ordering is an explicit *review convention*, not a
  probabilistic risk score, prediction of ROI, verified demand, or time saved.
  A repeated validated input produces the same proposal IDs, order, evidence
  links and immutable source-qualified references.

## Where the data goes and what never happens

The queue is a **pure derived projection** of the canonical report, created
locally by `brain.triage.decision_queue(report)`. Only the private human-readable
Markdown and escaped HTML gain a section. The original canonical `report.json`
bytes, `Store.report` and `Store.read_report` replay, event/ledger SQL,
provider requests, state branch, research budgets and acceptance artifacts
are unchanged. There is no new workflow, GitHub cron, scheduled ChatGPT task,
API query, third-party code execution, automatic PR, email, integration,
trading permission, or paid call. All suggestions explicitly require a human.

The source data remain necessary context for any review. When a candidate has
an unknown license or feedback of uncertain provenance, investigate it before
considering reuse. Do not interpret this module as validating any copyright
or third-party access claim.

## Tests and release boundary

`tests/test_brain_triage.py` covers stale/nonactual evidence precedence,
actual fresh failure priority, invalid source failures, bounded cross-target
diversity, operator-feedback suppression, unknown-license caveats,
repeatability under reordered provider results, failure views and exact
canonical JSON preservation after Markdown/HTML rendering.

An integrated candidate is not accepted until its **exact final SHA** passes
Foundation App15368 and independent App5121826 reviews on the combined head.
Do not merge while the current V6 source-specific six-hour automatic
acceptance is being measured. A future V7 protected merge creates a **new**
source SHA and requires a distinct operator authorization, state migration
review and source-specific acceptance. Historical V6 automatic runs and V5
receipts cannot certify V7.
