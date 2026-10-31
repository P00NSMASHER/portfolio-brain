"""Bounded core preflight: hosted slowdown cannot become unverified PASS."""
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from brain import __main__ as cli
from brain.core import BrainError

SHA = "b" * 40


class PreflightTimeoutTests(unittest.TestCase):
    def test_completed_slow_suite_needs_full_positive_evidence(self):
        with (
            patch.object(cli, "source_sha", return_value=SHA),
            patch("brain.validate.validate_policy"),
            patch("brain.__main__.subprocess.run") as runner,
            patch.object(cli, "write_private_test_log") as private_log,
            patch.object(cli, "write_report") as report,
        ):
            runner.return_value = SimpleNamespace(
                returncode=0, stdout="", stderr="Ran 124 tests in 69.4s\\n\\nOK\\n"
            )
            result = cli.preflight("/tmp/preflight", SHA)
            self.assertEqual(runner.call_args.kwargs["timeout"], 120)
            self.assertEqual(result["status"], "PASS")
            self.assertFalse(result["production_accepted"])
            self.assertFalse(result["soak_started"])
            private_log.assert_called_once()
            report.assert_called_once()

    def test_exhausted_timeout_preserves_partial_evidence_and_fails_closed(self):
        with (
            patch.object(cli, "source_sha", return_value=SHA),
            patch("brain.validate.validate_policy"),
            patch("brain.__main__.subprocess.run") as runner,
            patch.object(cli, "write_private_test_log") as private_log,
            patch.object(cli, "write_report") as report,
        ):
            runner.side_effect = subprocess.TimeoutExpired(
                cmd=["python", "-m", "unittest"], timeout=120,
                output=b"Ran 37 preliminary cases", stderr=b"slow runner"
            )
            with self.assertRaisesRegex(BrainError, "PREFLIGHT_TEST_TIMEOUT"):
                cli.preflight("/tmp/preflight", SHA)
            self.assertEqual(runner.call_args.kwargs["timeout"], 120)
            self.assertIn("Ran 37 preliminary cases", private_log.call_args.args[1])
            self.assertIn("slow runner", private_log.call_args.args[1])
            self.assertIn("PREFLIGHT_TEST_TIMEOUT", private_log.call_args.args[1])
            report.assert_not_called()

    def test_fast_but_failed_suite_remains_failed(self):
        with (
            patch.object(cli, "source_sha", return_value=SHA),
            patch("brain.validate.validate_policy"),
            patch("brain.__main__.subprocess.run") as runner,
            patch.object(cli, "write_private_test_log"),
            patch.object(cli, "write_report") as report,
        ):
            runner.return_value = SimpleNamespace(
                returncode=1, stdout="", stderr="Ran 7 tests\\nFAILED (failures=1)\\n"
            )
            with self.assertRaisesRegex(BrainError, "PREFLIGHT_TEST_FAILURE"):
                cli.preflight("/tmp/preflight", SHA)
            report.assert_not_called()


if __name__ == "__main__":
    unittest.main()
