import copy
import unittest

from hunting.calibration import load_corpus, run_calibration


class HunterCalibrationTests(unittest.TestCase):
    def test_corpus_has_required_positive_negative_and_ambiguous_controls(self):
        corpus=load_corpus()
        counts={name:0 for name in ("POSITIVE","NEGATIVE","AMBIGUOUS")}
        for case in corpus["cases"]:
            counts[case["case_class"]]+=1
        self.assertGreaterEqual(counts["POSITIVE"],10)
        self.assertGreaterEqual(counts["NEGATIVE"],10)
        self.assertGreaterEqual(counts["AMBIGUOUS"],3)

    def test_current_classifier_passes_entire_calibration_corpus(self):
        report=run_calibration()
        self.assertEqual(report["status"],"PASS")
        self.assertEqual(report["positive_retained"],report["positive_cases"])
        self.assertEqual(report["negative_rejected"],report["negative_cases"])
        self.assertEqual(report["ambiguous_matched"],report["ambiguous_cases"])
        self.assertEqual(report["failed_case_ids"],[])
        self.assertEqual(report["network_calls"],0)
        self.assertEqual(report["state_mutations"],0)

    def test_negative_controls_cover_only_the_remaining_structural_hard_reject(self):
        report=run_calibration()
        reasons={
            row["actual_reason"]
            for row in report["results"]
            if row["case_class"]=="NEGATIVE"
        }
        self.assertEqual(reasons,{"NO_IMPLEMENTATION_PATHS"})
        self.assertTrue(all(
            row["decision_trace"]["hard_gate_status"]=="REJECT"
            for row in report["results"]
            if row["case_class"]=="NEGATIVE"
        ))

    def test_ambiguous_controls_prove_soft_signals_rank_without_rejecting(self):
        report=run_calibration()
        ambiguous=[row for row in report["results"] if row["case_class"]=="AMBIGUOUS"]
        self.assertGreaterEqual(len(ambiguous),5)
        self.assertTrue(all(row["ambiguity"] for row in ambiguous))
        self.assertTrue(any(row["actual_disposition"]=="DUPLICATE" for row in ambiguous))
        retained=[row for row in ambiguous if row["actual_disposition"]=="RETAIN"]
        self.assertTrue(any(row["actual_rank_band"]=="MEDIUM" for row in retained))
        self.assertTrue(any(row["actual_rank_band"]=="LOW" for row in retained))
        self.assertTrue(any("NO_TEST_OR_REGRESSION_PATHS" in row["actual_soft_signals"] for row in retained))
        self.assertTrue(any("NO_STRUCTURAL_CAPABILITY_SIGNAL" in row["actual_soft_signals"] for row in retained))
        self.assertTrue(all(row["decision_trace"]["soft_signals_do_not_reject"] for row in retained))

    def test_positive_controls_remain_high_ranked_and_all_retain(self):
        report=run_calibration()
        positives=[row for row in report["results"] if row["case_class"]=="POSITIVE"]
        self.assertTrue(positives)
        self.assertTrue(all(row["actual_disposition"]=="RETAIN" for row in positives))
        self.assertTrue(all(row["actual_rank_band"]=="HIGH" for row in positives))
        self.assertTrue(all(row["actual_rank_score"]>=8 for row in positives))

    def test_calibration_fails_closed_when_a_gold_expectation_is_corrupted(self):
        corpus=copy.deepcopy(load_corpus())
        corpus["cases"][0]["expected_disposition"]="REJECT"
        report=run_calibration(corpus)
        self.assertEqual(report["status"],"FAIL")
        self.assertIn(corpus["cases"][0]["case_id"],report["failed_case_ids"])


if __name__=="__main__":
    unittest.main()
