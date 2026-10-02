import unittest
from unittest.mock import patch

from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader


CREATED = "2026-09-29T16:35:30Z"


def workflow_run(run_id, created_at, *, updated_at=None):
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
        "workflow_run": {"id": run_id, "head_branch": "main", "head_sha": "a" * 40},
    }


class ArtifactRequestBudgetRegressionTests(unittest.TestCase):
    def test_many_producer_runs_use_bounded_artifact_scan_before_request_budget_exhaustion(self):
        producers = {f"producer-{index:03d}": "test" for index in range(70)}
        reducer_runs = {
            201: workflow_run(201, "2026-09-29T21:00:00Z"),
            202: workflow_run(202, "2026-09-29T22:00:00Z"),
        }
        snapshot_rows = {
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-09-29T21:01:00Z", 201),
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-09-29T22:01:00Z", 202),
        }
        producer_runs = {}
        events = []
        for index, workflow in enumerate(producers):
            run_id = 1000 + index
            producer_runs[workflow] = workflow_run(
                run_id, "2026-09-29T21:30:00Z", updated_at="2026-09-29T21:31:00Z"
            )
            events.append(artifact(
                2000 + index,
                f"{EVENT_PREFIX}{run_id}-test-{'b' * 40}-1",
                "2026-09-29T21:31:00Z",
                run_id,
            ))
        unrelated = artifact(
            3000, f"{EVENT_PREFIX}9999-test-{'c' * 40}-1",
            "2026-09-29T21:31:00Z", 9999,
        )

        reader = object.__new__(GitHubReader)
        reader.http = type(
            "RequestBudget", (), {"max_requests": 100, "requests": 0, "retries": 1}
        )()
        calls = []

        def get(suffix):
            reader.http.requests += 1
            if reader.http.requests > reader.http.max_requests:
                raise AssertionError("artifact API request budget exceeded")
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [reducer_runs[202], reducer_runs[201]]}
            if suffix.startswith("/actions/workflows/"):
                workflow = suffix.split("/actions/workflows/", 1)[1].split(".yml/runs?", 1)[0]
                return {"workflow_runs": [producer_runs[workflow]]}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                row = next(row for row in snapshot_rows.values()
                           if row["workflow_run"]["id"] == run_id)
                return {"total_count": 1, "artifacts": [row]}
            if suffix == "/actions/artifacts?per_page=100&page=1":
                return {"total_count": len(events) + 1, "artifacts": [*events, unrelated]}
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", producers):
            rows = reader.list_recent_journal_artifacts(CREATED)

        self.assertEqual(len(rows), len(events) + len(snapshot_rows))
        self.assertEqual(reader.http.requests, len(producers) + 4)
        self.assertTrue(any(call.startswith("/actions/artifacts?") for call in calls))
        self.assertFalse(any(
            call.startswith("/actions/runs/") and call.endswith("/artifacts?per_page=100")
            and int(call.split("/actions/runs/", 1)[1].split("/", 1)[0]) >= 1000
            for call in calls
        ))


if __name__ == "__main__":
    unittest.main()
