import unittest
from types import SimpleNamespace
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader


REPOSITORY = "P00NSMASHER/portfolio-brain"
SINCE = "2026-10-02T20:00:00Z"


def workflow_run(run_id, created_at):
    return {
        "id": run_id,
        "path": ".github/workflows/portfolio-state-reducer.yml",
        "created_at": created_at,
        "updated_at": created_at,
        "head_branch": "main",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
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


class ArtifactRequestBudgetFanoutTests(unittest.TestCase):
    def test_many_producer_runs_use_bounded_artifact_batch_within_api_budget(self):
        producers = {f"producer-{index:02d}": f"producer-{index:02d}" for index in range(60)}
        reducer_runs = {
            201: workflow_run(201, "2026-10-02T21:00:00Z"),
            202: workflow_run(202, "2026-10-02T22:00:00Z"),
        }
        snapshots = {
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-10-02T21:01:00Z", 201),
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-10-02T22:01:00Z", 202),
        }
        runs = {}
        events = []
        for index, workflow in enumerate(producers):
            run_id = 1000 + index
            runs[workflow] = {
                "id": run_id,
                "created_at": "2026-10-02T21:30:00Z",
                "updated_at": "2026-10-02T21:31:00Z",
                "head_branch": "main",
                "head_sha": "b" * 40,
                "status": "completed",
                "conclusion": "success",
            }
            events.append(artifact(
                2000 + index,
                f"{EVENT_PREFIX}{run_id}-{workflow}-{'b' * 40}-1",
                f"2026-10-02T21:31:{index:02d}Z",
                run_id,
            ))
        events.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)

        reader = object.__new__(GitHubReader)
        reader.http = SimpleNamespace(max_requests=100, requests=0)
        calls = []

        def get(suffix):
            calls.append(suffix)
            reader.http.requests += 1
            if reader.http.requests > reader.http.max_requests:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [reducer_runs[202], reducer_runs[201]]}
            if suffix.startswith("/actions/workflows/"):
                workflow = suffix.split("/actions/workflows/", 1)[1].split(".yml/runs?", 1)[0]
                return {"workflow_runs": [runs[workflow]]}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                row = snapshots[run_id]
                return {"total_count": 1, "artifacts": [row]}
            if suffix == "/actions/artifacts?per_page=100&page=1":
                return {"artifacts": events}
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", producers):
            rows = reader.list_recent_journal_artifacts(SINCE, max_pages=20)

        self.assertEqual(
            {row["id"] for row in rows},
            {9, 10, *range(2000, 2060)},
        )
        self.assertLessEqual(reader.http.requests, reader.http.max_requests)
        self.assertIn("/actions/artifacts?per_page=100&page=1", calls)
        self.assertEqual(
            sum(call.endswith("/artifacts?per_page=100") for call in calls),
            2,
        )


if __name__ == "__main__":
    unittest.main()
