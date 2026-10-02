import json
import unittest
from unittest.mock import patch

from state_journal.transport import GitHubReader


class _Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.body


class StateJournalRequestBudgetRegressionTests(unittest.TestCase):
    def test_completed_run_artifact_lists_are_reused_within_the_read_budget(self):
        reader = GitHubReader("token", max_requests=100)
        requested_run_ids = []

        def open_url(request, *, timeout):
            del timeout
            run_id = int(request.full_url.split("/runs/")[1].split("/")[0])
            requested_run_ids.append(run_id)
            return _Response(json.dumps({"total_count": 0, "artifacts": []}).encode())

        with patch("runtime.artifact_state.open_url", side_effect=open_url) as request:
            for run_id in range(1, 52):
                self.assertEqual(reader._run_artifacts(run_id), [])
                self.assertEqual(reader._run_artifacts(run_id), [])

        self.assertEqual(request.call_count, 51)
        self.assertEqual(reader.http.requests, 51)
        self.assertEqual(requested_run_ids, list(range(1, 52)))


if __name__ == "__main__":
    unittest.main()
