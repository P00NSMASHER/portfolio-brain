"""Regression coverage for reducer discovery under API request pressure."""
import unittest
from unittest.mock import patch

from state_journal.transport import EVENT_PREFIX, GitHubReader


class RequestBudgetFallbackTests(unittest.TestCase):
    def test_repository_artifact_scan_finishes_discovery_before_run_lookups_exhaust_budget(self):
        boundary = "2026-10-02T00:00:00Z"
        artifacts = []
        runs = []
        for run_id in range(101, 105):
            created_at = f"2026-10-02T00:00:{run_id - 100:02d}Z"
            artifacts.append({
                "id": run_id + 1000,
                "name": f"{EVENT_PREFIX}{run_id}-runtime-worker-{'a' * 40}-1",
                "created_at": created_at,
                "expired": False,
                "workflow_run": {"id": run_id, "head_branch": "main", "head_sha": "a" * 40},
            })
            runs.append({
                "id": run_id,
                "created_at": created_at,
                "updated_at": created_at,
                "head_branch": "main",
                "status": "completed",
                "conclusion": "success",
            })

        class RequestCounter:
            max_requests = 5
            requests = 0

        class FakeReader(GitHubReader):
            def __init__(self):
                self.http = RequestCounter()
                self.calls = []

            def get(self, suffix):
                if self.http.requests >= self.http.max_requests:
                    raise AssertionError("request budget exhausted")
                self.http.requests += 1
                self.calls.append(suffix)
                if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                    return {"workflow_runs": []}
                if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                    return {"workflow_runs": runs}
                if suffix == "/actions/artifacts?per_page=100&page=1":
                    return {"artifacts": artifacts}
                if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                    run_id = int(suffix.split("/")[3])
                    rows = [row for row in artifacts if row["workflow_run"]["id"] == run_id]
                    return {"total_count": len(rows), "artifacts": rows}
                raise AssertionError(f"unexpected API request: {suffix}")

        reader = FakeReader()
        with patch(
            "state_journal.transport.WORKFLOW_PRODUCERS",
            {"runtime-hourly-sync": "runtime-worker"},
        ):
            rows = reader.list_recent_journal_artifacts(
                boundary, max_pages=1
            )

        self.assertEqual({row["id"] for row in rows}, {row["id"] for row in artifacts})
        self.assertIn("/actions/artifacts?per_page=100&page=1", reader.calls)
        self.assertLessEqual(reader.http.requests, reader.http.max_requests)


if __name__ == "__main__":
    unittest.main()
