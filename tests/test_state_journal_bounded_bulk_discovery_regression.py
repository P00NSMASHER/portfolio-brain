"""Regression coverage for request-bounded journal artifact discovery."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader


def artifact(artifact_id, name, created_at, run_id):
    return {
        "id": artifact_id,
        "name": name,
        "created_at": created_at,
        "expired": False,
        "workflow_run": {"id": run_id, "head_branch": "main", "head_sha": "a" * 40},
    }


def run(run_id, created_at, updated_at=None):
    return {
        "id": run_id,
        "created_at": created_at,
        "updated_at": updated_at or created_at,
        "head_branch": "main",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
    }


class BoundedBulkDiscoveryRegressionTests(unittest.TestCase):
    def test_recent_events_are_batched_and_pre_overlap_long_runs_remain_scanned(self):
        reader = GitHubReader("test-token", max_requests=100)
        calls = []
        boundary = datetime(2026, 10, 1, 21, 0, tzinfo=timezone.utc)
        producer_runs = []
        recent_artifacts = []
        for index in range(98):
            created = boundary + timedelta(minutes=1, seconds=index)
            run_id = 1000 + index
            producer_runs.append(run(run_id, created.isoformat().replace("+00:00", "Z")))
            recent_artifacts.append(artifact(
                2000 + index,
                f"{EVENT_PREFIX}{run_id}-producer-{'a' * 40}-1",
                (created + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
                run_id,
            ))

        late_run = run(
            999,
            "2026-10-01T20:59:00Z",
            updated_at="2026-10-01T21:10:00Z",
        )
        late_event = artifact(
            1999,
            f"{EVENT_PREFIX}999-producer-{'b' * 40}-1",
            "2026-10-01T20:59:30Z",
            999,
        )
        snapshots = {
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-10-01T22:01:00Z", 202),
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-10-01T21:01:00Z", 201),
        }

        def get(suffix):
            calls.append(suffix)
            if len(calls) > 100:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [
                    run(202, "2026-10-01T22:00:00Z"),
                    run(201, "2026-10-01T21:00:00Z"),
                ]}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshots[202]]}
            if suffix == "/actions/runs/201/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshots[201]]}
            if suffix.startswith("/actions/workflows/producer.yml/runs?"):
                return {"workflow_runs": [late_run, *producer_runs]}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                row = late_event if run_id == 999 else recent_artifacts[run_id - 1000]
                return {"total_count": 1, "artifacts": [row]}
            if suffix == "/actions/artifacts?per_page=100&page=1":
                return {"artifacts": recent_artifacts}
            if suffix == "/actions/artifacts?per_page=100&page=2":
                return {"artifacts": []}
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {"producer": "producer"}):
            rows = reader.list_recent_journal_artifacts("2026-10-01T03:18:34Z")

        self.assertEqual(len([row for row in rows if row["name"].startswith(EVENT_PREFIX)]), 99)
        self.assertIn(1999, {row["id"] for row in rows})
        self.assertEqual(
            sum(call.startswith("/actions/runs/") and call.endswith("/artifacts?per_page=100")
                for call in calls),
            3,
        )
        self.assertEqual(
            sum(call.startswith("/actions/artifacts?per_page=100&page=") for call in calls),
            1,
        )
        self.assertLess(len(calls), 100)


if __name__ == "__main__":
    unittest.main()
