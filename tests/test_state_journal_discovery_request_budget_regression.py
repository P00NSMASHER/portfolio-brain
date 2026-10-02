"""Regression coverage for producer-run discovery under the API request budget."""
import unittest
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader


CREATED = "2026-09-29T16:35:30Z"
REDUCER_NEW = "2026-09-29T22:00:00Z"
REDUCER_OLD = "2026-09-29T21:00:00Z"
PRODUCERS = {f"producer-{index:02d}": "test" for index in range(20)}


def workflow_run(run_id, path, created_at):
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


class DiscoveryRequestBudgetRegressionTests(unittest.TestCase):
    def test_many_enrolled_workflow_runs_stay_within_request_budget(self):
        reducer_runs = [
            workflow_run(201, ".github/workflows/portfolio-state-reducer.yml", REDUCER_NEW),
            workflow_run(202, ".github/workflows/portfolio-state-reducer.yml", REDUCER_OLD),
        ]
        snapshots = {
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-09-29T22:01:00Z", 201),
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-09-29T21:01:00Z", 202),
        }
        producer_runs = {}
        for index, workflow in enumerate(PRODUCERS):
            rows = []
            for attempt in range(4):
                run_id = 1000 + index * 4 + attempt
                created = f"2026-09-29T21:30:{attempt:02d}Z"
                row = workflow_run(
                    run_id, f".github/workflows/{workflow}.yml", created
                )
                rows.append(row)
            producer_runs[workflow] = rows

        reader = object.__new__(GitHubReader)
        requests = 0

        def get(suffix):
            nonlocal requests
            requests += 1
            if requests > 100:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": reducer_runs}
            if suffix.startswith("/actions/runs?"):
                return {"workflow_runs": reducer_runs + [
                    row for rows in producer_runs.values() for row in rows
                ]}
            if suffix.startswith("/actions/workflows/"):
                workflow = suffix.split("/actions/workflows/", 1)[1].split(".yml/runs?", 1)[0]
                return {"workflow_runs": producer_runs[workflow]}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                if run_id in snapshots:
                    rows = [snapshots[run_id]]
                else:
                    rows = [artifact(
                        5000 + run_id,
                        f"{EVENT_PREFIX}{run_id}-test-{'b' * 40}-1",
                        "2026-09-29T21:31:00Z",
                        run_id,
                    )]
                return {"total_count": len(rows), "artifacts": rows}
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", PRODUCERS):
            rows = reader.list_recent_journal_artifacts(CREATED)

        self.assertEqual(len(rows), 82)
        self.assertLessEqual(requests, 100)
        self.assertEqual(
            sum(row["name"].startswith(EVENT_PREFIX) for row in rows),
            80,
        )


if __name__ == "__main__":
    unittest.main()
