# Portfolio Brain v2 acceptance record — 2026-10-07

The rebuilt core is **PRE-ARM PASS**, on one unchanged exact main commit
[`a0161341d823f9e8ed320c2cfb48b98184a5c4b7`](https://github.com/P00NSMASHER/portfolio-brain/commit/a0161341d823f9e8ed320c2cfb48b98184a5c4b7). It is not soak-accepted production and does not meet
the unlimited self-repair/never-needs-human guarantee. This branch stores evidence;
it does not change accepted main or schedule another run.

Merged engineering: [PR642](https://github.com/P00NSMASHER/portfolio-brain/pull/642), [PR643](https://github.com/P00NSMASHER/portfolio-brain/pull/643).
The first live attempt failed with403; its diagnosed cause and preserved artifact
are in `acceptance.json`. That failure is not hidden or relabelled. The accepted
source is the later exact main above, with all mandatory job steps successful.

- [Live accepted cycle](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/37693707713): real public source retrieval,
  code inspection, reports, labelled simulated experiment, doctor PASS, publication.
- [Exact-main Foundation](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/37693707584):1405 tests PASS in74.441s.
- Exact-main product preflight:36 tests PASS in0.718s; raw output in this branch.
- Published state [`3650ac2e613e7604df1321327f9a4e8cb3c7a887`](https://github.com/P00NSMASHER/portfolio-brain/commit/3650ac2e613e7604df1321327f9a4e8cb3c7a887):
  seven events, zero pending, canonical hash `4c18250a69b7d96d86b0c9972de39e35791ec34423f2a78145139c029cb9e414`.
- Downloaded artifact11515070237 matches SHA-256
  `afc411be814f64839d5f2678d045861fc36ce13c632b571dea0cd67ee6cfe8e7`; original ZIP preserved here permanently beyond
  the provider's30-day artifact retention. Independent replay of the remotely
  delivered SQLite matches the artifact doctor and its canonical report.

Hourly core runs at minute17. The existing autonomous reliability worker runs hourly
at minute30 with bounded evidence-based protected-PR repairs; its future repair
success is not established by updating its instructions. Bounded knowledge proposals
require three fresh actual implementation/test sources and at most one proposal
per week. This cycle returned `NO_CANDIDATE`; no actual self-upgrade merge is claimed.
Public source discovery has no license filter; private ingestion uses existing
authorized credentials into private local state only and has not been tested live.

## Useful demonstration

Four actual registered repositories were observed. Two public freight-invoice source
candidates were inspected at immutable revisions (MIT and UNKNOWN license labels).
They are ranked using structural evidence and not treated as production-ready.
The shipped simulated invoice experiment matched baseline results across1000 cases
(885 duplicates and two near misses), using1000 vs57877 defined operations. This
proves the bounded algorithm claim; revenue, demand and engineering savings remain
unmeasured. Read `reports/experiment/report.json` and the rendered summary for details.

## Reproduce without another hosted run

Use the accepted checkout and existing permitted read token if source APIs require it.
Never reuse another user's credentials or publish private inputs.

```bash
git clone https://github.com/P00NSMASHER/portfolio-brain.git
cd portfolio-brain
git checkout a0161341d823f9e8ed320c2cfb48b98184a5c4b7
python -m brain preflight --output brain-local/preflight --expected-sha a0161341d823f9e8ed320c2cfb48b98184a5c4b7
python -m brain init --db brain-local/demo.sqlite --output brain-local/bootstrap
python -m brain monitor --db brain-local/demo.sqlite --output brain-local/monitor --expected-sha a0161341d823f9e8ed320c2cfb48b98184a5c4b7
python -m brain research --db brain-local/demo.sqlite --output brain-local/research --expected-sha a0161341d823f9e8ed320c2cfb48b98184a5c4b7
python -m brain experiment --db brain-local/demo.sqlite --output brain-local/experiment --expected-sha a0161341d823f9e8ed320c2cfb48b98184a5c4b7
python -m brain doctor --db brain-local/demo.sqlite --output brain-local/doctor --expected-sha a0161341d823f9e8ed320c2cfb48b98184a5c4b7
```

Live data evolves and may fail or require existing API access; this command sequence
never fabricates the original snapshot. To reproduce its ledger deterministically,
fetch the recorded state commit, extract `state.sqlite`, use `Store(...,
visibility="PUBLIC").read_report(...)` and compare the canonical hash. Operational
doctor freshness deliberately expires after two hours; do not change the clock to
make historical acceptance look current.

## Documentation and preservation

[Architecture diagram/contracts](https://github.com/P00NSMASHER/portfolio-brain/blob/a0161341d823f9e8ed320c2cfb48b98184a5c4b7/docs/rebuild/ARCHITECTURE.md),
[removed-component inventory and forensic record](https://github.com/P00NSMASHER/portfolio-brain/blob/a0161341d823f9e8ed320c2cfb48b98184a5c4b7/docs/rebuild/FORENSICS.md),
[restart/recovery runbook](https://github.com/P00NSMASHER/portfolio-brain/blob/a0161341d823f9e8ed320c2cfb48b98184a5c4b7/docs/rebuild/OPERATIONS.md).
Forty old schedulers are byte-identical archives; old packages/ledgers are inert
historical fixtures. Both independent verifier trust anchors are unchanged.
Original Brain commitf0814f55fb5abf83135181d447171fb45d01933c and trading commit
6f7710512e6ac2f86e8cb12ad233a08980cf0220 are preserved with documented recovery refs;
trading implementation/data were not changed. No new purchases, accounts, paid
calls, credential changes, order execution or external deployment occurred.

## Complete requirement classification

This final matrix supersedes the before-integration matrix for this evidence point.
PASS applies to the stated scope only. BLOCKED requires an external dependency;
NOT TESTED establishes no completion. The failed unlimited autonomy requirement
remains explicit.

| Requirement | Status | Evidence or limit |
|---|---|---|
| Canonical repository and project interaction | PASS | Brain canonical; trading surveillance kept separate and untouched |
| Verified recovery point and historical evidence | PASS | Recorded original commits/trees, recovery refs, complete verified history bundle and byte-identical workflow archives |
| Product reassessment | PASS | Business research and engineering intelligence primary; market holdings optional; aspirations distinguished |
| Smaller active architecture | PASS | One recurring owner, stdlib modules, one SQLite authority; forty legacy schedulers archived |
| Durable transactional state and idempotency | PASS | Crash/concurrency/duplicate/gap/stale/tail-loss/replay regressions and independently verified delivered state |
| Freshness and no fabricated readiness | PASS | Exact-main preflight, semantic ages, workload continuation barriers, doctor, zero backlog and external delivery verification |
| Minimal automation and bounded cost/recovery | PASS | Hourly serialized owner, five-minute cap, bounded GETs/retries; no paid calls or credentials changed |
| Core portfolio repository monitoring | PASS | All four configured public projects observed in live accepted cycle |
| Actual code discovery and evidence ranking | PASS | Two exact-commit source blobs with verified hashes, test-path evidence and MIT/UNKNOWN license metadata; no license filter |
| Private repository discovery implementation | PASS | Existing-token scoped private local-state path plus deterministic privacy tests |
| Live private repository discovery | NOT TESTED | No private-source access demonstration or publication; existing hosted token has repository scope only |
| Durable analytical memory and bounded learning | PASS | Evidence and outcome ledger, deterministic reports, rotated searches and knowledge-file integration |
| Measured useful experiment | PASS | Simulated invoice tuple dedup: equal outputs on1000 cases,885 duplicates,two near misses;57877 vs1000 defined operations |
| Commercial demand, revenue and engineering time saved | NOT TESTED | Only unverified hypotheses and structural reuse evidence; no money or savings claimed |
| Financial holdings/exposure/history calculations | PASS | Deterministic explicitly supplied-input tests; long-only USD and fixed-holdings history limitations |
| Live licensed market-data feed | NOT TESTED | No provider feed/accounts added; no actual investment portfolio supplied |
| Protected bounded knowledge self-upgrade | PASS | Implemented fixed-file bot PR path, minimum evidence, weekly cooldown, independent verifier and deterministic mocked tests |
| Live autonomous upgrade and merge | NOT TESTED | First cycle correctly produced NO_CANDIDATE; end-to-end GitHub auto-upgrade not observed |
| Autonomous reliability repair worker | PASS | Existing hourly worker repointed to v2, protected PRs and bounded evidence-based repairs; no new paid service |
| Never need humans/general unlimited self-repair | FAIL | Arbitrary autonomous runtime code generation/repair is not implemented or accepted; external access/provider faults can require intervention |
| Nonstop continuous external availability | BLOCKED | GitHub schedule/provider can delay or fail; no existing continuous host provisioned |
| Layered regression and adversarial tests | PASS | 1405 hosted exact-main tests, including36 product tests and12 independent adversarial cases |
| Reproducible real-input end-to-end operation | PASS | Accepted live cycle fetched sources, analyzed, ran simulated experiment, verified doctor and persisted state |
| Protected GitHub integration | PASS | PR642 and643 merged through required App gates and unresolved-thread rules without bypass |
| Exact-main PREPARE/PREFLIGHT/PRE-ARM | PASS | One unchanged main SHA, all mandatory steps, verified artifact/state and Foundation success |
| Authorized lengthy soak and post-soak | NOT TESTED | No explicit authorization; neither started nor declared successful |
| Recovery and restart documentation | PASS | Operations runbook, original recovery commits and active SQLite restart/backup procedures |
| Legacy run37655516971 repair | BLOCKED | Still queued/null; provider record remains an external dependency |
| Read-only execution/no spend/history safety | PASS | No trades, downstream deployment, messages, paid calls, credential changes or historical data deletion |

## Remaining external dependencies and unaccepted work

GitHub run37655516971 still reports queued/null on its old revision, with no jobs;
[issue640](https://github.com/P00NSMASHER/portfolio-brain/issues/640) remains unresolved. V2 does not depend on its lock,
artifacts or record; legacy acceptance remains blocked. No support repair is claimed.
Continuous external hosting/access/provider guarantees are not available from this
hourly design. Full autonomous self-rewriting has not been implemented. Private
live discovery and a real knowledge-upgrade merge have not been demonstrated.
No explicit lengthy-soak authorization was given: SOAK and POST-SOAK are NOT TESTED.
Business value needs actual reviewed downstream experiments and measured outcomes.
