"""Regression tests for reducer snapshots retained across workflow attempts."""
import unittest
from unittest.mock import patch

from state_journal.transport import SNAPSHOT_ARTIFACT, GitHubReader


class ReducerAttemptArtifactTests(unittest.TestCase):
    def test_discovery_uses_latest_snapshot_when_a_run_retains_prior_attempt_artifact(self):
        reader = object.__new__(GitHubReader)
        old = {
            "id": 41,
            "name": SNAPSHOT_ARTIFACT,
            "created_at": "2026-10-01T14:00:00Z",
            "expired": False,
        }
        newest = {
            "id": 42,
            "name": SNAPSHOT_ARTIFACT,
            "created_at": "2026-10-01T14:05:00Z",
            "expired": False,
        }

        def get(path):
            if path.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {
                    "workflow_runs": [{
                        "id": 300,
                        "created_at": "2026-10-01T13:59:00Z",
                        "head_branch": "main",
                        "status": "completed",
                        "conclusion": "success",
                    }]
                }
            if path == "/actions/runs/300/artifacts?per_page=100":
                return {"total_count": 2, "artifacts": [old, newest]}
            raise AssertionError("unexpected GitHub request: " + path)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {}):
            artifacts = reader.list_recent_journal_artifacts("2026-10-01T13:00:00Z")

        self.assertEqual([artifact["id"] for artifact in artifacts], [42])


if __name__ == "__main__":
    unittest.main()
