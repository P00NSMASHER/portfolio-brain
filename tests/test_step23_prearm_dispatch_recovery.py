import unittest
import urllib.error
from unittest.mock import patch

from acceptance import step23_prearm_preflight as preflight


SHA = "a" * 40


def completed_row(correlation: str, run_id: int = 7) -> dict:
    return {
        "id": run_id,
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": SHA,
        "display_title": correlation,
        "status": "completed",
        "conclusion": "success",
        "created_at": "2026-10-07T15:00:00Z",
        "updated_at": "2026-10-07T15:01:00Z",
    }


class DispatchRecoveryTests(unittest.TestCase):
    def test_accepted_500_is_recovered_by_exact_correlation_without_resend(self):
        correlation = "prearm-12345-2-runtime-hourly-sync"
        row = completed_row(correlation)

        class API:
            def __init__(self):
                self.post_calls = 0

            def post(self, path, payload):
                self.post_calls += 1
                raise urllib.error.HTTPError(path, 500, "Internal Server Error", {}, None)

            def get(self, path):
                if path == "/branches/main":
                    return {"commit": {"sha": SHA}}
                if path.startswith("/actions/workflows/"):
                    return {"workflow_runs": [row]}
                if path == "/actions/runs/7":
                    return row
                raise AssertionError(path)

        api = API()
        result = preflight.dispatch(
            api,
            workflow="runtime-hourly-sync",
            filename="runtime-hourly-sync.yml",
            exact_sha=SHA,
            correlation=correlation,
        )
        self.assertEqual(api.post_calls, 1)
        self.assertEqual(result["run_id"], 7)
        self.assertEqual(result["dispatch_transient_http_statuses"], [500])

    def test_unaccepted_transient_5xx_retries_once_after_bounded_discovery(self):
        correlation = "prearm-12345-3-portfolio-autonomous-scheduler"
        row = completed_row(correlation, 8)

        class API:
            def __init__(self):
                self.post_calls = 0

            def post(self, path, payload):
                self.post_calls += 1
                if self.post_calls == 1:
                    raise urllib.error.HTTPError(path, 503, "Service Unavailable", {}, None)

            def get(self, path):
                if path == "/branches/main":
                    return {"commit": {"sha": SHA}}
                raise AssertionError(path)

        api = API()
        timeout = RuntimeError(
            "timed out locating correlated pre-arm run for "
            "portfolio-autonomous-scheduler.yml"
        )
        with patch.object(preflight, "wait_for_correlated_run", side_effect=[timeout, row]):
            result = preflight.dispatch(
                api,
                workflow="portfolio-autonomous-scheduler",
                filename="portfolio-autonomous-scheduler.yml",
                exact_sha=SHA,
                correlation=correlation,
            )
        self.assertEqual(api.post_calls, 2)
        self.assertEqual(result["run_id"], 8)
        self.assertEqual(result["dispatch_transient_http_statuses"], [503])

    def test_nontransient_dispatch_error_is_not_retried(self):
        correlation = "prearm-12345-4-hunter-autonomous-cycle"

        class API:
            def __init__(self):
                self.post_calls = 0

            def post(self, path, payload):
                self.post_calls += 1
                raise urllib.error.HTTPError(path, 422, "Unprocessable Entity", {}, None)

            def get(self, path):
                if path == "/branches/main":
                    return {"commit": {"sha": SHA}}
                raise AssertionError(path)

        api = API()
        with self.assertRaises(urllib.error.HTTPError):
            preflight.dispatch(
                api,
                workflow="hunter-autonomous-cycle",
                filename="hunter-autonomous-cycle.yml",
                exact_sha=SHA,
                correlation=correlation,
            )
        self.assertEqual(api.post_calls, 1)


if __name__ == "__main__":
    unittest.main()
