import json
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import EVENT_PREFIX, GitHubReader


ROOT = Path(__file__).resolve().parents[1]
UPLOAD_STEPS = json.loads((ROOT / "state_journal/UPLOAD_STEPS.json").read_text())


class EventRunCacheRegressionTests(unittest.TestCase):
    def test_discovered_exact_attempt_metadata_stays_within_api_request_budget(self):
        reader = object.__new__(GitHubReader)
        requests = []
        runs = []
        artifacts = {}
        for index in range(30):
            run_id = 301 + index
            runs.append({
                "id": run_id,
                "run_attempt": 1,
                "created_at": "2026-10-01T12:00:00Z",
                "updated_at": "2026-10-01T12:01:00Z",
                "head_branch": "main",
                "head_sha": "a" * 40,
                "status": "completed",
                "conclusion": "success",
                "path": ".github/workflows/runtime-hourly-sync.yml",
            })
            artifacts[run_id] = {
                "id": 700 + index,
                "name": f"{EVENT_PREFIX}{run_id}-runtime-worker-{'a' * 40}-1",
                "created_at": "2026-10-01T12:01:00Z",
                "expired": False,
                "workflow_run": {
                    "id": run_id,
                    "head_branch": "main",
                    "head_sha": "a" * 40,
                },
            }
        event = {"producer": "runtime-worker", "changes": [{"domain": "heartbeat"}]}

        def request(suffix):
            requests.append(suffix)
            if len(requests) > 100:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": []}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": runs}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                return {"total_count": 1, "artifacts": [artifacts[run_id]]}
            if suffix.endswith("/attempts/1/jobs?per_page=100"):
                return {"total_count": 1, "jobs": [{
                    "steps": [
                        {"name": name, "status": "completed", "conclusion": "success"}
                        for name in (
                            "Capture immutable state transition event",
                            "Upload immutable state transition event",
                            UPLOAD_STEPS["runtime-worker"]["heartbeat"],
                        )
                    ],
                }]}
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = request

        def archive(artifact_id):
            requests.append(f"archive:{artifact_id}")
            if len(requests) > 100:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            return b"event archive"

        reader.archive = archive
        with patch("state_journal.transport.WORKFLOW_PRODUCERS",
                   {"runtime-hourly-sync": "runtime-worker"}), \
             patch("state_journal.transport.extract_json", return_value=event), \
             patch("state_journal.transport.validate_event"), \
             patch("state_journal.transport.validate_provider_event",
                   return_value=(event, {})):
            artifacts = reader.list_recent_journal_artifacts("2026-10-01T00:00:00Z")
            self.assertEqual(len(artifacts), 30)
            for artifact in artifacts:
                self.assertEqual(reader.event(artifact, UPLOAD_STEPS), (event, {}))

        self.assertEqual(len(requests), 92)
        self.assertFalse(any(
            request.endswith("/attempts/1") for request in requests
        ))

    def test_attempt_mismatch_does_not_reuse_latest_run_metadata(self):
        reader = object.__new__(GitHubReader)
        latest_attempt = {"id": 301, "run_attempt": 2}
        requested_attempt = {"id": 301, "run_attempt": 1}
        reader._workflow_run_cache = {(301, 2): latest_attempt}
        calls = []

        def request(suffix):
            calls.append(suffix)
            return requested_attempt

        reader.get = request

        self.assertIs(reader._event_source_run(301, 1), requested_attempt)
        self.assertEqual(calls, ["/actions/runs/301/attempts/1"])


if __name__ == "__main__":
    unittest.main()
