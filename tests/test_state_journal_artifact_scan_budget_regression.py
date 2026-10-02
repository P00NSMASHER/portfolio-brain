"""Regression coverage for journal discovery near the GitHub API request cap."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import EVENT_PREFIX, GitHubReader


class JournalArtifactScanBudgetRegressionTests(unittest.TestCase):
    def test_many_producer_runs_use_bounded_global_scan_instead_of_exhausting_budget(self):
        producers = {f"producer-{index:02d}": "test" for index in range(55)}
        runs = {}
        artifacts = []
        for index, workflow in enumerate(producers):
            run_id = 1000 + index
            runs[workflow] = {
                "id": run_id,
                "created_at": "2026-10-02T10:00:00Z",
                "updated_at": "2026-10-02T10:01:00Z",
                "head_branch": "main",
                "status": "completed",
                "conclusion": "success",
            }
            artifacts.append({
                "id": 2000 + index,
                "name": f"{EVENT_PREFIX}{run_id}-test-{'b' * 40}-1",
                "created_at": "2026-10-02T10:01:00Z",
                "expired": False,
                "workflow_run": {"id": run_id, "head_branch": "main"},
            })

        reader = object.__new__(GitHubReader)
        reader.http = SimpleNamespace(max_requests=100, requests=0)
        calls = []

        def get(suffix):
            reader.http.requests += 1
            if reader.http.requests > reader.http.max_requests:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": []}
            if suffix.startswith("/actions/workflows/"):
                workflow = suffix.split("/actions/workflows/", 1)[1].split(".yml/runs?", 1)[0]
                return {"workflow_runs": [runs[workflow]]}
            if suffix == "/actions/artifacts?per_page=100&page=1":
                return {"artifacts": artifacts}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                return {"total_count": 1, "artifacts": [
                    next(row for row in artifacts if row["workflow_run"]["id"] == run_id)
                ]}
            raise AssertionError(f"Unexpected GitHub request: {suffix}")

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", producers):
            rows = reader.list_recent_journal_artifacts("2026-10-02T00:00:00Z")

        self.assertEqual(
            [row["id"] for row in rows],
            [row["id"] for row in reversed(artifacts)],
        )
        self.assertEqual(sum(call.startswith("/actions/artifacts?") for call in calls), 1)
        self.assertLess(reader.http.requests, reader.http.max_requests)


if __name__ == "__main__":
    unittest.main()
