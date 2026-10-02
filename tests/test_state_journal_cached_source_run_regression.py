import unittest
from unittest.mock import patch

from state_journal.transport import EVENT_PREFIX, GitHubReader


class CachedProducerSourceRunRegressionTests(unittest.TestCase):
    def test_event_reuses_exact_attempt_metadata_discovered_during_journal_scan(self):
        reader = object.__new__(GitHubReader)
        run = {
            "id": 101,
            "run_attempt": 1,
            "created_at": "2026-10-02T12:00:00Z",
            "updated_at": "2026-10-02T12:01:00Z",
            "head_branch": "main",
            "head_sha": "a" * 40,
            "event": "workflow_dispatch",
            "repository": {"full_name": "P00NSMASHER/portfolio-brain", "id": 1387747549},
            "head_repository": {"full_name": "P00NSMASHER/portfolio-brain", "id": 1387747549},
            "status": "completed",
            "conclusion": "success",
            "path": ".github/workflows/runtime-hourly-sync.yml",
            "workflow_id": 45,
        }
        artifact = {
            "id": 501,
            "name": f"{EVENT_PREFIX}101-runtime-worker-{'a' * 40}-1",
            "created_at": "2026-10-02T12:01:00Z",
            "expired": False,
            "workflow_run": {
                "id": 101,
                "head_branch": "main",
                "head_sha": "a" * 40,
            },
        }
        calls = []

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": []}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": [run]}
            if suffix == "/actions/runs/101/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [artifact]}
            if suffix == "/actions/runs/101/attempts/1/jobs?per_page=100":
                return {"total_count": 0, "jobs": []}
            if suffix == "/actions/runs/101/attempts/1":
                raise AssertionError("discovered source run metadata should be reused")
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = get
        reader.archive = lambda _artifact_id: b"event archive"
        event = {"producer": "runtime-worker", "changes": []}
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {
            "runtime-hourly-sync": "runtime-worker",
        }), patch("state_journal.transport.extract_json", return_value=event), \
             patch("state_journal.transport.validate_event"), \
             patch("state_journal.transport.validate_provider_event", return_value=(event, {})):
            artifacts = reader.list_recent_journal_artifacts("2026-10-02T11:00:00Z")
            self.assertEqual(artifacts, [artifact])
            self.assertEqual(reader.event(artifact, {})[0], event)

        self.assertEqual(len(calls), 4)
        self.assertNotIn("/actions/runs/101/attempts/1", calls)


if __name__ == "__main__":
    unittest.main()
