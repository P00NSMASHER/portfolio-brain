"""A merged release does not require a manually activated timed observation."""
from pathlib import Path
import unittest

from verification import independent_verifier as iv
ROOT = Path(__file__).resolve().parents[1]
class NoObservationActivationTests(unittest.TestCase):
    def test_no_timed_workflows_or_per_sha_variables(self):
        for path in ("reliability-day.yml", "portfolio-source-acceptance-producer.yml",
                     "portfolio-source-acceptance.yml"):
            self.assertFalse((ROOT/".github/workflows"/path).exists())
        body=(ROOT/"verification/independent_verifier.py").read_text()
        self.assertNotIn("verify_predecessor_acceptance",body)
        self.assertNotIn("PORTFOLIO_12H_",body)

    def test_release_retains_immutable_exact_head_and_independent_issuers(self):
        self.assertEqual(iv.CHECK_NAME,"portfolio-phase1-gate")
        self.assertEqual(iv.VERIFIER_APP_ID,5121826)
        self.assertEqual(iv.FOUNDATION_APP_ID,15368)
        self.assertIn("verification/independent_verifier.py",
                      iv.IMMUTABLE_TRUST_ANCHORS)
        self.assertTrue(iv._sha40("a"*40))
        self.assertFalse(iv._sha40("a"*39))

if __name__=="__main__":
    unittest.main()
