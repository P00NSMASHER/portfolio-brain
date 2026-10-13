"""V7 fair urgent-check selection and fail-closed public receipt semantics."""
import copy
import unittest

from brain.adapters import GitHub
from brain.investigate import investigate
from brain.sidecar import summarize
from test_brain_evidence_gaps import check, observe, verified, T0, T1
from test_brain_investigate import Transport, REPO, OTHER, THIRD, NOW, SOURCE
from test_brain_continuation import FOURTH
from test_brain_sidecar import observation as old_observation

REPOS = (REPO, OTHER, THIRD, FOURTH)


class CriticalCheckFairnessTests(unittest.TestCase):
    def test_four_simultaneous_new_check_regressions_rotate_within_existing_budget(self):
        events = []
        for repository in REPOS:
            events.extend((
                observe(repository, T0, [check(repository, conclusion="success")]),
                observe(repository, T1, [check(repository, conclusion="failure")]),
            ))
        report, history = verified(*events)
        skipped = set()
        snapshots = {}
        for hour in range(16, 20):
            moment = f"2026-10-12T{hour:02d}:00:00Z"
            transport = Transport()
            result = investigate(report, history=history, now=moment,
                                 api=GitHub(transport=transport))
            self.assertEqual(result["eligible_count"], 4)
            self.assertEqual(result["deferred_count"], 1)
            self.assertEqual(len(result["investigations"]), 3)
            self.assertEqual(result["requests_used"], 12)
            self.assertEqual(len(transport.calls), 12)
            self.assertEqual(result["status"],
                             "BOUNDED_READ_ONLY_REVALIDATION_COMPLETE_WITH_DEFERRED")
            self.assertFalse(result["execution_authority"])
            self.assertEqual(result["events_written"], 0)
            observed = {row["repository"] for row in result["investigations"]}
            self.assertEqual(len(observed), 3)
            self.assertTrue(all("follow_up_kind" not in row
                                for row in result["investigations"]))
            skipped.update(set(REPOS) - observed)
            snapshots[moment] = [r["repository"] for r in result["investigations"]]
        self.assertEqual(skipped, set(REPOS))
        self.assertNotEqual(snapshots["2026-10-12T16:00:00Z"],
                            snapshots["2026-10-12T17:00:00Z"])

    def test_new_regressions_still_have_priority_over_evidence_gaps(self):
        events = (
            observe(REPO, T0, [check(REPO, conclusion="success")]),
            observe(REPO, T1, [check(REPO, conclusion="failure")]),
            observe(OTHER, T0, [check(OTHER, conclusion="success")]),
            observe(OTHER, T1, []),
        )
        report, history = verified(*events)
        result = investigate(report, history=history, now=NOW,
                             api=GitHub(transport=Transport()))
        self.assertEqual([x["repository"] for x in result["investigations"]],
                         [REPO, OTHER])
        self.assertEqual(result["requests_used"], 8)


class SanitizeReceiptIntegrityTests(unittest.TestCase):
    def verify_blocked(self, report):
        result = summarize(report, SOURCE, *["success"] * 4)
        self.assertEqual(result["status"], "BLOCKED_NO_VERIFIED_INVESTIGATION")
        self.assertEqual(result["observed_check_evidence_classes"], {})
        self.assertIs(result["execution_authority"], False)
        self.assertIs(result["authorization_granted"], False)

    def test_status_count_inconsistency_is_not_laundered_to_success(self):
        original = old_observation()
        for updates in (
            {"status": "NO_ELIGIBLE_FAILURES"},
            {"status": "READ_ONLY_REVALIDATION_COMPLETE",
             "eligible_count": 2, "deferred_count": 1},
            {"status": "BOUNDED_READ_ONLY_REVALIDATION_COMPLETE_WITH_DEFERRED"},
            {"status": "STOPPED"},
            {"status": "REQUEST_BUDGET_DEFERRED"},
            {"status": "INCOMPLETE_READ_ONLY_REVALIDATION"},
        ):
            with self.subTest(updates=updates):
                modified = copy.deepcopy(original)
                modified.update(updates)
                self.verify_blocked(modified)

    def test_zero_eligible_cases_must_have_zero_checks_zero_gets(self):
        original = old_observation()
        for changes in (
            {"status":"NO_ELIGIBLE_FAILURES", "eligible_count":0,
             "deferred_count":0, "investigations": [], "requests_used":4},
            {"status":"NO_ELIGIBLE_FAILURES", "eligible_count":0,
             "deferred_count":0, "investigations": [original["investigations"][0]],
             "requests_used":0},
            {"status":"READ_ONLY_REVALIDATION_COMPLETE", "eligible_count":0,
             "deferred_count":0, "investigations": [], "requests_used":0},
        ):
            with self.subTest(changes=changes):
                modified = copy.deepcopy(original)
                modified.update(changes)
                self.verify_blocked(modified)

    def test_legitimate_incomplete_provider_failure_remains_partial(self):
        original = old_observation()
        failed = copy.deepcopy(original)
        failed["status"] = "INCOMPLETE_READ_ONLY_REVALIDATION"
        failed["investigations"][0]["checks"] = []
        failed["investigations"][0]["outcome"] = "UNVERIFIED_READ_FAILED"
        status = summarize(failed, SOURCE, *["success"] * 4)
        self.assertEqual(status["status"], "PARTIAL_READ_ONLY")
        self.assertIs(status["root_cause_verified"], False)

    def test_per_check_classes_must_match_original_replay_plan(self):
        repo = REPO
        report, history = verified(
            observe(repo, T0, [check(repo, conclusion="failure")]),
            observe(repo, T1, [check(repo, conclusion="failure")]))
        receipt = investigate(report, history=history, now=NOW,
                              api=GitHub(transport=Transport()))
        self.assertEqual(summarize(receipt, SOURCE, *["success"] * 4)["status"],
                         "OBSERVED_READ_ONLY")
        tamper = copy.deepcopy(receipt)
        tamper["investigations"][0]["checks"][0][
            "original_evidence_class"] = "RECOVERY_OBSERVED_NOT_RESOLUTION"
        self.verify_blocked(tamper)
        tamper = copy.deepcopy(receipt)
        tamper["investigations"][0]["check_evidence_classes"]["validate"] = (
            "RECOVERY_OBSERVED_NOT_RESOLUTION"
        )
        self.verify_blocked(tamper)

    def test_missing_or_duplicate_check_names_are_rejected(self):
        original = old_observation()
        for names in (["validate", "validate"], ["different"], []):
            with self.subTest(names=names):
                modified = copy.deepcopy(original)
                modified["investigations"][0]["check_names"] = names
                self.verify_blocked(modified)

    def test_replayed_sidecar_source_is_kept_private(self):
        receipt = old_observation()
        self.assertEqual(summarize(receipt, SOURCE, *["success"] * 4)["status"],
                         "OBSERVED_READ_ONLY")
        altered = copy.deepcopy(receipt)
        altered["investigations"][0]["outcome"] = "SOURCE_CHANGED_REQUIRES_NEW_COMPARISON"
        self.verify_blocked(altered)


if __name__ == "__main__":
    unittest.main()
