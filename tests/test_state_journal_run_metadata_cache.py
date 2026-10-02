"""Regression coverage for reusing journal discovery run metadata."""
import unittest

from state_journal.transport import GitHubReader


class SingleRequestHTTP:
    def __init__(self, response):
        self.response = response
        self.requests = 0

    def json(self, url):
        self.requests += 1
        if self.requests > 1:
            raise RuntimeError("artifact API request budget exceeded")
        if not url.endswith(
            "/actions/workflows/portfolio-state-reducer.yml/runs"
            "?branch=main&created=%3E%3D2026-10-01T00%3A00%3A00Z&per_page=100&page=1"
        ):
            raise AssertionError("unexpected API request: " + url)
        return self.response


class RunMetadataCacheTests(unittest.TestCase):
    def test_run_detail_reuses_record_from_bounded_workflow_discovery(self):
        reducer_run = {
            "id": 123,
            "created_at": "2026-10-01T01:00:00Z",
            "head_branch": "main",
            "head_sha": "a" * 40,
            "status": "completed",
            "conclusion": "success",
            "path": ".github/workflows/portfolio-state-reducer.yml",
            "repository": {"full_name": "P00NSMASHER/portfolio-brain"},
            "head_repository": {"full_name": "P00NSMASHER/portfolio-brain"},
        }
        reader = object.__new__(GitHubReader)
        reader.base = "https://api.github.com/repos/P00NSMASHER/portfolio-brain"
        reader.http = SingleRequestHTTP({"workflow_runs": [reducer_run]})
        reader._run_cache = {}

        discovered = reader._workflow_runs_since(
            "portfolio-state-reducer.yml",
            "2026-10-01T00:00:00Z",
            max_pages=1,
        )
        restored = reader.get("/actions/runs/123")

        self.assertEqual(discovered, [reducer_run])
        self.assertEqual(restored, reducer_run)
        self.assertEqual(reader.http.requests, 1)


if __name__ == "__main__":
    unittest.main()
