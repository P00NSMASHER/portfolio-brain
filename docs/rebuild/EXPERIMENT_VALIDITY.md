# Portfolio Brain: synthetic invoice experiment integrity

This proposal is an **offline evidence-quality candidate**, built separately
from V5 integration PR #661 and knowledge-diversity PR #662. Its exact
reviewed implementation/tests are now staged in the V5 draft candidate,
while source PR #663 remains untouched and unmerged. It does not
enable invoice ingestion, real freight recovery, trades, messages, deployment,
external reads, or paid services.

## Defect in the original research fixture

The historical `invoice-dedup-index-v1` fixture reused at most 113 distinct
source tuples to fill a workload of up to 2,000 records. For a requested size
of 1,000 records, 885 of the first 998 rows were repeated tuple values.
This tests an unusually duplicate-heavy synthetic workload and could give
a misleading impression of general algorithm performance.

The experiment still only detects **exact equality** of the tuple
`(carrier, invoice_identifier, amount)`, not freight billing errors or
near matches.

## Revised deterministic synthetic case mix

- Preserve the original allowed size `20..2000` and the ten-field
  `experiment` event payload contract.
- Generate `count - 2 - max(1, (count - 2) // 8)` unique synthetic
  invoice tuples with unique synthetic invoice identifiers.
- Inject exactly `max(1, (count - 2) // 8)` intentional true-duplicate
  rows sampled deterministically from those unique tuples.
- Inject **two** explicit near misses for one original: a different
  carrier and a different charge amount. Both must remain distinct from
  every exact duplicate and appear only once.
- Interleave the records reproducibly with a locally seeded pseudorandom
  shuffle. These are test cases, **not** a sample drawn from real shipments.
- Require the quadratic first-prior-equality detector and set-membership
  detector to return the same exact duplicate positions; verify that
  the detected count also matches the independently injected count.
- Fail closed if the identity checks or near-miss uniqueness checks break.

A size-1,000 experiment now includes 874 unique source rows, 124 injected
copies, and two distinct near misses, for a total of 1,000. It is still
a deliberately simplified synthetic test and does not purport to describe
actual duplicate rates.

## Metric truth boundaries

The retained `baseline_operations` field counts individual exact-tuple
equality comparisons. The retained `candidate_operations` field counts
**one set membership probe per input row**. They are **not equivalent cost
units**: hashing, insertions, interpreter overhead and hardware are not
measured. A smaller numerical count is *not* a measured speedup, elapsed
time saving, lower cost, or validated business impact.

No case establishes whether a duplicate invoice is a recoverable freight
billing error. No real invoice, customer identity, financial benefit or
production benchmark is used. The synthetic status, fixed source_ref, event
schema, deterministic SQLite replay and absence of execution authority
remain intact.

## Verification and release requirements

`tests/test_brain_invoice_experiment_quality.py` covers minimum and
maximum bounds, repeatability, all-unique/all-duplicate adversarial cases,
near misses across carrier/amount/text/case, all permutations of a small
hand-built fixture, oracle mismatch, injected-count tampering, event schema
compatibility and claims about unequal metric units.

This source candidate must pass full Foundation CI and the independently
credentialed App check at the **exact PR head**. No production source
transition, source promotion, new acceptance clock or merge is authorized.
The combined V5 draft must independently pass its own exact-head Foundation
and App gates; the source PR's independent checks cannot substitute for that
integration result. Historical v4 certification does not transfer to a new
source commit, and no protected main promotion is authorized.
