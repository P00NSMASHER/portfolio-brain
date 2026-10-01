"""Regression coverage for reducer snapshots published by workflow reruns."""
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
    def test_multiple_snapshot_artifacts_from_one_run_keep_newest_and_prior_run(self):
        reader = object.__new__(GitHubReader)
        newest_attempt_snapshot = snapshot(12, "2026-10-01T14:00:00Z", 202)
        prior_attempt_snapshot = snapshot(11, "2026-10-01T13:00:00Z", 202)
        predecessor = snapshot(10, "2026-09-30T14:00:00Z", 201)

        def get(suffix):
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [
                    run(202, "2026-10-01T13:59:00Z"),
                    run(201, "2026-09-30T13:59:00Z"),
                ]}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {
                    "total_count": 2,
                    "artifacts": [prior_attempt_snapshot, newest_attempt_snapshot],
                }
            if suffix == "/actions/runs/201/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [predecessor]}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {}):
            rows = reader.list_recent_journal_artifacts("2026-09-29T16:35:30Z")

        self.assertEqual([row["id"] for row in rows], [12, 10])


if __name__ == "__main__":
    unittest.main()
