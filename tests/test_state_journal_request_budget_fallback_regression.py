"""Regression coverage for request-bounded journal artifact discovery."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader


CREATED = "2026-09-29T16:35:30Z"


def run(run_id, created_at, *, updated_at=None):
    return {
        "id": run_id,
        "created_at": created_at,
        "updated_at": updated_at or created_at,
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


class RequestBudgetFallbackRegressionTests(unittest.TestCase):
    def test_many_producer_runs_fall_back_to_bounded_scoped_artifact_scan(self):
        reader = object.__new__(GitHubReader)
        reader.http = SimpleNamespace(requests=0, max_requests=6)
        snapshots = {
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-09-29T22:01:00Z", 202),
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-09-29T21:01:00Z", 201),
        }
        producers = {
            "producer-a": run(301, "2026-09-29T21:30:00Z", updated_at="2026-09-29T21:31:00Z"),
            "producer-b": run(302, "2026-09-29T21:32:00Z", updated_at="2026-09-29T21:33:00Z"),
        }
        events = [
            artifact(20, EVENT_PREFIX + "301-producer-a-" + "b" * 40 + "-1",
                     "2026-09-29T21:31:00Z", 301),
            artifact(21, EVENT_PREFIX + "302-producer-b-" + "c" * 40 + "-1",
                     "2026-09-29T21:33:00Z", 302),
        ]
        calls = []

        def get(suffix):
            reader.http.requests += 1
            if reader.http.requests > reader.http.max_requests:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [
                    run(202, "2026-09-29T22:00:00Z"),
                    run(201, "2026-09-29T21:00:00Z"),
                ]}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshots[202]]}
            if suffix == "/actions/runs/201/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshots[201]]}
            if suffix.startswith("/actions/workflows/producer-"):
                workflow = suffix.split("/actions/workflows/", 1)[1].split(".yml/runs?", 1)[0]
                return {"workflow_runs": [producers[workflow]]}
            if suffix.startswith("/actions/artifacts?per_page=100&page="):
                return {"total_count": len(events), "artifacts": events}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                raise AssertionError("per-run producer artifact query should exceed the remaining budget")
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {
            "producer-a": "producer-a",
            "producer-b": "producer-b",
        }):
            rows = reader.list_recent_journal_artifacts(CREATED)

        self.assertEqual({row["id"] for row in rows}, {9, 10, 20, 21})
        self.assertEqual(reader.http.requests, reader.http.max_requests)
        self.assertEqual(
            sum("/actions/artifacts?per_page=100&page=" in call for call in calls),
            1,
        )
        self.assertFalse(any(
            call.startswith("/actions/runs/301/artifacts")
            or call.startswith("/actions/runs/302/artifacts")
            for call in calls
        ))


if __name__ == "__main__":
    unittest.main()
