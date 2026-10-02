"""Regression coverage for reducing artifact requests with one valid snapshot."""
import unittest
from unittest.mock import patch

from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader


def run(run_id, created_at, *, updated_at=None):
    return {
        "id": run_id,
        "created_at": created_at,
        "updated_at": updated_at or created_at,
        "head_branch": "main",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": "success",
    }


def artifact(artifact_id, name, created_at, run_id):
    return {
        "id": artifact_id,
        "name": name,
        "created_at": created_at,
        "expired": False,
        "workflow_run": {"id": run_id, "head_branch": "main", "head_sha": "a" * 40},
    }


class SingleSnapshotBudgetRegressionTests(unittest.TestCase):
    def test_skips_pre_snapshot_terminal_artifacts_but_retains_overlapping_run(self):
        reader = object.__new__(GitHubReader)
        snapshot = artifact(10, SNAPSHOT_ARTIFACT, "2026-10-02T22:01:00Z", 202)
        late_event = artifact(
            30,
            EVENT_PREFIX + "301-runtime-worker-" + "b" * 40 + "-1",
            "2026-10-02T22:03:00Z",
            301,
        )
        calls = []

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [run(202, "2026-10-02T22:00:00Z")]}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshot]}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": [
                    run(301, "2026-10-02T21:59:30Z", updated_at="2026-10-02T22:02:00Z"),
                    run(250, "2026-10-02T20:00:00Z", updated_at="2026-10-02T20:05:00Z"),
                ]}
            if suffix == "/actions/runs/301/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [late_event]}
            if suffix == "/actions/runs/250/artifacts?per_page=100":
                raise AssertionError("pre-snapshot terminal run is already covered")
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {"runtime-hourly-sync": "runtime-worker"}):
            rows = reader.list_recent_journal_artifacts("2026-10-02T03:18:34Z")

        self.assertEqual([row["id"] for row in rows], [30, 10])
        self.assertNotIn("/actions/runs/250/artifacts?per_page=100", calls)


if __name__ == "__main__":
    unittest.main()
