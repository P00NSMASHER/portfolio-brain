"""Regression coverage for request-bounded journal workflow discovery."""
import io
import json
import unittest
from unittest.mock import patch

from state_journal.transport import GitHubReader, SNAPSHOT_ARTIFACT


REPOSITORY = "P00NSMASHER/portfolio-brain"
BOUNDARY = "2026-10-01T03:18:34Z"


def run(run_id, workflow, created_at):
    return {
        "id": run_id,
        "path": f".github/workflows/{workflow}.yml",
        "created_at": created_at,
        "updated_at": created_at,
        "head_branch": "main",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
    }


class BatchedRunDiscoveryRegressionTests(unittest.TestCase):
    def test_many_enrolled_workflows_fit_the_api_budget_without_skipping_artifact_checks(self):
        producers = {f"producer-{index:02d}": "test" for index in range(55)}
        reducer_runs = [
            run(202, "portfolio-state-reducer", "2026-10-01T22:00:00Z"),
            run(201, "portfolio-state-reducer", "2026-10-01T21:00:00Z"),
        ]
        producer_runs = [
            run(1000 + index, workflow, "2026-10-01T21:30:00Z")
            for index, workflow in enumerate(producers)
        ]
        all_runs = reducer_runs + producer_runs
        snapshot_rows = {
            202: {
                "id": 10,
                "name": SNAPSHOT_ARTIFACT,
                "created_at": "2026-10-01T22:01:00Z",
                "expired": False,
                "workflow_run": {"id": 202, "head_branch": "main", "head_sha": "a" * 40},
            },
            201: {
                "id": 9,
                "name": SNAPSHOT_ARTIFACT,
                "created_at": "2026-10-01T21:01:00Z",
                "expired": False,
                "workflow_run": {"id": 201, "head_branch": "main", "head_sha": "a" * 40},
            },
        }
        base = f"https://api.github.com/repos/{REPOSITORY}"

        def open_api(request, timeout):
            del timeout
            suffix = request.full_url.removeprefix(base)
            if suffix.startswith("/actions/runs?"):
                payload = {"total_count": len(all_runs), "workflow_runs": all_runs}
            elif suffix.startswith("/actions/workflows/"):
                workflow = suffix.split("/actions/workflows/", 1)[1].split(".yml/runs?", 1)[0]
                payload = {
                    "workflow_runs": [
                        row for row in all_runs
                        if row["path"] == f".github/workflows/{workflow}.yml"
                    ]
                }
            elif suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                rows = [snapshot_rows[run_id]] if run_id in snapshot_rows else []
                payload = {"total_count": len(rows), "artifacts": rows}
            else:
                raise AssertionError(f"Unexpected GitHub request: {suffix}")
            return io.BytesIO(json.dumps(payload).encode("utf-8"))

        reader = GitHubReader("test-token", max_requests=100)
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", producers), \
             patch("runtime.artifact_state.open_url", side_effect=open_api):
            artifacts = reader.list_recent_journal_artifacts(BOUNDARY)

        self.assertEqual({row["id"] for row in artifacts}, {9, 10})
        self.assertEqual(reader.http.requests, 58)


if __name__ == "__main__":
    unittest.main()
