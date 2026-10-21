"""Network-free regression tests for bounded guarded-runner failure evidence."""
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from brain.v9 import guarded_merge_runner as runner
from brain.v9.guarded_merge import Denied


class GuardedRunnerReasonTests(unittest.TestCase):
    def invoke_failure(self, error):
        stdout = io.StringIO()
        with patch.dict(os.environ, {"GH_TOKEN": "x" * 40,
                                    "GITHUB_SHA": "a" * 40}):
            with patch.object(runner, "dispatch_once", side_effect=error) as run:
                with redirect_stdout(stdout):
                    exit_code = runner.main()
        self.assertEqual(exit_code, 2)
        self.assertEqual(run.call_count, 1, "no retry after a possibly uncertain write")
        self.assertEqual(run.call_args.args[1], "a" * 40)
        self.assertIs(run.call_args.kwargs["apply"], True)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["status"], "RUNNER_BLOCKED")
        self.assertEqual(result["provider_writes"], "UNVERIFIED_NO_RETRY")
        self.assertEqual(set(result), {"status", "reason_code", "provider_writes"})
        return result

    def test_preserves_only_bounded_policy_codes(self):
        for code in ("RUNNER_PROTECTED_MAIN_MOVED", "HTTP_403",
                     "GITHUB_PROVIDER_UNAVAILABLE",
                     "AUTO_MERGE_WRITE_UNCERTAIN_READBACK_REQUIRED"):
            with self.subTest(code=code):
                self.assertEqual(self.invoke_failure(Denied(code))["reason_code"], code)

    def test_blocks_provider_message_token_or_control_character_echo(self):
        for error in (Denied("provider refused Bearer ghp_sensitive_value"),
                      Denied("LINE\nINJECTION"), Denied("A" * 81),
                      Denied("LOWER_case"), ValueError("Bearer ghp_sensitive_value"),
                      ValueError("HTTP_403")):
            with self.subTest(error=type(error).__name__):
                report = self.invoke_failure(error)
                self.assertEqual(report["reason_code"], "UNCLASSIFIED_FAILURE")
                self.assertNotIn("ghp_sensitive", json.dumps(report))

    def test_nested_failure_type_not_assumed_trusted(self):
        class UntrustedDenied(Denied):
            pass
        self.assertEqual(self.invoke_failure(UntrustedDenied("HTTP_403"))[
            "reason_code"], "UNCLASSIFIED_FAILURE")


if __name__ == "__main__":
    unittest.main()
