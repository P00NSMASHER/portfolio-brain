"""Regression coverage for reusing explicitly triggered journal runs."""
import unittest
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import EVENT_PREFIX, GitHubReader


class ExplicitRunRequestBudgetRegressionTests(unittest.TestCase):
    def test_trigger_run_reuses_discovered_run_metadata_and_artifacts(self):
        run = {
            "id": 301,
            "path": ".github/workflows/runtime-hourly-sync.yml",
            "created_at": "2026-10-02T12:00:00Z",
            "updated_at": "2026-10-02T12:01:00Z",
            "head_branch": "main",
            "head_sha": "a" * 40,
            "status": "completed",
            "conclusion": "success",
        }
        event = {
            "id": 401,
            "name": f"{EVENT_PREFIX}301-runtime-worker-{'a' * 40}-1",
            "created_at": "2026-10-02T12:01:00Z",
            "expired": False,
            "workflow_run": {
                "id": 301,
                "head_branch": "main",
                "head_sha": "a" * 40,
            },
        }
        reader = object.__new__(GitHubReader)
        requests = []

        def get(suffix):
            requests.append(suffix)
            if len(requests) > 3:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": []}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": [run]}
            if suffix == "/actions/runs/301/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [event]}
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {
            "runtime-hourly-sync": "runtime-worker",
        }):
            artifacts = reader.list_recent_journal_artifacts(
                "2026-10-02T11:00:00Z", explicit_run_ids=[301]
            )

        self.assertEqual([row["id"] for row in artifacts], [401])
        self.assertEqual(requests.count("/actions/runs/301/artifacts?per_page=100"), 1)
        self.assertFalse(any(request == "/actions/runs/301" for request in requests))
        self.assertEqual(len(requests), 3)


if __name__ == "__main__":
    unittest.main()
