"""Same-revision persistent failures, observed recoveries and evidence gaps."""
import copy
import unittest
from brain.adapters import GitHub
from brain.investigate import investigate
from brain.sidecar import summarize
from brain.render import investigation_summary_lines
from test_brain_evidence_gaps import check, observe, verified, T0, T1
from test_brain_investigate import Transport, REPO, REV, SOURCE, NOW


def record(when, statuses):
    return observe(REPO, when, [
        check(REPO, name=name, conclusion=status)
        for name, status in sorted(statuses.items())
    ])


def investigate_pair(before, after):
    report, history = verified(record(T0, before), record(T1, after))
    original = copy.deepcopy((report, history))
    provider = Transport()
    provider.extra_checks = [
        {"id": 21, "name": "audit", "status": "completed",
         "conclusion": "success", "head_sha": REV,
         "html_url": f"https://github.com/{REPO}/actions/runs/11/job/21"},
        {"id": 22, "name": "persist", "status": "completed",
         "conclusion": "failure", "head_sha": REV,
         "html_url": f"https://github.com/{REPO}/actions/runs/11/job/22"}
    ]
    result = investigate(report, history=history,
                         api=GitHub(transport=provider), now=NOW)
    assert (report, history) == original
    return result, provider


class MixedCheckSignalTests(unittest.TestCase):
    def test_persistent_failure_not_hidden_by_simultaneous_recovery(self):
        result, provider = investigate_pair(
            {"persist": "failure", "audit": "failure"},
            {"persist": "failure", "audit": "success"})
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["requests_used"], 4)
        self.assertEqual(len(provider.calls), 4)
        row = result["investigations"][0]
        self.assertEqual(row["follow_up_kind"], "PERSISTENT_ADVERSE_OBSERVED")
        self.assertEqual(row["check_names"], ["audit", "persist"])
        self.assertEqual(row["check_evidence_classes"], {
            "persist": "PERSISTENT_ADVERSE_OBSERVED",
            "audit": "RECOVERY_OBSERVED_NOT_RESOLUTION"
        })
        self.assertEqual(
            {x["name"]: x["original_evidence_class"] for x in row["checks"]},
            row["check_evidence_classes"])
        public = summarize(result, SOURCE, *["success"] * 4)
        self.assertEqual(public["observed_check_evidence_classes"], {
            "PERSISTENT_ADVERSE_OBSERVED": 1,
            "RECOVERY_OBSERVED_NOT_RESOLUTION": 1
        })
        self.assertIs(public["root_cause_verified"], False)
        self.assertEqual(public["github_mutations"], 0)
        self.assertNotIn(REPO, str(public))

    def test_missing_check_still_preserves_persistent_and_recovered_checks(self):
        result, provider = investigate_pair(
            {"persist": "failure", "audit": "failure", "orphan": "success"},
            {"persist": "failure", "audit": "success"})
        self.assertEqual(len(provider.calls), 4)
        row = result["investigations"][0]
        self.assertEqual(row["follow_up_kind"], "EVIDENCE_GAP_REVALIDATION")
        self.assertEqual(set(row["check_names"]), {"audit", "persist", "orphan"})
        self.assertEqual(row["check_evidence_classes"], {
            "orphan": "EVIDENCE_GAP_REVALIDATION",
            "persist": "PERSISTENT_ADVERSE_OBSERVED",
            "audit": "RECOVERY_OBSERVED_NOT_RESOLUTION"
        })
        statuses = {x["name"]: x["outcome"] for x in row["checks"]}
        self.assertEqual(statuses["persist"], "STILL_ADVERSE")
        self.assertEqual(statuses["audit"], "SUCCESS_OBSERVED_NOT_RESOLUTION")
        self.assertEqual(statuses["orphan"],
                         "UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK")
        public = summarize(result, SOURCE, *["success"] * 4)
        self.assertEqual(public["observed_check_evidence_classes"], {
            "EVIDENCE_GAP_REVALIDATION": 1,
            "PERSISTENT_ADVERSE_OBSERVED": 1,
            "RECOVERY_OBSERVED_NOT_RESOLUTION": 1
        })
        lines = "\n".join(investigation_summary_lines(result))
        for class_name in row["check_evidence_classes"].values():
            self.assertIn(class_name, lines)
        self.assertIn("NOT root cause", lines)

    def test_unknown_explicit_class_fails_closed_for_public_summary(self):
        result, _ = investigate_pair(
            {"persist": "failure", "audit": "failure"},
            {"persist": "failure", "audit": "success"})
        forged = copy.deepcopy(result)
        forged["investigations"][0]["checks"][0][
            "original_evidence_class"] = "UNAUTHORIZED_DOWNSTREAM_ACTION"
        public = summarize(forged, SOURCE, *["success"] * 4)
        self.assertEqual(public["status"], "BLOCKED_NO_VERIFIED_INVESTIGATION")
        self.assertEqual(public["observed_check_evidence_classes"], {})
        self.assertFalse(public["execution_authority"])

    def test_previous_receipts_without_optional_class_remain_readable(self):
        from test_brain_sidecar import observation
        public = summarize(observation(), SOURCE, *["success"] * 4)
        self.assertEqual(public["status"], "OBSERVED_READ_ONLY")
        self.assertEqual(public["observed_check_evidence_classes"],
                         {"INITIAL_ADVERSE_TRANSITION": 1})


if __name__ == "__main__":
    unittest.main()
