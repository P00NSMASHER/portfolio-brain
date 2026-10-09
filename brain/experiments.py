"""Reviewed, bounded experiment code. Discovered source is never executed.

All invoice inputs are synthetic. Equality comparisons and hash-set membership
probes are different units of work, NOT comparable timings or financial savings.
"""
from random import Random

from brain.core import require


def _synthetic_invoice_rows(count):
    """Build reproducible, mostly distinct exact-tuple invoice cases.

    The earlier fixture recycled a small 113-row seed throughout nearly the
    entire workload. That strongly favored a duplicate-heavy synthetic case.
    Keep deliberate duplicates bounded to about one eighth of cases, plus two
    deliberately close (but unequal) invoice tuples. No real invoice data.
    """
    require(type(count) is int and 20 <= count <= 2000,
            "experiment size must be 20..2000")
    deliberate_duplicates = max(1, (count - 2) // 8)
    unique_count = count - 2 - deliberate_duplicates
    originals = [
        (f"CARRIER-{i % 13:02d}", f"INV-{i:06d}", 100 + ((i * 29) % 997))
        for i in range(unique_count)
    ]
    # Source indices are deterministic, but not dependent on any customer data.
    duplicates = [
        originals[(i * 37 + 11) % unique_count]
        for i in range(deliberate_duplicates)
    ]
    anchor = originals[0]
    near_misses = (
        (anchor[0] + "-OTHER", anchor[1], anchor[2]),
        (anchor[0], anchor[1], anchor[2] + 100_000),
    )
    require(
        all(row not in originals and row not in duplicates for row in near_misses)
        and near_misses[0] != near_misses[1],
        "synthetic near-miss contamination",
    )
    rows = originals + duplicates + list(near_misses)
    Random(20261009 + count).shuffle(rows)
    require(len(rows) == count and len(set(rows)) == count - deliberate_duplicates,
            "synthetic duplicate-count contract failed")
    return rows, deliberate_duplicates, near_misses


def _baseline_duplicate_indices(rows):
    """First-equal-prior-row oracle, counting exact tuple comparisons."""
    duplicates = []
    equality_comparisons = 0
    for index, row in enumerate(rows):
        for prior_index in range(index):
            equality_comparisons += 1
            if row == rows[prior_index]:
                duplicates.append(index)
                break
    return duplicates, equality_comparisons


def _indexed_duplicate_indices(rows):
    """Set-based implementation: one membership probe per input row."""
    seen = set()
    duplicates = []
    for index, row in enumerate(rows):
        if row in seen:
            duplicates.append(index)
        seen.add(row)
    return duplicates


def invoice_dedup_experiment(count=500):
    require(type(count) is int and 20 <= count <= 2000,
            "experiment size must be 20..2000")
    rows, intended_duplicates, near_misses = _synthetic_invoice_rows(count)
    baseline, comparisons = _baseline_duplicate_indices(rows)
    indexed = _indexed_duplicate_indices(rows)
    require(
        baseline == indexed and len(indexed) == intended_duplicates,
        "candidate failed correctness oracle or injected duplicate-count check",
    )
    require(
        all(rows.count(row) == 1 for row in near_misses),
        "synthetic near-miss became an exact duplicate",
    )
    require(
        comparisons >= len(rows),
        "unexpected operation counter: baseline comparisons below membership probes",
    )
    return {
        "experiment": "invoice-dedup-index-v1",
        "dataset_kind": "SIMULATED",
        "cases": count,
        "baseline_operations": comparisons,
        "candidate_operations": len(rows),
        "equal_outputs": True,
        "duplicate_cases": len(indexed),
        "near_duplicates": 2,
        "source_ref": "brain/experiments.py:invoice-dedup-index-v1",
        "scope": (
            "Synthetic exact-tuple duplicate experiment: mostly distinct "
            "invoices, deliberate repeats and two nonduplicate near misses. "
            "Baseline operations count tuple equality comparisons; candidate "
            "operations count set membership probes. These are NON-EQUIVALENT "
            "units, not benchmark timings or a verified speedup. No production "
            "behavior, freight overpayment, revenue, engineering time saved "
            "or customer benefit is established."
        ),
    }
