import unittest
from datetime import datetime, timezone

from operations.reducer_wake import (
    REDUCER_FILE,
    daemon_identity,
    execute,
)

MAIN = "a" * 40
NOW = datetime(2026, 10, 6, 23, 50, tzinfo=timezone.utc)


def consumer(run_id=11, status="in_progress", sha=MAIN):
    return {
        "id": run_id,
        "name": "runtime-hourly-sync",
        "path": ".github/workflows/runtime-hourly-sync.yml",
        "head_branch": "main",
        "head_sha": sha,
        "status": status,
    }


def reducer(run_id=21, status="completed", conclusion="success", updated_at="2026-10-06T23:49:30Z", sha=MAIN):
    return {
        "id": run_id,
        "name": "portfolio-state-reducer",
        "path": ".github/workflows/portfolio-state-reducer.yml",
        "head_branch": "main",
        "head_sha": sha,
        "status": status,
        "conclusion": conclusion,
        "updated_at": updated_at,
    }


class API:
    def __init__(self, rows=None, daemon=None):
        self.rows = rows or []
        self.daemon = daemon
        self.calls = []
        self.requests = 0

    def call(self, path, method="GET", payload=None):
        self.calls.append((path, method, payload))
        self.requests += 1
        if path.startswith("/actions/runs/") and "?" not in path:
            return self.daemon
        if path == "/actions/runs?branch=main&per_page=100":
            return {"workflow_runs": self.rows}
        if method == "POST":
            return {}
        raise AssertionError(path)


class ReducerWakeTests(unittest.TestCase):
    def test_active_consumer_requests_exact_reducer_only(self):
        api = API([consumer()])
        result = execute(api, MAIN, at=NOW)
        self.assertEqual(result["action"], "REDUCER_WAKE_REQUESTED")
        self.assertFalse(result["authority_granted"])
        posts = [call for call in api.calls if call[1] == "POST"]
        self.assertEqual(
            posts,
            [(f"/actions/workflows/{REDUCER_FILE}/dispatches", "POST", {"ref": "main"})],
        )

    def test_active_or_recent_reducer_dedupes_wake(self):
        for row, expected in (
            (reducer(status="in_progress", conclusion=None), "REDUCER_ALREADY_ACTIVE"),
            (reducer(), "RECENT_REDUCER_SUCCESS"),
        ):
            with self.subTest(expected=expected):
                api = API([consumer(), row])
                result = execute(api, MAIN, at=NOW)
                self.assertEqual(result["action"], expected)
                self.assertFalse(any(method == "POST" for _, method, _ in api.calls))

    def test_stale_success_requests_fresh_reducer(self):
        api = API([
            consumer(),
            reducer(updated_at="2026-10-06T23:45:00Z"),
        ])
        result = execute(api, MAIN, at=NOW)
        self.assertEqual(result["action"], "REDUCER_WAKE_REQUESTED")

    def test_no_consumer_or_wrong_main_never_dispatches(self):
        for rows in ([], [consumer(sha="b" * 40)]):
            with self.subTest(rows=rows):
                api = API(rows)
                result = execute(api, MAIN, at=NOW)
                self.assertEqual(result["action"], "NO_ACTIVE_CANONICAL_CONSUMER")
                self.assertFalse(any(method == "POST" for _, method, _ in api.calls))

    def test_daemon_identity_is_exact_main_and_active(self):
        daemon = {
            "id": 88,
            "name": "portfolio-schedule-clock-daemon",
            "path": ".github/workflows/portfolio-schedule-clock-daemon.yml",
            "event": "workflow_dispatch",
            "head_branch": "main",
            "head_sha": MAIN,
            "run_attempt": 2,
            "status": "in_progress",
        }
        self.assertEqual(daemon_identity(API(daemon=daemon), 88, 2, MAIN)["id"], 88)
        with self.assertRaisesRegex(Exception, "exact current main"):
            daemon_identity(API(daemon={**daemon, "head_sha": "b" * 40}), 88, 2, MAIN)


if __name__ == "__main__":
    unittest.main()
