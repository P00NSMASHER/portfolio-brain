"""Private V7 source reviews must not render attacker-controlled Markdown links."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from brain.render import write_report
from test_brain_triage import candidate, sample_report


@unittest.skipUnless(os.name == "posix", "Private report requires POSIX permissions")
class PrivateSourceReferenceTests(unittest.TestCase):
    def render(self, candidates):
        report = sample_report(candidates=candidates)
        original = copy.deepcopy(report)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "protected"
            write_report(report, out)
            markdown = (out / "report.md").read_text()
            webpage = (out / "report.html").read_text()
            saved = json.loads((out / "report.json").read_text())
            self.assertEqual(saved, original)
            self.assertEqual(report, original)
            self.assertEqual(out.stat().st_mode & 0o777, 0o700)
            self.assertEqual((out / "report.md").stat().st_mode & 0o777, 0o600)
            self.assertEqual((out / "report.json").stat().st_mode & 0o777, 0o600)
            return markdown, webpage

    def test_exact_revision_and_path_remain_reviewable_not_executable(self):
        row = candidate("agent-products", 1)
        markdown, webpage = self.render([row])
        self.assertIn("Reusable code to evaluate", markdown)
        self.assertIn(row["source_ref"], markdown)
        self.assertIn("Exact commit/path link verified", markdown)
        self.assertIn("execution, source rights", markdown)
        self.assertIn("NOT independently verified", markdown)
        self.assertIn(row["source_ref"], webpage)

    def test_untrusted_source_links_omitted_without_losing_valid_source(self):
        good = candidate("school-tools", 2)
        row = candidate("agent-products", 1)
        altered = [
            {**row, "source_ref": row["source_ref"] + "?redirect=https://evil.example"},
            {**row, "source_ref": row["source_ref"] + "#private"},
            {**row, "source_ref": row["source_ref"].replace("/blob/", "/tree/")},
            {**row, "source_ref": row["source_ref"].replace("source/research", "evil/research")},
            {**row, "key": "wrong:key"},
            {**row, "path": "src/other.py"},
            good,
        ]
        markdown, webpage = self.render(altered)
        self.assertIn(good["source_ref"], markdown)
        self.assertNotIn("?redirect=", markdown)
        self.assertNotIn("#private", markdown)
        self.assertNotIn("evil/research/blob", markdown)
        self.assertIn("6 unverified candidate source link(s) omitted", markdown)
        self.assertNotIn("https://evil.example", markdown)
        self.assertNotIn("https://evil.example", webpage)

    def test_untrusted_target_and_license_are_escaped_in_private_report(self):
        row = candidate("agent-products", 1)
        row["license"] = "<script>[bad](https://evil.invalid)</script>"
        row["target"] = "<script>*pwn*</script>"
        row["utility_evidence"] = "[Open](https://evil.invalid) malicious_value"
        markdown, webpage = self.render([row])
        self.assertNotIn("<script>", markdown)
        self.assertNotIn("[bad]", markdown)
        self.assertNotIn("*pwn*", markdown)
        self.assertIn(r"\<script\>", markdown)
        self.assertIn(r"\[bad\]", markdown)
        self.assertIn(r"\*pwn\*", markdown)
        self.assertNotIn("<script>", webpage)
        self.assertNotIn('href="https://evil.invalid"', webpage)

    def test_only_invalid_candidates_do_not_publish_unsafe_link(self):
        row = candidate("freight-recovery", 3)
        altered = {**row, "source_ref": "https://evil.example/path"}
        markdown, webpage = self.render([altered])
        self.assertIn("1 unverified candidate source link(s) omitted", markdown)
        self.assertNotIn("https://evil.example", markdown)
        self.assertNotIn("https://evil.example", webpage)

    def test_malformed_candidates_do_not_break_valid_private_review(self):
        good = candidate("school-tools", 2)
        markdown, _ = self.render([
            None, True, ["list"], {**good, "source_ref": None},
            {**good, "key": 4}, good
        ])
        self.assertIn(good["source_ref"], markdown)
        self.assertIn("5 unverified candidate source link(s) omitted", markdown)


if __name__ == "__main__":
    unittest.main()
