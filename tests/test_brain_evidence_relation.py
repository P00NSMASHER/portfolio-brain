"""V7 check-state relations: original source vs one GET-only recheck.

All fixtures originate from replay-verified synthetic original SQLite, with
fake public GitHub responses. Relation enums are advisory observations only.
"""
import copy
import json
import unittest

from brain.adapters import GitHub
from brain.evidence_relation import source_followup_relation, allowed_relations
from brain.investigate import investigate
from brain.review import review_packet, review_lines
from brain.sidecar import summarize
from brain.render import investigation_summary_lines
from test_brain_evidence_gaps import observe, check, verified, T0, T1
from test_brain_investigate import REPO, REV, NOW, SOURCE, Transport


def snap(when, states):
    return observe(REPO, when, [
        check(REPO, name=name, conclusion=conclusion)
        for name, conclusion in sorted(states.items())
    ])


def analyze(old, new, *, current="failure", extras=()):
    report, history = verified(snap(T0, old), snap(T1, new))
    frozen = copy.deepcopy((report, history))
    provider = Transport(conclusion=current)
    provider.extra_checks = [
        {"id": index + 30, "name": name, "status": "completed",
         "conclusion": conclusion, "head_sha": REV,
         "html_url": f"https://github.com/{REPO}/actions/runs/89/job/{index + 30}"}
        for index, (name, conclusion) in enumerate(extras)
    ]
    result = investigate(report, history=history,
                         api=GitHub(transport=provider), now=NOW)
    assert (report, history) == frozen
    return result, provider


def first(receipt):
    return receipt["investigations"][0]["checks"][0]


