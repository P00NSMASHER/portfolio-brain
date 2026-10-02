"""Regression coverage for request-bounded journal artifact discovery."""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader


def reducer_run(run_id, created_at):
    return {
        "id": run_id,
        "path": ".github/workflows/portfolio-state-reducer.yml",
        "created_at": created_at,
        "updated_at": created_at,
        "head_branch": "main",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": "success",
    }


def artifact(artifact_id, name, created_at, run_id):
    return {
        "id": artifact_id,
        "name": name,
        "created_at": created_at,
        "expired": False,
        "workflow_run": {
            "id": run_id,
            "head_branch": "main",
            "head_sha": "a" * 40,
        },
    }


class LatestSnapshotOverlapRegressionTests(unittest.TestCase):
    def test_old_covered_runs_do_not_exhaust_request_budget(self):
        older_snapshot_run = reducer_run(201, "2026-10-02T21:00:00Z")
        latest_snapshot_run = reducer_run(202, "2026-10-02T22:00:00Z")
        snapshots = {
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-10-02T21:01:00Z", 201),
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-10-02T22:01:00Z", 202),
        }
        covered_start = datetime(2026, 10, 2, 21, 10, tzinfo=timezone.utc)
        covered_runs = []
        for index in range(99):
            started = covered_start + timedelta(seconds=index)
            covered_runs.append({
                "id": 1000 + index,
                "created_at": started.isoformat().replace("+00:00", "Z"),
                "updated_at": (started + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
                "head_branch": "main",
                "head_sha": "b" * 40,
                "status": "completed",
                "conclusion": "success",
            })
        overlapping_run = {
            "id": 2000,
            "created_at": "2026-10-02T21:59:59Z",
            "updated_at": "2026-10-02T22:00:01Z",
            "head_branch": "main",
            "head_sha": "c" * 40,
            "status": "completed",
            "conclusion": "success",
        }
        event = artifact(
            20,
            EVENT_PREFIX + "2000-runtime-worker-" + "c" * 40 + "-1",
            "2026-10-02T22:00:01Z",
            2000,
        )

        reader = object.__new__(GitHubReader)
        request_count = 0
        reader.http = SimpleNamespace(max_requests=100, requests=0)

        def get(suffix):
            nonlocal request_count
            request_count += 1
            reader.http.requests = request_count
            if request_count > 100:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [latest_snapshot_run, older_snapshot_run]}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                if suffix.endswith("&page=2"):
                    return {"workflow_runs": []}
                return {"workflow_runs": [overlapping_run, *covered_runs]}
            if suffix == "/actions/runs/201/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshots[201]]}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshots[202]]}
            if suffix == "/actions/runs/2000/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [event]}
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = get
        with patch(
            "state_journal.transport.WORKFLOW_PRODUCERS",
            {"runtime-hourly-sync": "runtime-worker"},
        ):
            rows = reader.list_recent_journal_artifacts("2026-10-02T20:00:00Z")

        self.assertEqual([row["id"] for row in rows], [10, 20, 9])
        self.assertEqual(request_count, 6)


if __name__ == "__main__":
    unittest.main()
