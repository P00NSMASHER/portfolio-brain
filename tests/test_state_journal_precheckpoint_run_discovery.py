"""Regression coverage for producer runs crossing the journal scan boundary."""
import unittest
from unittest.mock import patch

from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader


def run(run_id, created_at, *, updated_at=None):
    return {
        "id": run_id,
        "created_at": created_at,
        "updated_at": updated_at or created_at,
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
    }


def artifact(artifact_id, name, created_at, run_id):
    return {
        "id": artifact_id,
        "name": name,
        "created_at": created_at,
        "expired": False,
        "workflow_run": {
            "id": run_id,
            "head_branch": "main",
            "head_sha": "a" * 40,
        },
    }


class PrecheckpointProducerDiscoveryTests(unittest.TestCase):
    def test_run_started_before_scan_boundary_but_completed_during_replay_window_is_found(self):
        reader = object.__new__(GitHubReader)
        snapshot_new = artifact(10, SNAPSHOT_ARTIFACT, "2026-09-30T22:01:00Z", 202)
        snapshot_old = artifact(9, SNAPSHOT_ARTIFACT, "2026-09-30T21:01:00Z", 201)
        late_event = artifact(
            20,
            EVENT_PREFIX + "301-runtime-worker-" + "b" * 40 + "-1",
            "2026-09-30T21:01:30Z",
            301,
        )
        crossed_boundary = run(
            301,
            "2026-09-30T10:40:00Z",
            updated_at="2026-09-30T21:02:00Z",
        )
        calls = []

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [
                    run(202, "2026-09-30T22:00:00Z"),
                    run(201, "2026-09-30T21:00:00Z"),
                ]}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshot_new]}
            if suffix == "/actions/runs/201/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshot_old]}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                if "created=%3E%3D2026-09-30T10%3A35%3A30Z" in suffix:
                    return {"workflow_runs": [crossed_boundary]}
                return {"workflow_runs": []}
            if suffix == "/actions/runs/301/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [late_event]}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {"runtime-hourly-sync": "runtime-worker"}):
            rows = reader.list_recent_journal_artifacts("2026-09-30T16:35:30Z")

        self.assertIn(20, [row["id"] for row in rows])
        self.assertTrue(any(
            "created=%3E%3D2026-09-30T10%3A35%3A30Z%20%3C2026-09-30T16%3A35%3A30Z" in call
            for call in calls
        ))


if __name__ == "__main__":
    unittest.main()
