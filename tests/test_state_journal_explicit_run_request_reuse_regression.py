import unittest
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import EVENT_PREFIX, GitHubReader


class ExplicitRunRequestReuseRegressionTests(unittest.TestCase):
    def test_trigger_run_reuses_discovery_metadata_and_artifact_listing(self):
        run = {
            "id": 301,
            "path": ".github/workflows/runtime-hourly-sync.yml",
            "created_at": "2026-09-29T21:30:00Z",
            "updated_at": "2026-09-29T21:31:00Z",
            "head_branch": "main",
            "head_sha": "a" * 40,
            "status": "completed",
            "conclusion": "success",
        }
        event = {
            "id": 20,
            "name": f"{EVENT_PREFIX}301-runtime-worker-{'a' * 40}-1",
            "created_at": "2026-09-29T21:31:00Z",
            "expired": False,
            "workflow_run": {"id": 301},
        }
        calls = []
        reader = object.__new__(GitHubReader)

        def get(suffix):
            calls.append(suffix)
            if len(calls) > 4:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": []}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": [run]}
            if suffix == "/actions/runs/301/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [event]}
            if suffix == "/actions/runs/301":
                return run
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = get
        with patch(
            "state_journal.transport.WORKFLOW_PRODUCERS",
            {"runtime-hourly-sync": "runtime-worker"},
        ):
            artifacts = reader.list_recent_journal_artifacts(
                "2026-09-29T16:35:30Z", explicit_run_ids=[301]
            )

        self.assertEqual([artifact["id"] for artifact in artifacts], [20])
        self.assertEqual(calls.count("/actions/runs/301/artifacts?per_page=100"), 1)


if __name__ == "__main__":
    unittest.main()
