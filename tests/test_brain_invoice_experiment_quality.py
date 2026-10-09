"""Adversarial correctness and interpretation tests for synthetic invoice evidence.

No network, customers, timing benchmarks, external code or revenue assertions.
"""
import copy
import itertools
from collections import Counter
import unittest
from unittest.mock import patch

from brain.adapters import event
from brain.core import BrainError, validate_event
from brain.experiments import (
    _baseline_duplicate_indices,
    _indexed_duplicate_indices,
    _synthetic_invoice_rows,
    invoice_dedup_experiment,
)
from brain.intelligence import validate_payload


class InvoiceExperimentQuality(unittest.TestCase):
    def test_default_and_full_supported_counts_are_deterministic(self):
        for count in (20, 21, 24, 100, 500, 1000, 2000):
            with self.subTest(count=count):
                self.assertEqual(
                    invoice_dedup_experiment(count),
                    invoice_dedup_experiment(count),
                )
                self.assertEqual(
                    _synthetic_invoice_rows(count),
                    _synthetic_invoice_rows(count),
                )

    def test_mostly_distinct_corpus_is_not_duplicate_heavy(self):
        for count in (20, 21, 44, 100, 500, 1000, 2000):
            with self.subTest(count=count):
                rows, intentional, near = _synthetic_invoice_rows(count)
                self.assertEqual(len(rows), count)
                self.assertEqual(len(set(rows)), count - intentional)
                self.assertGreaterEqual(len(set(rows)) * 4, count * 3)
                self.assertEqual(intentional, max(1, (count - 2) // 8))
                self.assertEqual(len(near), 2)
                self.assertNotEqual(near[0], near[1])
                self.assertTrue(all(rows.count(x) == 1 for x in near))
                self.assertTrue(all(isinstance(x, tuple) and len(x) == 3
                                    for x in rows))
                self.assertTrue(all(isinstance(x[0], str) and
                                    isinstance(x[1], str) and
                                    type(x[2]) is int for x in rows))

    def test_all_1981_supported_sizes_duplicate_distinct_originals(self):
        # O(sum(count)) fixture validation, not an O(count**2) oracle at
        # every size. The expensive quadratic oracle is covered separately.
        for count in range(20, 2001):
            with self.subTest(count=count):
                rows, intentional, near = _synthetic_invoice_rows(count)
                frequencies = Counter(rows)
                self.assertEqual(len(rows), count)
                self.assertEqual(len(frequencies), count - intentional)
                self.assertEqual(sum(n == 2 for n in frequencies.values()),
                                 intentional)
                self.assertTrue(all(n in (1, 2) for n in frequencies.values()))
                self.assertEqual(len(near), 2)
                self.assertTrue(all(frequencies[n] == 1 for n in near))

    def test_former_stride_collision_at_size_44_is_eliminated(self):
        rows, intentional, near = _synthetic_invoice_rows(44)
        frequencies = Counter(rows)
        self.assertEqual(intentional, 5)
        self.assertEqual(len(rows), 44)
        self.assertEqual(len(frequencies), 39)
        self.assertEqual(sum(n == 2 for n in frequencies.values()), 5)
        self.assertTrue(all(n <= 2 for n in frequencies.values()))
        self.assertTrue(all(frequencies[n] == 1 for n in near))
        self.assertEqual(
            len(_indexed_duplicate_indices(rows)), 5,
        )
        self.assertEqual(
            _indexed_duplicate_indices(rows), _baseline_duplicate_indices(rows)[0],
        )
        self.assertEqual(invoice_dedup_experiment(44)["duplicate_cases"], 5)

    def test_old_collision_fixture_fails_closed_despite_correct_total(self):
        count = 44
        intentional = (count - 2) // 8
        originals = [
            (f"CARRIER-{i % 13:02d}", f"INV-{i:06d}",
             100 + ((i * 29) % 997))
            for i in range(count - 2 - intentional)
        ]
        # Historical modulo stride 37 and modulus 37 selected source 11
        # five times, despite the intended five separate duplicate originals.
        wrong_copies = [
            originals[(i * 37 + 11) % len(originals)]
            for i in range(intentional)
        ]
        self.assertEqual(len(set(wrong_copies)), 1)
        anchor = originals[0]
        near = (
            (anchor[0] + "-OTHER", anchor[1], anchor[2]),
            (anchor[0], anchor[1], anchor[2] + 100_000),
        )
        rows = originals + wrong_copies + list(near)
        self.assertEqual(_indexed_duplicate_indices(rows),
                         _baseline_duplicate_indices(rows)[0])
        self.assertEqual(len(_indexed_duplicate_indices(rows)), intentional)
        with patch("brain.experiments._synthetic_invoice_rows",
                   return_value=(rows, intentional, near)):
            with self.assertRaisesRegex(BrainError,
                                        "synthetic duplicate-source diversity"):
                invoice_dedup_experiment(count)

    def test_experiment_duplicate_case_count_matches_known_injections(self):
        for count in (20, 21, 100, 500, 1000, 2000):
            with self.subTest(count=count):
                rows, intentional, _ = _synthetic_invoice_rows(count)
                baseline, comparisons = _baseline_duplicate_indices(rows)
                indexed = _indexed_duplicate_indices(rows)
                result = invoice_dedup_experiment(count)
                self.assertEqual(indexed, baseline)
                self.assertEqual(len(indexed), intentional)
                self.assertEqual(result["duplicate_cases"], intentional)
                self.assertEqual(result["near_duplicates"], 2)
                self.assertEqual(result["baseline_operations"], comparisons)
                self.assertEqual(result["candidate_operations"], count)
                self.assertGreaterEqual(comparisons, count)

    def test_previous_duplicate_heavy_fixture_does_not_return(self):
        result = invoice_dedup_experiment(1000)
        self.assertGreater(result["duplicate_cases"], 100)
        self.assertLess(result["duplicate_cases"], 150)
        self.assertEqual(result["cases"], 1000)

    def test_exact_tuple_near_misses_do_not_count_as_duplicates(self):
        rows = [
            ("C", "INV-1", 100),
            ("OTHER", "INV-1", 100),  # different carrier
            ("C", "INV-1", 101),      # different amount
            ("C", "INV-1 ", 100),     # different invoice string
            ("c", "INV-1", 100),      # case difference is not equality
            ("C", "INV-1", 100),      # exact copy of first
            ("C", "INV-1", 101),      # exact copy of third
        ]
        self.assertEqual(_indexed_duplicate_indices(rows), [5, 6])
        self.assertEqual(_baseline_duplicate_indices(rows)[0], [5, 6])

    def test_baseline_and_index_agree_across_all_handcrafted_orders(self):
        data = [
            ("A", "1", 1),
            ("A", "1", 1),
            ("A", "1", 2),
            ("B", "1", 1),
            ("A", "2", 1),
            ("B", "1", 1),
        ]
        for order in itertools.permutations(data):
            expected = [
                i for i, row in enumerate(order) if row in order[:i]
            ]
            self.assertEqual(_baseline_duplicate_indices(order)[0], expected)
            self.assertEqual(_indexed_duplicate_indices(order), expected)

    def test_all_unique_and_all_duplicate_extremes(self):
        unique = [("C", f"I-{i}", i) for i in range(40)]
        identical = [("C", "I-0", 0)] * 40
        self.assertEqual(_baseline_duplicate_indices(unique)[0], [])
        self.assertEqual(_indexed_duplicate_indices(unique), [])
        self.assertEqual(_baseline_duplicate_indices(identical)[0],
                         list(range(1, 40)))
        self.assertEqual(_indexed_duplicate_indices(identical),
                         list(range(1, 40)))
        self.assertEqual(_baseline_duplicate_indices(unique)[1], 780)
        self.assertEqual(_baseline_duplicate_indices(identical)[1], 39)

    def test_detectors_do_not_modify_caller_rows(self):
        rows, _, _ = _synthetic_invoice_rows(100)
        before = copy.deepcopy(rows)
        _baseline_duplicate_indices(rows)
        _indexed_duplicate_indices(rows)
        self.assertEqual(rows, before)

    def test_oracle_mismatch_fails_closed(self):
        with patch("brain.experiments._indexed_duplicate_indices",
                   return_value=[]):
            with self.assertRaisesRegex(BrainError, "correctness oracle"):
                invoice_dedup_experiment(100)

    def test_claimed_duplicate_count_mismatch_fails_closed(self):
        rows, deliberate, near = _synthetic_invoice_rows(100)
        with patch("brain.experiments._synthetic_invoice_rows",
                   return_value=(rows, deliberate + 1, near)):
            with self.assertRaisesRegex(BrainError, "injected duplicate-count"):
                invoice_dedup_experiment(100)

    def test_contaminated_near_miss_fails_closed(self):
        rows, deliberate, near = _synthetic_invoice_rows(100)
        contaminated = (near[0], near[0])
        with patch("brain.experiments._synthetic_invoice_rows",
                   return_value=(rows, deliberate, contaminated)):
            with self.assertRaisesRegex(BrainError, "near-miss"):
                invoice_dedup_experiment(100)

    def test_invalid_boundaries_rejected_without_silent_coercion(self):
        for count in (-1, 0, 19, 2001, True, False, 100.0, "100", None, []):
            with self.subTest(count=count):
                with self.assertRaises(BrainError):
                    invoice_dedup_experiment(count)

    def test_event_schema_still_exactly_matches_existing_authority(self):
        result = invoice_dedup_experiment(500)
        self.assertEqual(set(result), {
            "experiment", "dataset_kind", "cases", "baseline_operations",
            "candidate_operations", "equal_outputs", "duplicate_cases",
            "near_duplicates", "source_ref", "scope",
        })
        self.assertEqual(result["experiment"], "invoice-dedup-index-v1")
        self.assertEqual(result["dataset_kind"], "SIMULATED")
        self.assertIs(result["equal_outputs"], True)
        self.assertEqual(
            result["source_ref"],
            "brain/experiments.py:invoice-dedup-index-v1",
        )
        now = "2026-10-09T00:00:00Z"
        validate_payload("experiment", result, now)
        item = event("experiment", result["experiment"], result,
                     "a" * 40, data_kind="SIMULATED", now=now)
        validate_event(item, now)

    def test_truthful_non_equivalent_operation_units_and_no_value_claim(self):
        scope = invoice_dedup_experiment(500)["scope"].lower()
        for term in (
            "synthetic", "tuple equality comparisons",
            "set membership probes", "non-equivalent", "not benchmark timings",
            "no production", "freight overpayment", "revenue",
            "engineering time saved", "customer benefit",
        ):
            with self.subTest(term=term):
                self.assertIn(term, scope)
        self.assertNotIn("demonstrates a verified speedup", scope)


if __name__ == "__main__":
    unittest.main()
