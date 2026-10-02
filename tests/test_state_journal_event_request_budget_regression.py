"""Regression coverage for reusing producer metadata during journal replay."""
import unittest
from unittest.mock import patch

from state_journal.transport import EVENT_PREFIX, GitHubReader


class EventRequestBudgetRegressionTests(unittest.TestCase):
    def test_event_replay_reuses_discovered_source_attempt_metadata(self):
        reader = GitHubReader("token")
        run = {
            "id": 301,
            "run_attempt": 2,
            "path": ".github/workflows/runtime-hourly-sync.yml",
            "created_at": "2026-10-02T12:00:00Z",
            "updated_at": "2026-10-02T12:01:00Z",
            "head_branch": "main",
            "head_sha": "a" * 40,
            "status": "completed",
            "conclusion": "success",
            "event": "workflow_dispatch",
            "workflow_id": 45,
            "repository": {"full_name": "P00NSMASHER/portfolio-brain", "id": 1387747549},
            "head_repository": {"full_name": "P00NSMASHER/portfolio-brain", "id": 1387747549},
        }
        event_artifact = {
            "id": 20,
            "name": f"{EVENT_PREFIX}301-runtime-worker-{'a' * 40}-2",
            "created_at": "2026-10-02T12:01:00Z",
            "expired": False,
            "digest": "sha256:" + "b" * 64,
            "workflow_run": {
                "id": 301,
                "head_branch": "main",
                "head_sha": "a" * 40,
            },
        }
        requests = []

        def get(suffix):
            requests.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": []}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": [run]}
            if suffix == "/actions/runs/301/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [event_artifact]}
            if suffix == "/actions/runs/301/attempts/2/jobs?per_page=100":
                return {"total_count": 1, "jobs": [{"steps": []}]}
            raise AssertionError(f"Unexpected GitHub request: {suffix}")

        reader.get = get
        reader.archive = lambda _artifact_id: b"event archive"
        with patch("state_journal.transport.WORKFLOW_PRODUCERS",
                   {"runtime-hourly-sync": "runtime-worker"}), \
             patch("state_journal.transport.extract_json",
                   return_value={"producer": "runtime-worker", "changes": [{"domain": "heartbeat"}]}), \
             patch("state_journal.transport.validate_event"), \
             patch("state_journal.transport.validate_provider_event", return_value=({"event": "ok"}, {})):
            artifacts = reader.list_recent_journal_artifacts(
                "2026-10-02T00:00:00Z",
                max_pages=1,
                explicit_run_ids=[],
            )
            result = reader.event(artifacts[0], {})

        self.assertEqual(result, ({"event": "ok"}, {}))
        self.assertNotIn("/actions/runs/301/attempts/2", requests)
        self.assertIn("/actions/runs/301/attempts/2/jobs?per_page=100", requests)
        self.assertEqual(requests.count("/actions/runs/301/artifacts?per_page=100"), 1)


if __name__ == "__main__":
    unittest.main()
