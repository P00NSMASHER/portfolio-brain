# Portfolio Brain: synthetic invoice experiment integrity

This synthetic method originated in independent draft PR #663. Its latest,
independently checked implementation and tests are staged **unchanged** in
the existing V5 integration draft PR #661; the original PR #663 remains
OPEN/DRAFT/UNMERGED. The balanced-knowledge candidate PR #662 also remains
unchanged. This does not enable invoice ingestion, real freight recovery,
trades, messages, deployment, external reads, or paid services.

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
  rows sampled deterministically **without replacement** from those unique
  tuples. Each original invoice is duplicated at most once; no one source
  invoice is allowed to account for multiple injected duplicate rows.
- Inject **two** explicit near misses for one original: a different
  carrier and a different charge amount. Both must remain distinct from
  every exact duplicate and appear only once.
- Interleave the records reproducibly with a locally seeded pseudorandom
  shuffle. These are test cases, **not** a sample drawn from real shipments.
- Require the quadratic first-prior-equality detector and set-membership
  detector to return the same exact duplicate positions; verify that
  the detected count also matches the independently injected count.
- Fail closed if the identity checks, near-miss uniqueness, or the
  requirement that each duplicate comes from a **distinct original** breaks.

### Corrected second-order fixture defect

The original draft's deterministic selection used a fixed modular stride
`(i * 37 + 11) % unique_count`. At `count=44`, there are 37 unique
original invoices and 5 intended duplicate copies. Because the modulus is
also 37, **all five copies came from original index 11**. The earlier
checks counted five duplicate rows, but did not detect the missing variety
in duplicated sources. The updated sampler draws five **different** originals
without replacement, and a separate frequency contract rejects fixtures
where any invoice appears more than twice.

The new adversarial suite validates the source-frequency distribution for
**every supported size 20 through 2,000 (1,981 sizes)** in linear time per
fixture. The more expensive quadratic-vs-index duplicate-position oracle is
run for representative and boundary sizes, not all 1,981 lengths. This
remains a synthetic methodology test, not evidence of actual invoice volumes.

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
hand-built fixture, the former `count=44` collision, exhaustive size-range
source-diversity checks, oracle mismatch, injected-count tampering, event
schema compatibility and claims about unequal metric units.

This source candidate must pass full Foundation CI and the independently
credentialed App check at the **exact PR head**. No production source
transition, source promotion, new acceptance clock or merge is authorized.
The combined V5 integration branch must pass NEW Foundation and separately
credentialed App checks at its **exact final head**. Source PR checks alone
cannot certify an assembled revision. Historical v4 certification does not
transfer to V5. All original source PR branches remain unmerged, and no
protected-main promotion, V5 scheduled execution or acceptance is authorized.
