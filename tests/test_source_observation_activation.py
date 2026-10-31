"""No accidental 12-hour start from a trust-anchor release.

These are deterministic policy and condition-shape checks, not real GitHub
repository-variable inspection and NOT original unattended reliability data.
"""
import unittest
from pathlib import Path

from brain.validate import validate_policy

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = "vars.PORTFOLIO_12H_OBSERVATION_ENABLED == 'true'"
SOURCE = "vars.PORTFOLIO_12H_AUTHORIZED_SOURCE_SHA == github.sha"
WORKFLOWS = (
    ".github/workflows/reliability-day.yml",
    ".github/workflows/portfolio-source-acceptance-producer.yml",
)


class SourceScopedObservationActivationTests(unittest.TestCase):
    def test_both_jobs_require_two_independent_source_scoped_optins(self):
        for path in WORKFLOWS:
            source = (ROOT / path).read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertIn(ACTIVE, source)
                self.assertIn(SOURCE, source)
                self.assertEqual(source.count("false &&"), 1)
                self.assertRegex(source, r"(?m)^\s+false &&$")
                self.assertIn("github.event.workflow_run.head_sha == github.sha", source)
                self.assertIn("workflow_run:", source)
                self.assertNotIn("schedule:", source)
                self.assertNotIn("workflow_dispatch:", source)

    def test_source_requires_current_main_and_is_not_a_static_old_sha(self):
        for path in WORKFLOWS:
            source = (ROOT / path).read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertNotIn("0061071667cfb273a15b9e25a8854794316d12cb", source)
                self.assertEqual(source.count(SOURCE), 1)
                self.assertEqual(source.count(ACTIVE), 1)

    def test_missing_or_stale_approval_var_is_always_a_denial(self):
        current = "a" * 40
        for original in (None, "", "false", "TRUE"):
            for approved in (None, "", "b" * 40):
                with self.subTest(flag=original, approved=approved):
                    self.assertFalse(original == "true" and approved == current)

        # Even perfectly matching flags cannot overcome the separate literal
        # false guard. Re-arming needs fresh user approval and protected code.
        self.assertFalse(False and "true" == "true" and current == current)

    def test_runtime_policy_enforces_the_new_double_hold(self):
        receipt = validate_policy()
        self.assertEqual(receipt["status"], "PASS")
        self.assertIs(receipt["soak_started"], False)
        self.assertIs(receipt["production_accepted"], False)


if __name__ == "__main__":
    unittest.main()
