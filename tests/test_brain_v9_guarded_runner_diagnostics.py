"""Network-free regression checks for fail-closed runner diagnostics."""
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from brain.v9 import guarded_merge_runner as runner
from brain.v9.guarded_merge import Denied


class GuardedRunnerDiagnosticTests(unittest.TestCase):
    def invoke(self, outcome):
        capture = io.StringIO()
        is_error = isinstance(outcome, Exception)
        with patch.dict(runner.os.environ,
                        {"GH_TOKEN": "synthetic-not-a-real-token", "GITHUB_SHA": "a" * 40},
                        clear=True):
            with patch.object(runner, "dispatch_once",
                              side_effect=outcome if is_error else None,
                              return_value=None if is_error else outcome) as dispatch:
                with redirect_stdout(capture):
                    exit_code = runner.main()
        dispatch.assert_called_once()
        output = capture.getvalue()
        self.assertEqual(len(output.splitlines()), 1)
        return exit_code, json.loads(output), output

    def test_known_provider_and_protection_denials_are_visible(self):
        for reason in ("REPOSITORY_GRAPHQL_SETTING_UNVERIFIED", "HTTP_403",
                       "RUNNER_PROTECTED_MAIN_MOVED", "RUNNER_DUPLICATE_CANDIDATES"):
            with self.subTest(reason=reason):
                code, payload, _ = self.invoke(Denied(reason))
                self.assertEqual(code, 2)
                self.assertEqual(payload, {
                    "status": "RUNNER_BLOCKED",
                    "reason_code": reason,
                    "provider_writes": "UNVERIFIED_NO_RETRY",
                })

    def test_untrusted_exception_text_is_never_logged(self):
        secret = "GH_TOKEN=ghp_this_is_not_a_real_token"
        for error in (Denied(secret),
                      Denied("HTTP_403\\n" + secret),
                      ValueError(secret)):
            with self.subTest(error=type(error).__name__):
                code, payload, output = self.invoke(error)
                self.assertEqual(code, 2)
                self.assertEqual(payload["reason_code"], "UNCLASSIFIED")
                self.assertEqual(payload["provider_writes"], "UNVERIFIED_NO_RETRY")
                self.assertNotIn(secret, output)

    def test_normal_zero_write_result_is_unchanged(self):
        result = {"status": "OBSERVED", "candidate_count": 0,
                  "decisions": [], "provider_writes": 0}
        code, payload, _ = self.invoke(result)
        self.assertEqual(code, 0)
        self.assertEqual(payload, result)

    def test_unknown_post_remains_a_hold_not_a_retry(self):
        result = {"status": "POST_WRITE_UNCERTAIN_MANUAL_RECONCILIATION",
                  "provider_writes": "UNKNOWN",
                  "decisions": [{"pr_number": 901, "provider_writes": "UNKNOWN_AFTER_POST"}]}
        code, payload, _ = self.invoke(result)
        self.assertEqual(code, 2)
        self.assertEqual(payload, result)

    def test_diagnostic_changes_never_grant_merge_permission(self):
        from pathlib import Path
        workflow = Path(".github/workflows/v9-guarded-native-automerge.yml").read_text()
        self.assertIn("contents: read", workflow)
        self.assertIn("pull-requests: write", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertNotIn("pull_request_target:", workflow)
        self.assertNotIn("gh pr merge", workflow)


if __name__ == "__main__":
    unittest.main()
