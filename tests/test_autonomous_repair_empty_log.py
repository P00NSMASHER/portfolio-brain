"""Autonomous repair intake must survive failed runs without downloadable failed-step logs."""
import unittest

from repair.autonomous_repair import request_from_run

REPO = "P00NSMASHER/portfolio-brain"


def run_doc():
    return {
        "id": 456,
        "name": "portfolio-state-reducer",
        "path": ".github/workflows/portfolio-state-reducer.yml",
        "head_branch": "main",
        "head_sha": "a" * 40,
        "event": "workflow_run",
        "conclusion": "failure",
        "repository": {"full_name": REPO},
    }


class EmptyFailureLogRepairTests(unittest.TestCase):
    def test_empty_failed_log_falls_back_to_authenticated_run_metadata(self):
        request = request_from_run(run_doc(), "", base_sha="b" * 40)
        self.assertEqual(request["source_ref"], "workflow-run:456")
        self.assertIn("concluded failure", request["failure_summary"])
        self.assertIn("No failed-step log text was available", request["failure_summary"])
        self.assertIn("do not infer a root cause", request["failure_summary"])
        self.assertNotIn("PASS", request["failure_summary"])

    def test_whitespace_only_failed_log_uses_same_fail_safe_metadata_summary(self):
        request = request_from_run(run_doc(), "\n  \t", base_sha="b" * 40)
        self.assertIn("workflow portfolio-state-reducer run 456", request["failure_summary"])
        self.assertEqual(request["failed_head_sha"], "a" * 40)


if __name__ == "__main__":
    unittest.main()