class CheckRelationTests(unittest.TestCase):
    def test_one_fixed_label_per_source_class_and_observed_status(self):
        classes = (
            ("INITIAL_ADVERSE_TRANSITION", "NEW_ADVERSE_REOBSERVED"),
            ("PERSISTENT_ADVERSE_OBSERVED", "PERSISTENT_ADVERSE_REOBSERVED"),
            ("UNBASELINED_ADVERSE_OBSERVED", "UNBASELINED_ADVERSE_REOBSERVED"),
            ("RECOVERY_OBSERVED_NOT_RESOLUTION", "RECOVERY_NOT_REPRODUCED"),
            ("EVIDENCE_GAP_REVALIDATION", "GAP_RECHECK_ADVERSE"),
        )
        self.assertEqual(len(allowed_relations()), 9)
        for original, relation in classes:
            with self.subTest(original=original):
                self.assertEqual(
                    source_followup_relation(original, "STILL_ADVERSE"), relation)
                self.assertIn(relation, allowed_relations())
        self.assertEqual(
            source_followup_relation("RECOVERY_OBSERVED_NOT_RESOLUTION",
                                     "SUCCESS_OBSERVED_NOT_RESOLUTION"),
            "RECOVERY_REOBSERVED_NOT_FIX_VERIFIED")
        self.assertEqual(
            source_followup_relation("EVIDENCE_GAP_REVALIDATION",
                                     "SUCCESS_OBSERVED_NOT_RESOLUTION"),
            "GAP_RECHECK_SUCCESS_NOT_FIX_VERIFIED")
        for original in ("INITIAL_ADVERSE_TRANSITION",
                         "PERSISTENT_ADVERSE_OBSERVED",
                         "UNBASELINED_ADVERSE_OBSERVED"):
            self.assertEqual(
                source_followup_relation(original, "SUCCESS_OBSERVED_NOT_RESOLUTION"),
                "ORIGINAL_ADVERSE_NOT_REOBSERVED")
        for current in ("CHECK_NOT_COMPLETED",
                        "UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK",
                        "OTHER_CONCLUSION_NOT_RESOLUTION"):
            self.assertEqual(
                source_followup_relation("INITIAL_ADVERSE_TRANSITION", current),
                "CURRENT_EVIDENCE_INCOMPLETE")

    def test_persistent_adverse_and_prior_recovery_that_reversed_both_rechecked(self):
        receipt, provider = analyze(
            {"validate": "failure", "audit": "failure"},
            {"validate": "failure", "audit": "success"},
            extras=[("audit", "failure")])
        self.assertEqual(len(provider.calls), 4)
        self.assertEqual(receipt["requests_used"], 4)
        row = receipt["investigations"][0]
        self.assertEqual({
            item["name"]: item["source_followup_relation"] for item in row["checks"]
        }, {
            "validate": "PERSISTENT_ADVERSE_REOBSERVED",
            "audit": "RECOVERY_NOT_REPRODUCED"
        })
        self.assertFalse(receipt["root_cause_verified"])
        public = summarize(receipt, SOURCE, *["success"] * 4)
        self.assertEqual(public["observed_source_followup_relations"], {
            "PERSISTENT_ADVERSE_REOBSERVED": 1,
            "RECOVERY_NOT_REPRODUCED": 1,
        })
        self.assertNotIn(REPO, json.dumps(public))
        self.assertEqual(public["github_mutations"], 0)
        packet = review_packet(receipt)
        categories = {i["check_name"]: i["category"] for i in packet["items"]}
        self.assertEqual(categories["audit"], "RECOVERY_NOT_REPRODUCED")
        self.assertTrue(any("RECOVERY_NOT_REPRODUCED" in line
                            for line in review_lines(receipt)))

    def test_original_recovery_reobserved_green_not_a_confirmed_fix(self):
        receipt, provider = analyze(
            {"validate": "failure"}, {"validate": "success"}, current="success")
        self.assertEqual(first(receipt)["source_followup_relation"],
                         "RECOVERY_REOBSERVED_NOT_FIX_VERIFIED")
        public = summarize(receipt, SOURCE, *["success"] * 4)
        self.assertEqual(public["observed_source_followup_relations"],
                         {"RECOVERY_REOBSERVED_NOT_FIX_VERIFIED": 1})
        self.assertFalse(public["root_cause_verified"])
        self.assertFalse(public["authorization_granted"])

    def test_original_deterioration_green_is_not_verified_resolution(self):
        receipt, _ = analyze({"validate": "success"},
                              {"validate": "failure"}, current="success")
        self.assertEqual(first(receipt)["source_followup_relation"],
                         "ORIGINAL_ADVERSE_NOT_REOBSERVED")
        human = review_packet(receipt)
        self.assertEqual(human["items"][0]["category"],
                         "ORIGINAL_ADVERSE_NOT_REOBSERVED")
        self.assertFalse(human["incident_closed"])
        self.assertFalse(human["execution_authority"])
        lines = "\n".join(investigation_summary_lines(receipt))
        self.assertIn("ORIGINAL_ADVERSE_NOT_REOBSERVED", lines)
        self.assertIn("NOT root cause", lines)

    def test_unbaselined_first_failure_green_has_no_fabricated_prior_success(self):
        receipt, _ = analyze({}, {"validate": "failure"}, current="success")
        self.assertEqual(first(receipt)["original_evidence_class"],
                         "UNBASELINED_ADVERSE_OBSERVED")
        self.assertEqual(first(receipt)["source_followup_relation"],
                         "ORIGINAL_ADVERSE_NOT_REOBSERVED")
        public = summarize(receipt, SOURCE, *["success"] * 4)
        self.assertEqual(public["status"], "PARTIAL_READ_ONLY")
        self.assertEqual(public["observed_source_followup_relations"],
                         {"ORIGINAL_ADVERSE_NOT_REOBSERVED": 1})

    def test_original_gap_later_adverse_and_success_are_not_claimed_comparable(self):
        for conclusion, expected in (
            ("failure", "GAP_RECHECK_ADVERSE"),
            ("success", "GAP_RECHECK_SUCCESS_NOT_FIX_VERIFIED"),
        ):
            with self.subTest(conclusion=conclusion):
                receipt, _ = analyze({"validate": "failure"}, {},
                                     current=conclusion)
                self.assertEqual(first(receipt)["source_followup_relation"], expected)

    def test_mixed_four_check_classes_preserved_in_one_original_request(self):
        receipt, provider = analyze(
            {"validate":"success","persist":"failure",
             "audit":"failure","orphan":"success"},
            {"validate":"failure","persist":"failure",
             "audit":"success"},
            extras=[("persist","failure"),("audit","success")])
        self.assertEqual(len(provider.calls), 4)
        checks = {c["name"]: c["source_followup_relation"]
                  for c in receipt["investigations"][0]["checks"]}
        self.assertEqual(checks, {
            "validate":"NEW_ADVERSE_REOBSERVED",
            "persist":"PERSISTENT_ADVERSE_REOBSERVED",
            "audit":"RECOVERY_REOBSERVED_NOT_FIX_VERIFIED",
            "orphan":"CURRENT_EVIDENCE_INCOMPLETE",
        })
        public = summarize(receipt, SOURCE, *["success"]*4)
        self.assertEqual(public["status"], "PARTIAL_READ_ONLY")
        self.assertEqual(sum(public["observed_source_followup_relations"].values()),4)
        self.assertNotIn("orphan", json.dumps(public))
        self.assertEqual(receipt["events_written"], 0)

    def test_tampered_source_relation_or_original_class_fails_closed(self):
        receipt, _ = analyze({"validate":"success"}, {"validate":"failure"})
        attacks = [
            "RECOVERY_NOT_REPRODUCED", "FIX_VERIFIED",
            "", None, False, 0, ["NEW_ADVERSE_REOBSERVED"]
        ]
        for altered in attacks:
            with self.subTest(altered=altered):
                forged = copy.deepcopy(receipt)
                forged["investigations"][0]["checks"][0][
                    "source_followup_relation"
                ] = altered
                safe = summarize(forged, SOURCE, *["success"]*4)
                self.assertEqual(safe["status"], "BLOCKED_NO_VERIFIED_INVESTIGATION")
                self.assertEqual(safe["observed_source_followup_relations"], {})
                self.assertFalse(safe["execution_authority"])
                with self.assertRaises(ValueError):
                    review_packet(forged)
        changed = copy.deepcopy(receipt)
        changed["investigations"][0]["checks"][0][
            "original_evidence_class"
        ] = "RECOVERY_OBSERVED_NOT_RESOLUTION"
        self.assertEqual(summarize(changed,SOURCE,*["success"]*4)["status"],
                         "BLOCKED_NO_VERIFIED_INVESTIGATION")

    def test_legacy_receipt_without_optional_relation_does_not_invent_counts(self):
        from test_brain_sidecar import observation
        safe = summarize(observation(), SOURCE, *["success"] * 4)
        self.assertEqual(safe["observed_source_followup_relations"], {})
        self.assertEqual(safe["status"], "OBSERVED_READ_ONLY")

    def test_missing_current_check_keeps_incomplete_relation_without_fabricated_fix(self):
        receipt, provider = analyze(
            {"validate":"failure"}, {"validate":"failure"})
        tampered = copy.deepcopy(receipt)
        # Genuine category is derived from a completed original result.
        # Provider revalidation may be missing: this remains incomplete.
        provider2=Transport()
        provider2.check_mutation=lambda x:x.update(name="elsewhere")
        report,history=verified(snap(T0,{"validate":"failure"}),
                                snap(T1,{"validate":"failure"}))
        actual=investigate(report,history=history,
                           api=GitHub(transport=provider2),now=NOW)
        checked=first(actual)
        self.assertEqual(checked["source_followup_relation"],
                         "CURRENT_EVIDENCE_INCOMPLETE")
        self.assertEqual(checked["outcome"],
                         "UNVERIFIED_MISSING_OR_AMBIGUOUS_CHECK")
        self.assertEqual(summarize(actual,SOURCE,*["success"]*4)["status"],
                         "PARTIAL_READ_ONLY")
        self.assertEqual(len(provider2.calls),4)

    def test_helper_rejects_unrecognized_or_malformed_source(self):
        for cls, outcome in (
            ("DELETED_SOURCE", "STILL_ADVERSE"),
            ("INITIAL_ADVERSE_TRANSITION", "AUTO_REPAIR_SUCCEEDED"),
            (False, "STILL_ADVERSE"),
            ("INITIAL_ADVERSE_TRANSITION", None),
        ):
            with self.subTest(cls=cls, outcome=outcome), self.assertRaises(ValueError):
                source_followup_relation(cls, outcome)


if __name__ == "__main__":
    unittest.main()
