"""Regression coverage for request-bounded producer run discovery."""
import unittest
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import GitHubReader, SNAPSHOT_ARTIFACT


CREATED = "2026-09-29T16:35:30Z"


def run(run_id, created_at, *, path):
    return {
        "id": run_id,
        "path": path,
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


class CombinedRunDiscoveryRegressionTests(unittest.TestCase):
    def test_many_producer_workflows_stay_within_api_request_budget(self):
        producers = {f"producer-{index:02d}": "test" for index in range(49)}
        reducer_runs = [
            run(201, "2026-09-29T21:00:00Z",
                path=".github/workflows/portfolio-state-reducer.yml"),
            run(202, "2026-09-29T22:00:00Z",
                path=".github/workflows/portfolio-state-reducer.yml"),
        ]
        producer_runs = [
            run(
                1000 + index,
                "2026-09-29T21:30:00Z",
                path=f".github/workflows/{workflow}.yml",
            )
            for index, workflow in enumerate(producers)
        ]
        snapshots = {
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-09-29T21:01:00Z", 201),
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-09-29T22:01:00Z", 202),
        }
        events = {
            1000 + index: artifact(
                2000 + index,
                f"portfolio-state-event-v2-{1000 + index}-test-{'b' * 40}-1",
                "2026-09-29T21:31:00Z",
                1000 + index,
            )
            for index in range(len(producers))
        }
        reader = object.__new__(GitHubReader)
        reader.http = object()
        requests = []

        def get(suffix):
            requests.append(suffix)
            if len(requests) > 100:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": reducer_runs}
            if suffix.startswith("/actions/runs?"):
                return {"workflow_runs": producer_runs}
            if suffix.startswith("/actions/workflows/"):
                workflow = suffix.split("/actions/workflows/", 1)[1].split(".yml/runs?", 1)[0]
                return {"workflow_runs": [
                    next(row for row in producer_runs
                         if row["path"] == f".github/workflows/{workflow}.yml")
                ]}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                row = snapshots[run_id] if run_id in snapshots else events[run_id]
                return {"total_count": 1, "artifacts": [row]}
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", producers):
            rows = reader.list_recent_journal_artifacts(CREATED)

        self.assertEqual(len(rows), len(producers) + 2)
        self.assertEqual(len(requests), len(producers) + 4)
        self.assertEqual(sum(suffix.startswith("/actions/runs?") for suffix in requests), 1)
        self.assertFalse(any("/actions/workflows/producer-" in suffix for suffix in requests))


if __name__ == "__main__":
    unittest.main()
