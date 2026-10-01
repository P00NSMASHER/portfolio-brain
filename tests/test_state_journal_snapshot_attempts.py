"""Regression coverage for snapshots retained across reducer workflow reruns."""
import unittest
from unittest.mock import patch

from state_journal.transport import SNAPSHOT_ARTIFACT, GitHubReader


def run(run_id, created_at):
    return {
        "id": run_id,
        "created_at": created_at,
        "updated_at": created_at,
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
    }


def snapshot(artifact_id, created_at, run_id):
    return {
        "id": artifact_id,
        "name": SNAPSHOT_ARTIFACT,
        "created_at": created_at,
        "expired": False,
        "workflow_run": {
            "id": run_id,
            "head_branch": "main",
            "head_sha": "a" * 40,
        },
    }


class ReducerSnapshotAttemptTests(unittest.TestCase):
    def test_latest_snapshot_from_reducer_rerun_is_used_once_per_workflow_run(self):
        reader = object.__new__(GitHubReader)
        older_attempt = snapshot(10, "2026-09-30T08:00:00Z", 202)
        latest_attempt = snapshot(11, "2026-09-30T08:05:00Z", 202)
        predecessor = snapshot(9, "2026-09-30T07:00:00Z", 201)

        def get(path):
            if path.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {
                    "workflow_runs": [
                        run(202, "2026-09-30T08:00:00Z"),
                        run(201, "2026-09-30T07:00:00Z"),
                    ]
                }
            if path == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 2, "artifacts": [older_attempt, latest_attempt]}
            if path == "/actions/runs/201/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [predecessor]}
            raise AssertionError("unexpected GitHub request: " + path)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {}):
            artifacts = reader.list_recent_journal_artifacts("2026-09-29T16:35:30Z")

        self.assertEqual([row["id"] for row in artifacts], [11, 9])


if __name__ == "__main__":
    unittest.main()
