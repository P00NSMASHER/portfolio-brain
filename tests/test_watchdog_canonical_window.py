import unittest

from state_journal.contracts import WORKFLOW_PRODUCERS
from state_journal.transport import GitHubReader, SNAPSHOT_ARTIFACT


class WatchdogCanonicalWindowRegressionTests(unittest.TestCase):
    def reader(self):
        reader = object.__new__(GitHubReader)
        reader.http = object()
        reader.base = "https://api.github.com/repos/P00NSMASHER/portfolio-brain"
        return reader

    def test_recent_scan_uses_trusted_snapshot_and_run_scoped_artifacts(self):
        reader = self.reader()
        calls = []
        snapshot = {
            "id": 9001,
            "name": SNAPSHOT_ARTIFACT,
            "expired": False,
            "created_at": "2026-09-29T20:47:53Z",
            "workflow_run": {
                "id": 7001,
                "head_branch": "main",
                "head_sha": "a" * 40,
            },
        }
        event = {
            "id": 9101,
            "name": "portfolio-state-event-v2-8001-runtime-worker-" + "b" * 40 + "-1",
            "expired": False,
            "created_at": "2026-09-29T20:50:00Z",
            "workflow_run": {
                "id": 8001,
                "head_branch": "main",
                "head_sha": "b" * 40,
            },
        }

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/artifacts?name="):
                return {"artifacts": [snapshot]}
            if suffix == "/actions/runs/7001":
                return {
                    "id": 7001,
                    "path": ".github/workflows/portfolio-state-reducer.yml",
                    "head_branch": "main",
                    "head_sha": "a" * 40,
                    "status": "completed",
                    "conclusion": "success",
                    "repository": {"full_name": "P00NSMASHER/portfolio-brain"},
                    "head_repository": {"full_name": "P00NSMASHER/portfolio-brain"},
                }
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs"):
                return {
                    "workflow_runs": [{
                        "id": 8001,
                        "path": ".github/workflows/runtime-hourly-sync.yml",
                        "head_branch": "main",
                    }]
                }
            if suffix == "/actions/runs/8001/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [event]}
            if suffix.startswith("/actions/workflows/"):
                return {"workflow_runs": []}
            raise AssertionError(suffix)

        reader.get = get
        rows = reader.list_recent_artifacts("2026-09-29T16:35:30Z", max_pages=2)
        self.assertEqual({row["id"] for row in rows}, {9001, 9101})
        self.assertFalse(any(
            suffix.startswith("/actions/artifacts?per_page=100")
            for suffix in calls
        ))
        for workflow in WORKFLOW_PRODUCERS:
            self.assertTrue(any(
                f"/actions/workflows/{workflow}.yml/runs" in suffix
                for suffix in calls
            ), workflow)

    def test_run_artifact_pagination_must_be_complete(self):
        reader = self.reader()
        snapshot = {
            "id": 9001,
            "name": SNAPSHOT_ARTIFACT,
            "expired": False,
            "created_at": "2026-09-29T20:47:53Z",
            "workflow_run": {
                "id": 7001,
                "head_branch": "main",
                "head_sha": "a" * 40,
            },
        }

        def get(suffix):
            if suffix.startswith("/actions/artifacts?name="):
                return {"artifacts": [snapshot]}
            if suffix == "/actions/runs/7001":
                return {
                    "id": 7001,
                    "path": ".github/workflows/portfolio-state-reducer.yml",
                    "head_branch": "main",
                    "head_sha": "a" * 40,
                    "status": "completed",
                    "conclusion": "success",
                    "repository": {"full_name": "P00NSMASHER/portfolio-brain"},
                    "head_repository": {"full_name": "P00NSMASHER/portfolio-brain"},
                }
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs"):
                return {
                    "workflow_runs": [{
                        "id": 8001,
                        "path": ".github/workflows/runtime-hourly-sync.yml",
                        "head_branch": "main",
                    }]
                }
            if suffix == "/actions/runs/8001/artifacts?per_page=100":
                return {"total_count": 101, "artifacts": []}
            if suffix.startswith("/actions/workflows/"):
                return {"workflow_runs": []}
            raise AssertionError(suffix)

        reader.get = get
        with self.assertRaisesRegex(ValueError, "Run artifact listing incomplete"):
            reader.list_recent_artifacts("2026-09-29T16:35:30Z", max_pages=2)


if __name__ == "__main__":
    unittest.main()
