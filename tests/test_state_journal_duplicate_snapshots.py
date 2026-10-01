"""Regression coverage for reducer reruns that leave multiple snapshot artifacts."""
import unittest
from unittest.mock import patch

from state_journal.transport import SNAPSHOT_ARTIFACT, GitHubReader


def reducer_run(run_id, created_at):
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


class DuplicateReducerSnapshotTests(unittest.TestCase):
    def test_multiple_snapshots_in_one_run_are_discovered_newest_first(self):
        reader = object.__new__(GitHubReader)
        calls = []
        newest = snapshot(11, "2026-09-29T22:03:00Z", 202)
        previous_attempt = snapshot(10, "2026-09-29T22:01:00Z", 202)

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {
                    "workflow_runs": [
                        reducer_run(202, "2026-09-29T22:00:00Z"),
                        reducer_run(201, "2026-09-29T21:00:00Z"),
                    ]
                }
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 2, "artifacts": [previous_attempt, newest]}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {}):
            rows = reader.list_recent_journal_artifacts("2026-09-29T16:35:30Z")

        self.assertEqual([row["id"] for row in rows], [11, 10])
        self.assertIn("/actions/runs/202/artifacts?per_page=100", calls)
        self.assertNotIn("/actions/runs/201/artifacts?per_page=100", calls)


if __name__ == "__main__":
    unittest.main()
