"""End-to-end private report rendering of bounded V7 operator review proposals."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from brain.render import write_report
from test_brain_review import check, observation, receipt


@unittest.skipUnless(os.name == "posix", "Private report mode validation requires POSIX")
class PrivateReviewReportTests(unittest.TestCase):
    def test_source_bound_packet_is_in_private_md_html_without_mutating_machine_receipt(self):
        report = receipt(observation(check("validate")))
        before = json.dumps(report, sort_keys=True)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "private"
            write_report(report, output)
            saved = json.loads((output / "report.json").read_text())
            self.assertEqual(json.dumps(saved, sort_keys=True), before)
            markdown = (output / "report.md").read_text()
            html = (output / "report.html").read_text()
            self.assertIn("Source-bound incident review packet", markdown)
            self.assertIn("NEW_ADVERSE_CHECK", markdown)
            self.assertIn("NOT repairs", markdown)
            self.assertIn("NEW_ADVERSE_CHECK", html)
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            self.assertEqual((output / "report.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual((output / "report.md").stat().st_mode & 0o777, 0o600)
            self.assertEqual((output / "report.html").stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.dumps(report, sort_keys=True), before)

    def test_cross_repo_ci_coincidences_private_only_and_machine_json_unchanged(self):
        from test_brain_review_case_identity import real_check, row, OTHER
        from test_brain_review import REPOS, SHA
        from brain.sidecar import summarize
        report = receipt(
            row(REPOS[0], real_check(REPOS[0])),
            row(OTHER, real_check(OTHER)),
        )
        before = json.dumps(report, sort_keys=True)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "private"
            write_report(report, output)
            self.assertEqual(json.dumps(report, sort_keys=True), before)
            self.assertEqual(
                json.dumps(json.loads((output / "report.json").read_text()),
                           sort_keys=True), before
            )
            markdown = (output / "report.md").read_text()
            html = (output / "report.html").read_text()
            self.assertIn("Source-bound incident review packet", markdown)
            self.assertIn("Shared check-name review (noncausal)", markdown)
            self.assertIn("Case reference:", markdown)
            self.assertIn("not evidence of a shared cause", markdown)
            self.assertIn("Shared check-name review", html)
            self.assertEqual((output / "report.json").stat().st_mode & 0o777, 0o600)
        public = summarize(report, SHA, *["success"] * 4)
        self.assertEqual(public["status"], "OBSERVED_READ_ONLY")
        self.assertNotIn("same_name_adverse_coincidences", public)
        self.assertNotIn("check_name", public)
        self.assertNotIn(REPOS[0], str(public))
        self.assertNotIn(OTHER, str(public))

    def test_untrusted_check_names_are_escaped_in_private_bundle(self):
        untrusted = "<script> **danger** [x](https://evil.test)"
        report = receipt(observation(check(untrusted)))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "private"
            write_report(report, output)
            markup = (output / "report.md").read_text()
            html = (output / "report.html").read_text()
            self.assertNotIn("<script>", markup)
            self.assertNotIn("<script>", html)
            self.assertIn(r"\<script\>", markup)
            self.assertIn("&lt;script", html)


if __name__ == "__main__":
    unittest.main()
