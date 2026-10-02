"""Regression coverage for duplicate producer artifact requests during replay."""
import unittest
from unittest.mock import patch

from state_journal.transport import EVENT_PREFIX, GitHubReader


class JournalArtifactRequestBudgetTests(unittest.TestCase):
    def test_explicit_trigger_run_reuses_artifact_listing_from_scoped_discovery(self):
        reader = object.__new__(GitHubReader)
        calls = []
        event = {
            "id": 20,
            "name": EVENT_PREFIX + "301-runtime-worker-" + "b" * 40 + "-1",
            "created_at": "2026-10-02T12:00:00Z",
            "expired": False,
            "workflow_run": {
                "id": 301,
                "head_branch": "main",
                "head_sha": "b" * 40,
            },
        }

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": []}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": [{
                    "id": 301,
                    "created_at": "2026-10-02T11:59:00Z",
                    "updated_at": "2026-10-02T12:00:01Z",
                    "head_branch": "main",
                    "head_sha": "b" * 40,
                    "status": "completed",
                    "conclusion": "success",
                }]}
            if suffix == "/actions/runs/301":
                return {
                    "id": 301,
                    "head_branch": "main",
                    "head_sha": "b" * 40,
                    "status": "completed",
                    "conclusion": "success",
                    "path": ".github/workflows/runtime-hourly-sync.yml",
                }
            if suffix == "/actions/runs/301/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [event]}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {
            "runtime-hourly-sync": "runtime-worker",
        }):
            rows = reader.list_recent_journal_artifacts(
                "2026-10-02T11:00:00Z", explicit_run_ids=[301]
            )

        self.assertEqual([row["id"] for row in rows], [20])
        self.assertEqual(
            calls.count("/actions/runs/301/artifacts?per_page=100"),
            1,
        )
        self.assertIn("/actions/runs/301", calls)


if __name__ == "__main__":
    unittest.main()
