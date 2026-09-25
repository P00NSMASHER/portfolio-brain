import unittest

from truth.validate_truth_integration import validate_truth_integration

class TruthConformanceBundleTests(unittest.TestCase):
    def test_truth_integration_bundle_validates(self):
        result=validate_truth_integration()
        self.assertEqual(result["source_revision"],"b906d3f12aa9ad1bf443c41ff5281f38f5eeab0a")
        self.assertEqual(result["source_blob_sha"],"9b3eaa9412ece784c05e9c93dfcea04e1ec96105")
        self.assertEqual(result["verdicts"],4)
        self.assertEqual(result["finding_statuses"],8)
        self.assertEqual(result["projection_states"],["CONTRADICTED","STALE","UNKNOWN","VERIFIED"])

if __name__=="__main__":
    unittest.main()
