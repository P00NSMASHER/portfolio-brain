"""V7 quarantines duplicate CI check names while continuing uniquely sourced checks.

All observations are synthetic but passed through the original hashed SQLite
ledger and canonical report replay; no live mutation or provider write.
"""
import copy
import unittest

from brain.adapters import GitHub
from brain.core import BrainError
from brain.investigate import investigate
from brain.sidecar import summarize
from brain.review import review_lines
from test_brain_evidence_gaps import check, observe, verified, T0, T1
from test_brain_investigate import Transport, REPO, REV, SOURCE, NOW


def test_observation(when, checks):
    return observe(REPO, when, checks)


def c(name, conclusion):
    return check(REPO, name=name, conclusion=conclusion)


def duplicate(name, conclusion="failure"):
    return [c(name, conclusion), c(name, conclusion)]


def get_report(before, after):
    return verified(test_observation(T0, before),
                    test_observation(T1, after))


def provider_for(name, *, conclusion="failure"):
    transport = Transport(conclusion=conclusion)
    if name != "validate":
        transport.check_mutation = lambda row: row.update(name=name)
    return transport


def run_case(report, history, name="validate"):
    before = copy.deepcopy((report, history))
    provider = provider_for(name)
    receipt = investigate(report, history=history,
                          api=GitHub(transport=provider), now=NOW)
    assert (report, history) == before
    return receipt, provider


