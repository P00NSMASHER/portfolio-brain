"""Target-diverse selection for existing evidence-only Brain knowledge upgrades.

Offline, no network, mutation, code execution, paid calls or source promotion.
"""
import copy
import itertools
import unittest
from collections import Counter

from brain.core import BrainError, digest
from brain.upgrades import balanced_knowledge_sources, build_knowledge


def candidate(project, index, owner="ExampleOrg"):
    repository = f"{owner}/sources"
    path = f"src/invoice_match_{index:03}.py"
    source_sha = "a" * 40
    return {
        "key": f"{repository}:{path}",
        "repository": repository,
        "head_sha": source_sha,
        "path": path,
        "blob_sha": "b" * 40,
        "code_sha256": "c" * 64,
        "bytes": 2048,
        "test_paths": [f"tests/test_invoice_match_{index:03}.py"],
        "license": "MIT",
        "source_ref": f"https://github.com/{repository}/blob/{source_sha}/{path}",
        "target": project,
        "matched_terms": ["invoice", "match"],
        "freshness": "CURRENT",
        "data_kind": "ACTUAL",
    }


def report(rows):
    return {"status": "PASS", "reuse_candidates": rows}


class BalancedKnowledgeSelection(unittest.TestCase):
    def test_early_alphabetical_project_cannot_monopolize_all_twelve(self):
        rows = [candidate("school-tools", i, "AAA") for i in range(20)]
        rows += [candidate("freight-recovery", 201, "ZZZ")]
        rows += [candidate("agent-products", i, "ZZZ") for i in (301, 302)]
        selected = balanced_knowledge_sources(rows)
        counts = Counter(item["target"] for item in selected)
        self.assertEqual(len(selected), 12)
        self.assertEqual(counts, {
            "school-tools": 9, "freight-recovery": 1, "agent-products": 2,
        })
        self.assertEqual([x["target"] for x in selected[:3]], [
            "agent-products", "freight-recovery", "school-tools",
        ])

    def test_round_robin_when_every_target_has_sufficient_evidence(self):
        rows = [
            candidate(project, i, str(j) + "Org")
            for j, project in enumerate(("school-tools", "agent-products", "freight-recovery"))
            for i in range(1, 9)
        ]
        selected = balanced_knowledge_sources(rows)
        self.assertEqual(Counter(x["target"] for x in selected), {
            "school-tools": 4, "freight-recovery": 4, "agent-products": 4,
        })
        self.assertEqual(len({x["key"] for x in selected}), 12)

    def test_one_project_retains_stable_legacy_key_order(self):
        rows = [candidate("school-tools", i, "Only") for i in range(17, -1, -1)]
        selected = balanced_knowledge_sources(rows)
        self.assertEqual(
            [x["key"] for x in selected],
            sorted(x["key"] for x in rows)[:12],
        )

    def test_exhausted_targets_backfill_without_blank_slots(self):
        rows = [candidate("school-tools", i, "Alpha") for i in range(30)]
        rows.append(candidate("agent-products", 99, "Beta"))
        selected = balanced_knowledge_sources(rows)
        self.assertEqual(len(selected), 12)
        self.assertEqual(Counter(x["target"] for x in selected), {
            "school-tools": 11, "agent-products": 1,
        })

    def test_all_permutations_have_identical_selection_order(self):
        rows = [
            candidate("school-tools", 1, "AAA"),
            candidate("freight-recovery", 2, "ZZZ"),
            candidate("school-tools", 3, "AAA"),
            candidate("agent-products", 4, "ZZZ"),
            candidate("freight-recovery", 5, "ZZZ"),
        ]
        expected = [c["key"] for c in balanced_knowledge_sources(rows)]
        for perm in itertools.permutations(rows):
            self.assertEqual([x["key"] for x in balanced_knowledge_sources(perm)], expected)

    def test_empty_input_and_limit_bounds(self):
        self.assertEqual(balanced_knowledge_sources([]), [])
        self.assertEqual(len(balanced_knowledge_sources([
            candidate("school-tools", 1), candidate("school-tools", 2)
        ], limit=1)), 1)
        for limit in (0, -1, 13, True, 1.5, "12"):
            with self.subTest(limit=limit):
                with self.assertRaises(BrainError):
                    balanced_knowledge_sources([], limit=limit)

    def test_selection_does_not_modify_source_input(self):
        rows = [candidate("school-tools", i) for i in range(5)]
        before = copy.deepcopy(rows)
        balanced_knowledge_sources(rows)
        self.assertEqual(rows, before)

    def test_upgrade_output_fingerprint_and_fields_remain_canonical(self):
        rows = [candidate("school-tools", i, "AAA") for i in range(20)]
        rows += [candidate("freight-recovery", 222, "ZZZ")]
        rows += [candidate("agent-products", 333, "ZZZ")]
        result = build_knowledge(report(rows))
        reversed_result = build_knowledge(report(list(reversed(rows))))
        self.assertEqual(result, reversed_result)
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["scope"], "STRUCTURAL_REUSE_KNOWLEDGE_NOT_EXECUTED_OR_REVENUE_VERIFIED")
        self.assertEqual(result["fingerprint"], digest(result["sources"]))
        self.assertEqual(len(result["sources"]), 12)
        self.assertEqual({x["target"] for x in result["sources"]}, {
            "school-tools", "agent-products", "freight-recovery",
        })
        expected_fields = {
            "key", "repository", "head_sha", "path", "blob_sha",
            "code_sha256", "test_paths", "license", "source_ref",
            "target", "matched_terms",
        }
        self.assertTrue(all(set(source) == expected_fields for source in result["sources"]))

    def test_existing_three_qualified_sources_rule_unchanged(self):
        with self.assertRaisesRegex(BrainError, "INSUFFICIENT_UPGRADE_EVIDENCE"):
            build_knowledge(report([
                candidate("school-tools", 1), candidate("freight-recovery", 2)
            ]))

    def test_nonactual_stale_and_unrelated_tests_do_not_gain_eligibility(self):
        actual = [candidate("school-tools", 1), candidate("agent-products", 2)]
        simulated = candidate("freight-recovery", 3)
        simulated["data_kind"] = "SIMULATED"
        historical = candidate("freight-recovery", 4)
        historical["freshness"] = "HISTORICAL"
        unrelated = candidate("freight-recovery", 5)
        unrelated["test_paths"] = ["tests/test_unrelated_login.py"]
        with self.assertRaisesRegex(BrainError, "INSUFFICIENT_UPGRADE_EVIDENCE"):
            build_knowledge(report(actual + [simulated, historical, unrelated]))
        actual.append(candidate("freight-recovery", 6))
        accepted = build_knowledge(report(actual + [simulated, historical, unrelated]))
        self.assertEqual(len(accepted["sources"]), 3)
        self.assertEqual({x["key"] for x in accepted["sources"]},
                         {x["key"] for x in actual})

    def test_nonpassing_report_stays_blocked(self):
        with self.assertRaisesRegex(BrainError, "passing authoritative report"):
            build_knowledge({"status": "BLOCKED", "reuse_candidates": [
                candidate("school-tools", i) for i in range(4)
            ]})


if __name__ == "__main__":
    unittest.main()
