import unittest
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import GitHubReader, SNAPSHOT_ARTIFACT


def run(run_id, created_at, *, event):
    return {
        "id": run_id,
        "created_at": created_at,
        "updated_at": created_at,
        "head_branch": "main",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": "success",
        "event": event,
    }


def artifact(artifact_id, created_at, run_id):
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


class RejectedRunBudgetRegressionTests(unittest.TestCase):
    def test_rejected_github_events_do_not_spend_per_run_artifact_requests(self):
        reader = object.__new__(GitHubReader)
        calls = []
        reducer_runs = [
            run(202, "2026-10-02T12:00:00Z", event="workflow_run"),
            run(201, "2026-10-02T11:00:00Z", event="workflow_run"),
        ]
        rejected_runs = [
            run(1000 + index, "2026-10-02T11:30:00Z", event="pull_request_target")
            for index in range(101)
        ]

        def get(suffix):
            calls.append(suffix)
            if len(calls) > 10:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": reducer_runs}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                page = int(suffix.rsplit("page=", 1)[1])
                start = (page - 1) * 100
                return {"workflow_runs": rejected_runs[start:start + 100]}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {
                    "total_count": 1,
                    "artifacts": [artifact(10, "2026-10-02T12:01:00Z", 202)],
                }
            if suffix == "/actions/runs/201/artifacts?per_page=100":
                return {
                    "total_count": 1,
                    "artifacts": [artifact(9, "2026-10-02T11:01:00Z", 201)],
                }
            raise AssertionError(f"Unexpected GitHub request: {suffix}")

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {"runtime-hourly-sync": "runtime-worker"}):
            rows = reader.list_recent_journal_artifacts("2026-10-02T10:00:00Z")

        self.assertEqual([row["id"] for row in rows], [10, 9])
        self.assertEqual(len(calls), 5)
        rejected_artifact_requests = {
            f"/actions/runs/{rejected['id']}/artifacts?per_page=100"
            for rejected in rejected_runs
        }
        self.assertFalse(rejected_artifact_requests.intersection(calls))


if __name__ == "__main__":
    unittest.main()
