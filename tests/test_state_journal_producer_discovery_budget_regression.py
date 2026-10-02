import unittest
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import GitHubReader, SNAPSHOT_ARTIFACT


class ProducerDiscoveryBudgetRegressionTests(unittest.TestCase):
    def test_repository_run_scan_keeps_enrolled_producers_within_api_budget(self):
        producers = {f"producer-{index:02d}": "test" for index in range(14)}
        reducer_runs = [
            {
                "id": 201,
                "path": ".github/workflows/portfolio-state-reducer.yml",
                "created_at": "2026-09-29T21:00:00Z",
                "head_branch": "main",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "id": 202,
                "path": ".github/workflows/portfolio-state-reducer.yml",
                "created_at": "2026-09-29T22:00:00Z",
                "head_branch": "main",
                "status": "completed",
                "conclusion": "success",
            },
        ]
        producer_runs = []
        for index, workflow in enumerate(producers):
            for run_number in range(6):
                run_id = 1000 + index * 6 + run_number
                producer_runs.append({
                    "id": run_id,
                    "path": f".github/workflows/{workflow}.yml",
                    "created_at": "2026-09-29T21:30:00Z",
                    "updated_at": "2026-09-29T21:40:00Z",
                    "head_branch": "main",
                    "status": "completed",
                    "conclusion": "success",
                })

        artifacts_by_run = {
            201: [{
                "id": 9, "name": SNAPSHOT_ARTIFACT,
                "created_at": "2026-09-29T21:01:00Z", "expired": False,
                "workflow_run": {"id": 201},
            }],
            202: [{
                "id": 10, "name": SNAPSHOT_ARTIFACT,
                "created_at": "2026-09-29T22:01:00Z", "expired": False,
                "workflow_run": {"id": 202},
            }],
        }
        for index, run in enumerate(producer_runs):
            artifacts_by_run[run["id"]] = [{
                "id": 2000 + index,
                "name": f"portfolio-state-event-v2-{run['id']}-test-{'b' * 40}-1",
                "created_at": "2026-09-29T21:41:00Z",
                "expired": False,
                "workflow_run": {"id": run["id"]},
            }]

        reader = GitHubReader("token", max_requests=100)
        request_count = 0

        def get(suffix):
            nonlocal request_count
            request_count += 1
            if request_count > 100:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": list(reversed(reducer_runs))}
            if suffix.startswith("/actions/runs?"):
                return {"workflow_runs": producer_runs}
            if suffix.startswith("/actions/workflows/"):
                workflow = suffix.split("/actions/workflows/", 1)[1].split(".yml/runs?", 1)[0]
                return {"workflow_runs": [
                    run for run in producer_runs
                    if run["path"] == f".github/workflows/{workflow}.yml"
                ]}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                rows = artifacts_by_run[run_id]
                return {"total_count": len(rows), "artifacts": rows}
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", producers):
            artifacts = reader.list_recent_journal_artifacts("2026-09-29T16:35:30Z")

        self.assertEqual(request_count, 88)
        self.assertEqual(len(artifacts), 86)
        self.assertEqual(sum(row["name"] == SNAPSHOT_ARTIFACT for row in artifacts), 2)


if __name__ == "__main__":
    unittest.main()
