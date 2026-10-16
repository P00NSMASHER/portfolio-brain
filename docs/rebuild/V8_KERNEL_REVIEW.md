# V8 kernel review and verification record

Scope: the first approved v8 kernel plan, not full v8 deployment.

## Test-first evidence

| Batch | Failing-before observation | Passing-after observation |
|---|---|---|
| Contracts | 7 expected feature-missing assertion failures | 7 tests PASS |
| Planning | 6 expected feature-missing assertion failures | 13 cumulative tests PASS |
| Journal | 9 expected feature-missing assertion failures | 9 journal tests PASS |
| Claims | 3 expected claim-feature assertion failures | 25 cumulative tests PASS |
| CLI | 6 expected CLI-feature assertion failures | 31 cumulative tests PASS |
| Review | 7 assertions reproduced graph stall, tail loss, hidden trigger, WAL side effect, action reuse and terminal intent | All reproduced behaviors corrected |
| Snapshot | One assertion reproduced concurrent append causing false tip corruption | Single-transaction replay PASS |
| Final | New assertions plus positive reconciliation controls | 40 focused PASS;1943 full-suite PASS,2 platform skips, exit0 |

An incomplete intermediate local full run is not counted as verification. The
final fresh verbose run completed1943 tests in56.055s with exit0. Provider CI and
independent App checks must be read from the PR's original exact-head runs.

## Independent fresh-context source review

One read-only reviewer inspected all five task commits, the approved spec/plan,
real fixtures and bounded probes. It independently ran the original31 kernel
tests. It identified five Important issues; all received failing-before tests
and corrections in a single source fix pass. Its terminal-intent observation was
regraded Important because it violated terminal-attempt semantics; corrected.
Missing test coverage observations were resolved, not silently deferred.

Corrections: memoized dependency traversal; exact SQLite object allowlist;
transactional count/tip checkpoint; action identities bound to resource/owner/
source and protected from reuse; foreign header/WAL screening before SQLite;
terminal-intent guard; consistent snapshot during concurrent append/replay.

## Rulings and remaining boundaries

- Supplied records, capability declarations, LEARNED inputs and confirmations
  remain advisory. Cost: independent runtime adapters are still required before
  these records can authorize any external action.
- Provider exactly-once execution, deployments, task writes, runtime recovery and
  production migration stay outside this kernel. Cost: the kernel alone is not
  the completed autonomous Brain; subsequent approved subprojects remain necessary.
- Hostile unrestricted same-user filesystem replacement and wholesale rollback
  of database plus checkpoint are not authenticated by a local hash chain.
  Cost: independently retained tips are required before production acceptance.
- Revenue is not a planning input. General AI patch generation, live recovery
  and overall v8 completion remain unverified. Cost: no claim of full autonomy,
  live delivery or100/100 health follows from kernel tests.
- A checkpoint table and read snapshot were added to make the stated replay
  guarantee truthful. Cost: pre-review disposable prototype journals are refused
  rather than silently migrated; no production state is touched.
- Terminal-state new intents are rejected, while existing uncertain actions may
  be reconciled. Cost: a new repair attempt needs a newly recorded work identity.
- The reviewer did not validate protected provider gates. The implementer must
  verify them separately on the final PR head; author review is not a substitute.

Deferred minor findings: none. No second source-review round substitutes for the
observed RED/GREEN regressions and the final full suite.
