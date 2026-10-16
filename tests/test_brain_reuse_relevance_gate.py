"""Negative and positive controls for source-verified code relevance."""
import unittest
from brain.projects import _has_bounded_domain_reuse_evidence


class SourceRelevanceTests(unittest.TestCase):
    def test_unrelated_source_has_no_reuse_evidence(self):
        source = {"matched_terms": [], "test_paths": []}
        self.assertFalse(_has_bounded_domain_reuse_evidence(source))

    def test_code_terms_and_test_path_are_required_together(self):
        tested = {
            "matched_terms": ["permit", "license"],
            "test_paths": ["tests/test_permit_license.py"],
        }
        self.assertTrue(_has_bounded_domain_reuse_evidence(tested))
        self.assertFalse(_has_bounded_domain_reuse_evidence(
            {**tested, "test_paths": []}
        ))
        self.assertFalse(_has_bounded_domain_reuse_evidence(
            {**tested, "matched_terms": ["permit"]}
        ))
        self.assertFalse(_has_bounded_domain_reuse_evidence(
            {**tested, "matched_terms": ["permit", "Permit"]}
        ))

    def test_missing_and_malformed_evidence_stays_unqualified(self):
        for row in ({}, {"matched_terms": "permit", "test_paths": []},
                    {"matched_terms": [123, "permit"], "test_paths": [1]}):
            with self.subTest(row=row):
                self.assertFalse(_has_bounded_domain_reuse_evidence(row))


if __name__ == "__main__":
    unittest.main()
