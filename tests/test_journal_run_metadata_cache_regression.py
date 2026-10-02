import unittest

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import GitHubReader


class RequestBudgetTransport:
    def __init__(self, run, *, max_requests):
        self.run = run
        self.max_requests = max_requests
        self.requests = 0

    def _request(self):
        if self.requests >= self.max_requests:
            raise ArtifactRestoreError("artifact API request budget exceeded")
        self.requests += 1

    def json(self, _url):
        self._request()
        return {"workflow_runs": [self.run]}

    def bytes(self, _url):
        self._request()
        return b"snapshot"


class JournalRunMetadataCacheRegressionTests(unittest.TestCase):
    def test_snapshot_restore_reuses_run_metadata_from_workflow_listing(self):
        run = {
            "id": 77,
            "created_at": "2026-10-02T10:00:00Z",
            "updated_at": "2026-10-02T10:01:00Z",
            "path": ".github/workflows/portfolio-state-reducer.yml",
            "head_branch": "main",
            "head_sha": "a" * 40,
            "status": "completed",
            "conclusion": "success",
            "repository": {"full_name": "P00NSMASHER/portfolio-brain"},
            "head_repository": {"full_name": "P00NSMASHER/portfolio-brain"},
        }
        reader = GitHubReader("token", max_requests=2)
        reader.http = RequestBudgetTransport(run, max_requests=2)

        reader._workflow_runs_since(
            "portfolio-state-reducer.yml",
            "2026-10-02T09:00:00Z",
            max_pages=1,
        )
        restored_run = reader.get("/actions/runs/77")
        snapshot = reader.archive(88)

        self.assertEqual(restored_run, run)
        self.assertEqual(snapshot, b"snapshot")
        self.assertEqual(reader.http.requests, 2)


if __name__ == "__main__":
    unittest.main()
