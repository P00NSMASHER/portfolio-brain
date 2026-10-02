import unittest
from types import SimpleNamespace
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader


BOUNDARY = "2026-10-02T08:00:00Z"


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


class MultiRunRequestBudgetRegressionTests(unittest.TestCase):
    def test_many_enrolled_runs_use_bounded_artifact_pages_instead_of_one_request_per_run(self):
        workflow_names = ("producer-a", "producer-b")
        producer_runs = {
            workflow: [
                run(1000 + index, "2026-10-02T11:30:00Z", updated_at="2026-10-02T11:35:00Z")
                for index in range(offset, offset + 60)
            ]
            for workflow, offset in zip(workflow_names, (0, 100))
        }
        producer_run_ids = [
            row["id"] for rows in producer_runs.values() for row in rows
        ]
        reducer_runs = [
            run(202, "2026-10-02T10:00:00Z"),
            run(201, "2026-10-02T09:00:00Z"),
        ]
        snapshots = {
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-10-02T10:01:00Z", 202),
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-10-02T09:01:00Z", 201),
        }
        events = [
            artifact(
                2000 + index,
                f"{EVENT_PREFIX}{run_id}-test-{'b' * 40}-1",
                "2026-10-02T11:31:00Z",
                run_id,
            )
            for index, run_id in enumerate(producer_run_ids)
        ]
        unrelated = artifact(
            99999,
            f"{EVENT_PREFIX}9999-test-{'c' * 40}-1",
            "2026-10-02T11:32:00Z",
            9999,
        )
        repository_artifacts = sorted(
            [*events, unrelated],
            key=lambda row: (row["created_at"], row["id"]),
            reverse=True,
        )

        reader = object.__new__(GitHubReader)
        reader.http = SimpleNamespace(max_requests=100, requests=0)
        calls = []
        request_count = 0

        def get(suffix):
            nonlocal request_count
            request_count += 1
            reader.http.requests += 1
            calls.append(suffix)
            if request_count > 100:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": reducer_runs}
            if suffix.startswith("/actions/workflows/"):
                workflow = suffix.split("/actions/workflows/", 1)[1].split(".yml/runs?", 1)[0]
                return {"workflow_runs": producer_runs[workflow]}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                return {"total_count": 1, "artifacts": [snapshots[run_id]]}
            if suffix.startswith("/actions/artifacts?per_page=100&page="):
                page = int(suffix.rsplit("page=", 1)[1])
                start = (page - 1) * 100
                return {"artifacts": repository_artifacts[start:start + 100]}
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {
            workflow: workflow for workflow in workflow_names
        }):
            rows = reader.list_recent_journal_artifacts(BOUNDARY)

        self.assertEqual(
            {row["id"] for row in rows},
            {row["id"] for row in events} | {9, 10},
        )
        self.assertFalse(any("/actions/runs/1000/artifacts" in call for call in calls))
        self.assertEqual(sum("/actions/artifacts?" in call for call in calls), 2)
        self.assertEqual(request_count, 7)


if __name__ == "__main__":
    unittest.main()
