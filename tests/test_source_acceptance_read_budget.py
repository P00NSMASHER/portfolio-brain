"""Synthetic capacity tests, never a real source-acceptance certificate.

The source verifier must replay original GitHub core, observer, repair and
state evidence after potentially delayed activation. The read budget remains
finite and read-only, while a normal >256 GET proof is not falsely denied.
"""
import io
import json
import unittest
from unittest import mock

from soak_v3.audit import EvidenceError
from soak_v3.remote_probe import GitHubReadOnly
from verification import source_acceptance_producer as producer
from verification import source_acceptance_verifier as verifier

SOURCE = "a" * 40
CANDIDATE = "b" * 40


class ReadBudgetRegressions(unittest.TestCase):
    def test_same_finite_bound_for_producer_and_independent_app(self):
        self.assertEqual(verifier.SOURCE_ACCEPTANCE_API_CALL_BUDGET, 512)
        self.assertEqual(
            producer.SOURCE_ACCEPTANCE_API_CALL_BUDGET,
            verifier.SOURCE_ACCEPTANCE_API_CALL_BUDGET,
        )
        self.assertLessEqual(verifier.SOURCE_ACCEPTANCE_API_CALL_BUDGET, 656)

    def test_257_to_512_original_gets_fit_then_fail_closed(self):
        tokenless = GitHubReadOnly(
            "", transport=lambda _route: b"{}", max_attempts=1,
            max_calls=verifier.SOURCE_ACCEPTANCE_API_CALL_BUDGET,
        )
        for number in range(verifier.SOURCE_ACCEPTANCE_API_CALL_BUDGET):
            self.assertEqual(tokenless.get("/branches/main"), b"{}")
            if number == 256:
                self.assertEqual(tokenless.calls, 257)
        self.assertEqual(tokenless.calls, 512)
        with self.assertRaisesRegex(EvidenceError, "API_CALL_BUDGET"):
            tokenless.get("/branches/main")

    def test_producer_uses_bounded_budget_without_inventing_receipt(self):
        output = io.StringIO()
        with mock.patch.object(producer, "GitHubReadOnly") as api, \
             mock.patch.object(producer, "GitHubWrite") as writer, \
             mock.patch.object(producer, "build_receipt",
                               return_value=({"kind": "synthetic"}, "20261031")), \
             mock.patch.object(producer, "publish_receipt",
                               return_value={"pr_number": 812, "provider_writes": 0}), \
             mock.patch("sys.stdout", output), \
             mock.patch.dict("os.environ", {
                 "GITHUB_TOKEN": "test-read-token",
                 "PORTFOLIO_RUNTIME_TOKEN": "test-write-token",
             }):
            self.assertEqual(producer.main(["--source-sha", SOURCE]), 0)
            api.assert_called_once_with(
                "test-read-token",
                max_calls=verifier.SOURCE_ACCEPTANCE_API_CALL_BUDGET,
            )
            writer.assert_called_once_with("test-write-token")
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "RECEIPT_PR_READY")
        self.assertNotIn("test-read-token", output.getvalue())
        self.assertNotIn("test-write-token", output.getvalue())

    def test_independent_verifier_uses_same_bound_no_auto_pass_claim(self):
        output = io.StringIO()
        with mock.patch.object(verifier, "GitHubReadOnly") as api, \
             mock.patch.object(verifier, "verify_acceptance",
                               return_value=(SOURCE, "synthetic-external-id")), \
             mock.patch.object(verifier, "publish_check",
                               return_value={"id": 333}) as publish, \
             mock.patch("sys.stdout", output), \
             mock.patch.dict("os.environ", {
                 "GITHUB_TOKEN": "test-independent-read",
                 "PORTFOLIO_VERIFIER_TOKEN": "test-independent-app",
             }):
            self.assertEqual(verifier.main([
                "--pr-number", "812", "--head-sha", CANDIDATE,
            ]), 0)
            api.assert_called_once_with(
                "test-independent-read",
                max_calls=verifier.SOURCE_ACCEPTANCE_API_CALL_BUDGET,
            )
            publish.assert_called_once()
        result = json.loads(output.getvalue())
        self.assertEqual(result["check_run_id"], 333)
        self.assertNotIn("test-independent-app", output.getvalue())


if __name__ == "__main__":
    unittest.main()