class QuarantinedCheckNamesTests(unittest.TestCase):
    def test_unique_new_failure_survives_unrelated_duplicate_ci_names(self):
        before = [c("validate", "success")] + duplicate("noise", "failure")
        after = [c("validate", "failure")] + duplicate("noise", "failure")
        report, history = get_report(before, after)
        change = report["repository_changes"][0]
        self.assertEqual(change["check_comparison"],
                         "PARTIAL_AMBIGUOUS_CHECK_NAMES")
        self.assertEqual([x["name"] for x in change["check_deteriorations"]],
                         ["validate"])
        receipt, transport = run_case(report, history)
        self.assertEqual(receipt["status"], "READ_ONLY_REVALIDATION_COMPLETE")
        self.assertEqual(len(transport.calls), 4)
        self.assertEqual(receipt["requests_used"], 4)
        self.assertEqual(receipt["eligible_count"], 1)
        self.assertEqual(receipt["investigations"][0]["check_names"], ["validate"])
        self.assertEqual(receipt["investigations"][0]["checks"][0]["outcome"],
                         "STILL_ADVERSE")
        self.assertIs(receipt["investigations"][0]["partial_check_coverage"], True)
        self.assertFalse(receipt["root_cause_verified"])
        self.assertEqual(receipt["events_written"], 0)
        public = summarize(receipt, SOURCE, *["success"] * 4)
        self.assertEqual(public["status"], "PARTIAL_READ_ONLY")
        self.assertEqual(public["partial_check_coverage_repositories"], 1)
        self.assertNotIn("noise", str(public))
        human = "\n".join(review_lines(receipt))
        self.assertIn("partial original ci check-name coverage", human.lower())
        self.assertIn("NEW_ADVERSE_CHECK", human)
        self.assertNotIn("noise", human)

    def test_persistent_unique_failure_survives_duplicated_unrelated_check(self):
        before = [c("audit", "failure")] + duplicate("noise", "success")
        after = [c("audit", "failure")] + duplicate("noise", "failure")
        report, history = get_report(before, after)
        self.assertEqual(report["repository_changes"][0]["check_comparison"],
                         "PARTIAL_AMBIGUOUS_CHECK_NAMES")
        receipt, provider = run_case(report, history, "audit")
        self.assertEqual(receipt["investigations"][0]["check_names"], ["audit"])
        self.assertEqual(receipt["investigations"][0]["follow_up_kind"],
                         "PERSISTENT_ADVERSE_OBSERVED")
        self.assertIs(receipt["investigations"][0]["partial_check_coverage"], True)
        self.assertEqual(len(provider.calls), 4)
        self.assertEqual(summarize(receipt, SOURCE, *["success"] * 4)["status"],
                         "PARTIAL_READ_ONLY")

    def test_unambiguous_recovery_survives_unrelated_name_duplicates(self):
        report, history = get_report(
            [c("validate", "failure")] + duplicate("noise"),
            [c("validate", "success")] + duplicate("noise"),
        )
        receipt, provider = run_case(report, history)
        self.assertEqual(len(provider.calls), 4)
        self.assertEqual(receipt["investigations"][0]["check_names"], ["validate"])
        self.assertEqual(receipt["investigations"][0]["follow_up_kind"],
                         "RECOVERY_OBSERVED_NOT_RESOLUTION")
        self.assertIs(receipt["investigations"][0]["partial_check_coverage"], True)
        self.assertFalse(receipt["root_cause_verified"])

    def test_ambiguous_current_name_never_inferred_missing_or_recovered(self):
        report, history = get_report(
            [c("validate", "success"), c("gap", "failure")],
            [c("validate", "success")] + duplicate("gap"),
        )
        receipt, transport = run_case(report, history)
        self.assertEqual(receipt["status"], "NO_ELIGIBLE_FAILURES")
        self.assertEqual(transport.calls, [])

    def test_ambiguous_baseline_never_generates_comparable_transition(self):
        report, history = get_report(
            [c("validate", "success")] + duplicate("gap", "failure"),
            [c("validate", "success"), c("gap", "success")],
        )
        receipt, transport = run_case(report, history)
        self.assertEqual(receipt["status"], "NO_ELIGIBLE_FAILURES")
        self.assertEqual(transport.calls, [])

    def test_only_duplicate_checks_never_trigger_provider_request(self):
        report, history = get_report(duplicate("validate", "success"),
                                     duplicate("validate", "failure"))
        receipt, transport = run_case(report, history)
        self.assertEqual(receipt["status"], "NO_ELIGIBLE_FAILURES")
        self.assertEqual(transport.calls, [])

    def test_partial_comparison_never_infers_root_cause_or_full_review_coverage(self):
        report, history = get_report(
            [c("validate", "success")] + duplicate("noise"),
            [c("validate", "failure")] + duplicate("noise"),
        )
        receipt, _ = run_case(report, history)
        public = summarize(receipt, SOURCE, *["success"] * 4)
        self.assertEqual(public["observed_outcomes"], {"STILL_ADVERSE": 1})
        self.assertEqual(public["checked"], 1)
        self.assertEqual(public["partial_check_coverage_repositories"], 1)
        self.assertFalse(public["production_accepted"])
        self.assertFalse(public["execution_authority"])
        self.assertFalse(public["root_cause_verified"])

    def test_forged_partial_flag_boolean_is_rejected(self):
        report, history = get_report(
            [c("validate", "success")] + duplicate("noise"),
            [c("validate", "failure")] + duplicate("noise"),
        )
        receipt, _ = run_case(report, history)
        forged = copy.deepcopy(receipt)
        forged["investigations"][0]["partial_check_coverage"] = 1
        public = summarize(forged, SOURCE, *["success"] * 4)
        self.assertEqual(public["status"], "BLOCKED_NO_VERIFIED_INVESTIGATION")

    def test_untrusted_report_projection_quarantine_cannot_trigger_read(self):
        report, history = get_report(
            [c("validate", "success")] + duplicate("noise"),
            [c("validate", "failure")] + duplicate("noise"),
        )
        forged = copy.deepcopy(report)
        forged["repository_changes"][0]["current_revision"] = "c" * 40
        api = provider_for("validate")
        with self.assertRaises(BrainError):
            investigate(forged, history=history,
                        api=GitHub(transport=api), now=NOW)
        self.assertEqual(api.calls, [])

    def test_partial_comparison_merges_all_unique_check_signals_in_one_read(self):
        from test_brain_same_revision_all_signals import transport
        before = [
            c("validate", "success"), c("persist", "failure"),
            c("audit", "failure"), c("orphan", "success"),
        ] + duplicate("ambiguous", "failure")
        after = [
            c("validate", "failure"), c("persist", "failure"),
            c("audit", "success"),
        ] + duplicate("ambiguous", "failure")
        report, history = get_report(before, after)
        self.assertEqual(report["repository_changes"][0]["check_comparison"],
                         "PARTIAL_AMBIGUOUS_CHECK_NAMES")
        provider = transport()
        original = copy.deepcopy((report, history))
        receipt = investigate(report, history=history, now=NOW,
                              api=GitHub(transport=provider))
        self.assertEqual((report, history), original)
        self.assertEqual(len(provider.calls), 4)
        self.assertEqual(receipt["requests_used"], 4)
        row = receipt["investigations"][0]
        self.assertEqual(row["check_names"],
                         ["audit", "orphan", "persist", "validate"])
        self.assertNotIn("ambiguous", row["check_names"])
        self.assertTrue(row["partial_check_coverage"])
        self.assertEqual(row["check_evidence_classes"], {
            "validate": "INITIAL_ADVERSE_TRANSITION",
            "persist": "PERSISTENT_ADVERSE_OBSERVED",
            "audit": "RECOVERY_OBSERVED_NOT_RESOLUTION",
            "orphan": "EVIDENCE_GAP_REVALIDATION",
        })
        public = summarize(receipt, SOURCE, *["success"] * 4)
        self.assertEqual(public["status"], "PARTIAL_READ_ONLY")
        self.assertEqual(public["checked"], 1)
        self.assertEqual(public["partial_check_coverage_repositories"], 1)
        self.assertIs(public["root_cause_verified"], False)
        self.assertNotIn("ambiguous", str(public))

    def test_quarantined_untrusted_name_never_enters_private_review(self):
        unsafe = "<script> **invoke** [jump](https://untrusted.invalid)"
        report, history = get_report(
            [c("validate", "success")] + duplicate(unsafe, "failure"),
            [c("validate", "failure")] + duplicate(unsafe, "failure"),
        )
        receipt, _ = run_case(report, history)
        packet = "\n".join(review_lines(receipt))
        self.assertNotIn("<script>", packet)
        self.assertNotIn("invoke", packet)
        self.assertIn("partial original ci check-name coverage", packet.lower())
        self.assertIn("validate", packet)
        self.assertNotIn(unsafe, str(summarize(
            receipt, SOURCE, *["success"] * 4)))

    def test_normal_unambiguous_comparison_remains_complete(self):
        report, history = get_report(
            [c("validate", "success")], [c("validate", "failure")],
        )
        receipt, provider = run_case(report, history)
        self.assertEqual(len(provider.calls), 4)
        self.assertIs(receipt["investigations"][0]["partial_check_coverage"], False)
        public = summarize(receipt, SOURCE, *["success"] * 4)
        self.assertEqual(public["status"], "PARTIAL_READ_ONLY")
        self.assertEqual(public["partial_check_coverage_repositories"], 0)


if __name__ == "__main__":
    unittest.main()
