"""Regression coverage for reusing normal discovery during explicit recovery."""
import unittest
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader


class ExplicitRecoveryRequestBudgetTests(unittest.TestCase):
    def test_explicitly_recovered_discovered_run_does_not_refetch_metadata_or_artifacts(self):
        reader = object.__new__(GitHubReader)
        request_count = 0
        reducer_run = {
            "id": 202,
            "created_at": "2026-09-29T22:00:00Z",
            "head_branch": "main",
            "status": "completed",
            "conclusion": "success",
        }
        producer_run = {
            "id": 301,
            "created_at": "2026-09-29T21:30:00Z",
            "head_branch": "main",
            "status": "completed",
            "conclusion": "success",
            "path": ".github/workflows/runtime-hourly-sync.yml",
        }
        snapshot = {
            "id": 10,
            "name": SNAPSHOT_ARTIFACT,
            "created_at": "2026-09-29T22:01:00Z",
            "expired": False,
            "workflow_run": {"id": 202, "head_branch": "main"},
        }
        event = {
            "id": 20,
            "name": EVENT_PREFIX + "301-runtime-worker-" + "b" * 40 + "-1",
            "created_at": "2026-09-29T21:31:00Z",
            "expired": False,
            "workflow_run": {"id": 301, "head_branch": "main"},
        }

        def get(suffix):
            nonlocal request_count
            request_count += 1
            if request_count > 5:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [reducer_run]}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshot]}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": [producer_run]}
            if suffix == "/actions/runs/301/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [event]}
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {"runtime-hourly-sync": "runtime-worker"}):
            rows = reader.list_recent_journal_artifacts(
                "2026-09-29T16:35:30Z", explicit_run_ids=[301]
            )

        self.assertEqual([row["id"] for row in rows], [10, 20])
        self.assertEqual(request_count, 4)


if __name__ == "__main__":
    unittest.main()
