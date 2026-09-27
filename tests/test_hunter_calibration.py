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

    def test_negative_controls_cover_each_current_structural_rejection_reason(self):
        report=run_calibration()
        reasons={
            row["actual_reason"]
            for row in report["results"]
            if row["case_class"]=="NEGATIVE"
        }
        self.assertEqual(reasons,{
            "NO_IMPLEMENTATION_PATHS",
            "NO_TEST_OR_REGRESSION_PATHS",
            "NO_STRUCTURAL_CAPABILITY_SIGNAL",
        })

    def test_ambiguous_controls_are_explicit_and_do_not_count_as_positive_gold(self):
        report=run_calibration()
        ambiguous=[row for row in report["results"] if row["case_class"]=="AMBIGUOUS"]
        self.assertGreaterEqual(len(ambiguous),3)
        self.assertTrue(all(row["ambiguity"] for row in ambiguous))
        self.assertTrue(any(row["actual_disposition"]=="DUPLICATE" for row in ambiguous))
        self.assertTrue(any(
            row["actual_disposition"]=="RETAIN"
            and row["structural"]["source_path_count"]>0
            and row["structural"]["test_path_count"]>0
            for row in ambiguous
        ))

    def test_calibration_fails_closed_when_a_gold_expectation_is_corrupted(self):
        corpus=copy.deepcopy(load_corpus())
        corpus["cases"][0]["expected_disposition"]="REJECT"
        report=run_calibration(corpus)
        self.assertEqual(report["status"],"FAIL")
        self.assertIn(corpus["cases"][0]["case_id"],report["failed_case_ids"])


if __name__=="__main__":
    unittest.main()
