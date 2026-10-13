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

### Explicit per-source licensing gate in the review display

The verified original V6 snapshot tested against V7 emitted **five** code
reviews. Three of those five had `UNKNOWN` license metadata (freight-recovery
and two school-tool examples), while two agent-product examples said `MIT`.
These labels come from source metadata and are **not** independent license
verification or reuse authorization. Previously the private Markdown/HTML
preview displayed only the **first** generic limitation, leaving the specific
permission caveat hidden from a reviewer reading just the human report.

For every code-review row V7 now exposes its exact declared license metadata,
a deterministic `license_review_status` and
`source_reuse_permission_confirmed=false`. Both inconclusive labels
(`UNKNOWN`, `NOASSERTION`, `NONE`, `UNLICENSED`) and declared SPDX-like
labels require independent rights review before use. Inconclusive metadata
is explicitly called out; a declared `MIT` string does **not** mean license
conditions, attribution, owner authority or code provenance were checked.
All of each item's limitations are included in the human Markdown/HTML.
Text originating in source metadata remains escaped; the canonical
machine-readable `report.json` is byte-for-byte identical to its input.

This is a **visibility and review-safety improvement**, not an admission
filter, a license verifier, a legal opinion, a newly measured business result
or permission to ingest restricted repository content. The five source
recommendations, their target balancing and original structural scores
are unchanged. Only the V7 derived review metadata and private human
presentation are extended.

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

## Bounded non-UTF-8 source quarantine (V7 research resilience)

The October 13 signed V6 monitor/research run [#38454048750](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/38454048750) stopped its **research** stage with a `UnicodeDecodeError` while reading a third-party blob. A source file's `.py`, `.ts` or similar extension alone does **not** prove that its bytes are valid UTF-8 program text.

In this V7-only draft, source discovery still retrieves the **exact original
Git blob**, verifies the original Git object SHA-1 and declared byte length,
and strictly decodes UTF-8. If those genuine, hash-verified bytes are not
valid UTF-8, the hit is classified as
`SEARCH_RESULT_NON_UTF8_BLOB_NOT_INSPECTED`. No replacement characters,
guessed charset, rewritten source, fabricated hash or code-reuse credit
are introduced.

Only an **optional, public, search-derived** hit can be quarantined.
Discovery continues within its existing two-result/24-GET upper bounds and
records the skipped source as explicit missing research evidence. A distinct
fully verified second source is needed before research may report a partial
successful observation. If every returned source is unreadable, the run
fails with `DISCOVERY_ALL_SEARCH_RESULTS_UNAVAILABLE` rather than claiming
there were no relevant sources or closing a production acceptance gate.
**Explicitly requested sources, private lookups, wrong blob hashes, access
denials and network/global failures remain fatal.** A provider-supplied error
that merely says `SOURCE_BLOB_NOT_UTF8` cannot impersonate the internal
post-hash decoding finding.

The change affects only the unmerged candidate, not the original V6
production workflow or its signed acceptance process. No new scheduler,
external calls, retries, credits, write authority, third-party execution,
trading or spending is introduced. These are research-availability facts,
not an assurance that a discovered source is licensed, correct or useful.

## Exact immutable third-party code references and safe rendering

V7 source review is now limited to an original, exact GitHub blob URL that
matches the canonical candidate's repository, complete commit revision and
literal code path. The stable repository:path key must also match.
Unrelated GitHub pages, altered revisions, encoded traversal, query/fragment
suffixes and lookalike hosts are excluded from review proposals. Other
independently valid proposals remain reviewable after a malformed candidate.

Exact link identity is **not** code testing, license permission, security
verification or validated business value. The review proposal explicitly
records those distinctions. The older private Markdown/HTML reusable-code
list uses the same immutable link validator, escapes user/provider metadata
and counts unsafe links it omits rather than rendering a deceptive hyperlink.

The original machine receipt and optional names-free public sidecar remain
unchanged. No code execution, network reads, additional schedules,
downstream repair, spending, trading or production promotion was introduced.
