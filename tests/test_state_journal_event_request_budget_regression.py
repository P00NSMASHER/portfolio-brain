"""Regression coverage for reusing discovered producer run metadata."""
import unittest
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import GitHubReader


class EventRequestBudgetRegressionTests(unittest.TestCase):
    def test_event_reuses_discovered_run_when_request_budget_is_nearly_exhausted(self):
        reader = object.__new__(GitHubReader)
        reader._source_runs = {
            101: {
                "id": 101,
                "run_attempt": 1,
                "head_sha": "b" * 40,
                "path": ".github/workflows/runtime-hourly-sync.yml",
            }
        }
        request_count = 98
        requests = []

        def count_request(suffix):
            nonlocal request_count
            request_count += 1
            if request_count > 100:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            requests.append(suffix)

        def get(suffix):
            count_request(suffix)
            if suffix == "/actions/runs/101/attempts/1":
                return reader._source_runs[101]
            if suffix.endswith("/jobs?per_page=100"):
                return {"jobs": [], "total_count": 0}
            raise AssertionError(f"Unexpected API request: {suffix}")

        def archive(artifact_id):
            count_request(f"/actions/artifacts/{artifact_id}/zip")
            return b"event archive"

        reader.get = get
        reader.archive = archive
        metadata = {
            "id": 201,
            "name": f"portfolio-state-event-v2-101-runtime-worker-{'b' * 40}-1",
        }
        event = {"event_id": "event-101"}
        evidence = {"source_run_id": 101}

        with patch("state_journal.transport.extract_json", return_value=event), \
             patch("state_journal.transport.validate_event"), \
             patch("state_journal.transport.validate_provider_event",
                   return_value=(event, evidence)):
            self.assertEqual(reader.event(metadata, {}), (event, evidence))

        self.assertEqual(request_count, 100)
        self.assertEqual(len(requests), 2)
        self.assertNotIn("/actions/runs/101/attempts/1", requests)


if __name__ == "__main__":
    unittest.main()
