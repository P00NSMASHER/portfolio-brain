"""Adversarial test-evidence calibration against unrelated paths and old state.

Test filenames provide structural hints only. They cannot prove code coverage,
successful execution, licensing, business value, or authority to upgrade.
"""
import unittest

from brain.adapters import related_test_paths as discovery_related
from brain.core import BrainError
from brain.intelligence import build_report, related_test_paths, reuse_score
from brain.upgrades import build_knowledge


SHA = "a" * 40
NOW = "2026-10-08T21:00:00Z"


def blobs(*paths):
    return [{"type": "blob", "path": p} for p in paths]


def candidate_event(index, path, paths, *, repo=None):
    repository = repo or f"example/audit{index}"
    payload = {
        "repository": repository, "head_sha": SHA, "path": path,
        "blob_sha": "b" * 40, "code_sha256": "c" * 64,
        "bytes": 1234, "test_paths": list(paths), "license": "UNKNOWN",
        "source_ref": f"https://github.com/{repository}/blob/{SHA}/{path}",
        "target": "freight-recovery", "query": "freight invoice audit",
        "matched_terms": ["freight", "invoice"],
    }
    return {
        "kind": "candidate", "key": f"{repository}:{path}",
        "payload": payload, "observed_at": NOW, "id": f"candidate-event-{index}",
        "data_kind": "ACTUAL",
    }


def repo_event():
    return {
        "kind": "repository", "key": "example/root", "id": "repo-event-1",
        "observed_at": NOW, "data_kind": "ACTUAL",
        "payload": {
            "repository": "example/root", "head_sha": SHA,
            "source_ref": f"https://github.com/example/root/commit/{SHA}",
            "default_branch": "main", "checks": [], "open_issues": 0,
        },
    }


class CandidateTestEvidenceTests(unittest.TestCase):
    def test_actual_module_named_python_test_is_retained(self):
        expected = ["tests/test_invoice.py"]
        self.assertEqual(related_test_paths(
            "src/invoice.py", blobs("tests/test_invoice.py", "tests/conftest.py")
        ), expected)
        self.assertEqual(discovery_related(
            "src/invoice.py", blobs("tests/test_invoice.py")
        ), expected)

    def test_module_named_ts_and_camel_case_test_are_retained(self):
        self.assertEqual(
            related_test_paths("src/lib/srs/schedule.ts", blobs(
                "src/lib/srs/schedule.test.ts", "src/ui/calendar.test.ts"
            )),
            ["src/lib/srs/schedule.test.ts"],
        )
        self.assertEqual(
            related_test_paths("apps/backend/src/reviewSchedule.ts", blobs(
                "apps/backend/tests/review-schedule.spec.ts",
                "apps/agent/tests/review-schedule.spec.ts",
            )),
            ["apps/backend/tests/review-schedule.spec.ts"],
        )

    def test_unrelated_monorepo_suite_and_shared_generic_directories_are_rejected(self):
        self.assertEqual(related_test_paths(
            "apps/terminal/scripts/wallet-settle-probe.ts", blobs(
                "apps/agent/src/card.test.ts",
                "apps/agent/src/wallet-settle-probe.test.ts",
                "apps/terminal/lib/bridge.test.ts",
                "apps/terminal/scripts/wallet-settle-probe.test.ts",
            )
        ), ["apps/terminal/scripts/wallet-settle-probe.test.ts"])

    def test_data_only_vectors_and_config_files_cannot_count_as_executable_tests(self):
        self.assertEqual(related_test_paths(
            "examples/x402-verify-before-pay.ts", blobs(
                "tests/vectors/x402-counterparty-context.json",
                "tests/x402-verify-before-pay.yml",
                "tests/README.md",
            )
        ), [])

    def test_study_repo_general_e2e_suite_cannot_credit_reviews_module(self):
        self.assertEqual(related_test_paths(
            "src/actions/reviews.ts", blobs(
                "e2e/account-and-editing.spec.ts",
                "e2e/auth-and-decks.spec.ts",
                "src/lib/dashboard/stats.test.ts",
                "tests/reviews.spec.ts",
            )
        ), ["tests/reviews.spec.ts"])

    def test_generic_initializer_has_no_module_specific_test_evidence(self):
        self.assertEqual(related_test_paths(
            "python/x402aff/__init__.py", blobs(
                "python/tests/test_affiliation.py", "python/tests/test_payto.py"
            )
        ), [])

    def test_broad_exclusion_remains_separate_from_positive_test_eligibility(self):
        from brain.intelligence import is_test_source_path
        self.assertTrue(is_test_source_path("tests/vectors/context.json"))
        self.assertTrue(is_test_source_path("tests/test_invoice.py"))
        self.assertEqual(related_test_paths(
            "tests/test_invoice.py", blobs("tests/test_invoice.py")
        ), [])

    def test_historical_false_test_paths_lose_score_on_report_replay(self):
        old_tests = [
            "apps/agent/src/card.test.ts",
            "apps/terminal/lib/bridge.test.ts",
            "tests/vectors/x402-context.json",
            "docs/receiving/other-project/test_invoice.py",
        ]
        items = [repo_event()]
        for idx in range(1, 4):
            items.append(candidate_event(
                idx, "apps/terminal/scripts/wallet-settle-probe.ts", old_tests
            ))
        report = build_report(items, now=NOW, max_age=3600)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(len(report["reuse_candidates"]), 3)
        for candidate in report["reuse_candidates"]:
            self.assertEqual(candidate["test_paths"], [])
            self.assertEqual(candidate["reuse_score"], 3)
            self.assertEqual(candidate["utility_evidence"], "STRUCTURAL_ONLY_NOT_EXECUTED")
        self.assertEqual(len(report["business_opportunities"]), 3)
        with self.assertRaisesRegex(BrainError, "INSUFFICIENT_UPGRADE_EVIDENCE"):
            build_knowledge(report)

    def test_genuinely_name_linked_legacy_test_keeps_only_earned_score(self):
        older = candidate_event(1, "src/lib/srs/schedule.ts", [
            "tests/vectors/unrelated.json",
            "src/lib/srs/schedule.test.ts",
            "src/ui/calendar.test.ts",
        ])
        report = build_report([repo_event(), older], now=NOW, max_age=3600)
        c = report["reuse_candidates"][0]
        self.assertEqual(c["test_paths"], ["src/lib/srs/schedule.test.ts"])
        self.assertEqual(c["reuse_score"], 6)
        self.assertEqual(reuse_score(c), 6)

    def test_no_candidate_can_claim_test_execution_or_verified_revenue(self):
        event = candidate_event(1, "src/invoice.py", ["tests/test_invoice.py"])
        report = build_report([repo_event(), event], now=NOW, max_age=3600)
        candidate = report["reuse_candidates"][0]
        self.assertEqual(candidate["utility_evidence"], "STRUCTURAL_ONLY_NOT_EXECUTED")
        self.assertIsNone(report["learning"]["verified_revenue"])
        self.assertEqual(report["business_opportunities"][0]["revenue"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
