import io
import json
import unittest
from unittest.mock import patch

from state_journal.transport import (
    EMIT_STEP,
    UPLOAD_STEP,
    GitHubReader,
)


class RunMetadataCacheRegressionTests(unittest.TestCase):
    def test_event_reuses_run_details_from_discovery_for_matching_attempt(self):
        run = {"id": 101, "run_attempt": 1, "head_branch": "main"}
        event = {"producer": "runtime-worker", "changes": [{"domain": "runtime"}]}
        jobs = {
            "total_count": 1,
            "jobs": [{
                "id": 202,
                "run_id": 101,
                "run_attempt": 1,
                "steps": [{
                    "name": name,
                    "status": "completed",
                    "conclusion": "success",
                } for name in (EMIT_STEP, UPLOAD_STEP, "Upload runtime state")],
            }],
        }
        reader = GitHubReader("token", max_requests=1)
        reader._runs_by_id = {101: run}
        reader.archive = lambda _artifact_id: b"immutable event archive"
        meta = {
            "id": 303,
            "name": "portfolio-state-event-v2-101-runtime-worker-" + "a" * 40 + "-1",
        }
        with patch("state_journal.transport.extract_json", return_value=event), \
             patch("state_journal.transport.validate_event"), \
             patch("state_journal.transport.validate_provider_event", return_value=(event, {})) as validate, \
             patch(
                 "runtime.artifact_state.open_url",
                 return_value=io.BytesIO(json.dumps(jobs).encode("utf-8")),
             ):
            actual, _ = reader.event(
                meta, {"runtime-worker": {"runtime": "Upload runtime state"}}
            )

        self.assertIs(actual, event)
        self.assertEqual(reader.http.requests, 1)
        self.assertIs(validate.call_args.args[1], run)

    def test_event_fetches_details_when_cached_run_is_a_different_attempt(self):
        reader = object.__new__(GitHubReader)
        cached = {"id": 101, "run_attempt": 2}
        exact_attempt = {"id": 101, "run_attempt": 1}
        reader._runs_by_id = {101: cached}
        requests = []

        def get(suffix):
            requests.append(suffix)
            if suffix == "/actions/runs/101/attempts/1":
                return exact_attempt
            return {
                "total_count": 1,
                "jobs": [{
                    "id": 202,
                    "run_id": 101,
                    "run_attempt": 1,
                    "steps": [{
                        "name": name,
                        "status": "completed",
                        "conclusion": "success",
                    } for name in (EMIT_STEP, UPLOAD_STEP, "Upload runtime state")],
                }],
            }

        reader.get = get
        reader.archive = lambda _artifact_id: b"immutable event archive"
        event = {"producer": "runtime-worker", "changes": [{"domain": "runtime"}]}
        meta = {
            "id": 303,
            "name": "portfolio-state-event-v2-101-runtime-worker-" + "a" * 40 + "-1",
        }
        with patch("state_journal.transport.extract_json", return_value=event), \
             patch("state_journal.transport.validate_event"), \
             patch("state_journal.transport.validate_provider_event", return_value=(event, {})) as validate:
            reader.event(meta, {"runtime-worker": {"runtime": "Upload runtime state"}})

        self.assertEqual(requests, [
            "/actions/runs/101/attempts/1",
            "/actions/runs/101/attempts/1/jobs?per_page=100",
        ])
        self.assertIs(validate.call_args.args[1], exact_attempt)


if __name__ == "__main__":
    unittest.main()
