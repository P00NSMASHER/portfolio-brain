"""Regression coverage for bounded journal-scoped GitHub discovery."""
import unittest
from unittest.mock import patch

from state_journal.contracts import JournalError
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader


def run(run_id, created_at, *, conclusion="success", updated_at=None):
    return {
        "id": run_id,
        "created_at": created_at,
        "updated_at": updated_at or created_at,
        "head_branch": "main",
        "status": "completed",
        "conclusion": conclusion,
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


class ScopedJournalDiscoveryTests(unittest.TestCase):
    def test_repository_scale_restore_uses_closed_workflow_allowlist_not_global_artifact_scan(self):
        reader = object.__new__(GitHubReader)
        calls = []
        snapshot_new = artifact(10, SNAPSHOT_ARTIFACT, "2026-09-29T22:01:00Z", 202)
        snapshot_old = artifact(9, SNAPSHOT_ARTIFACT, "2026-09-29T21:01:00Z", 201)
        event = artifact(
            20,
            EVENT_PREFIX + "301-runtime-worker-" + "b" * 40 + "-1",
            "2026-09-29T21:31:00Z",
            301,
        )
        unrelated = artifact(21, "portfolio-command-center-preview-deadbeef", "2026-09-29T21:31:01Z", 301)

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [
                    run(202, "2026-09-29T22:00:00Z"),
                    run(201, "2026-09-29T21:00:00Z"),
                ]}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshot_new]}
            if suffix == "/actions/runs/201/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshot_old]}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": [run(301, "2026-09-29T21:30:00Z")]}
            if suffix == "/actions/runs/301/artifacts?per_page=100":
                return {"total_count": 2, "artifacts": [event, unrelated]}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {"runtime-hourly-sync": "runtime-worker"}):
            rows = reader.list_recent_journal_artifacts("2026-09-29T16:35:30Z")

        self.assertEqual([row["id"] for row in rows], [10, 20, 9])
        self.assertTrue(any(
            "runtime-hourly-sync.yml/runs?" in call
            and "created=%3E%3D2026-09-29T16%3A35%3A30Z" in call
            for call in calls
        ))
        self.assertFalse(any("/actions/artifacts?" in call for call in calls))
        self.assertFalse(any(row["id"] == 21 for row in rows))

    def test_inflight_producer_before_snapshot_overlap_is_discovered_without_explicit_run_id(self):
        reader = object.__new__(GitHubReader)
        snapshot_new = artifact(10, SNAPSHOT_ARTIFACT, "2026-09-29T22:01:00Z", 202)
        snapshot_old = artifact(9, SNAPSHOT_ARTIFACT, "2026-09-29T21:01:00Z", 201)
        event = artifact(
            20,
            EVENT_PREFIX + "301-runtime-worker-" + "b" * 40 + "-1",
            "2026-09-29T21:01:30Z",
            301,
        )
        calls = []

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [
                    run(202, "2026-09-29T22:00:00Z"),
                    run(201, "2026-09-29T21:00:00Z"),
                ]}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshot_new]}
            if suffix == "/actions/runs/201/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshot_old]}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": [
                    run(301, "2026-09-29T20:59:30Z", updated_at="2026-09-29T21:02:00Z")
                ]}
            if suffix == "/actions/runs/301/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [event]}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {"runtime-hourly-sync": "runtime-worker"}):
            rows = reader.list_recent_journal_artifacts("2026-09-29T16:35:30Z")

        self.assertIn(20, [row["id"] for row in rows])
        self.assertTrue(any(
            "runtime-hourly-sync.yml/runs?" in call
            and "created=%3E%3D2026-09-29T16%3A35%3A30Z" in call
            for call in calls
        ))

    def test_terminal_history_before_snapshot_overlap_skips_artifact_fetch(self):
        reader = object.__new__(GitHubReader)
        snapshot_new = artifact(10, SNAPSHOT_ARTIFACT, "2026-09-29T22:01:00Z", 202)
        snapshot_old = artifact(9, SNAPSHOT_ARTIFACT, "2026-09-29T21:01:00Z", 201)
        late_event = artifact(
            20,
            EVENT_PREFIX + "302-runtime-worker-" + "b" * 40 + "-1",
            "2026-09-29T21:01:30Z",
            302,
        )
        calls = []

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [
                    run(202, "2026-09-29T22:00:00Z"),
                    run(201, "2026-09-29T21:00:00Z"),
                ]}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshot_new]}
            if suffix == "/actions/runs/201/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshot_old]}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": [
                    run(302, "2026-09-29T20:59:30Z", updated_at="2026-09-29T21:02:00Z"),
                    run(250, "2026-09-29T18:00:00Z", updated_at="2026-09-29T18:05:00Z"),
                ]}
            if suffix == "/actions/runs/302/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [late_event]}
            if suffix == "/actions/runs/250/artifacts?per_page=100":
                raise AssertionError("historical terminal run should be covered by predecessor snapshot")
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {"runtime-hourly-sync": "runtime-worker"}):
            rows = reader.list_recent_journal_artifacts("2026-09-29T16:35:30Z")

        self.assertIn(20, [row["id"] for row in rows])
        self.assertFalse(any("/actions/runs/250/artifacts" in call for call in calls))

    def test_producer_started_before_recent_reducers_is_not_lost_if_event_publishes_later(self):
        reader = object.__new__(GitHubReader)
        snapshot_new = artifact(10, SNAPSHOT_ARTIFACT, "2026-09-29T22:01:00Z", 202)
        snapshot_old = artifact(9, SNAPSHOT_ARTIFACT, "2026-09-29T21:01:00Z", 201)
        event = artifact(
            20,
            EVENT_PREFIX + "301-runtime-worker-" + "b" * 40 + "-1",
            "2026-09-29T21:01:30Z",
            301,
        )
        calls = []

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [
                    run(202, "2026-09-29T22:00:00Z"),
                    run(201, "2026-09-29T21:00:00Z"),
                ]}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshot_new]}
            if suffix == "/actions/runs/201/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshot_old]}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": []}
            if suffix == "/actions/runs/301":
                row = run(301, "2026-09-29T20:59:30Z")
                row["path"] = ".github/workflows/runtime-hourly-sync.yml"
                return row
            if suffix == "/actions/runs/301/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [event]}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {"runtime-hourly-sync": "runtime-worker"}):
            rows = reader.list_recent_journal_artifacts(
                "2026-09-29T16:35:30Z", explicit_run_ids=[301]
            )

        self.assertIn(20, [row["id"] for row in rows])
        self.assertTrue(any(call == "/actions/runs/301" for call in calls))
        self.assertTrue(any(
            "runtime-hourly-sync.yml/runs?" in call
            and "created=%3E%3D2026-09-29T21%3A00%3A00Z" in call
            for call in calls
        ))

    def test_per_run_artifact_overflow_fails_closed(self):
        reader = object.__new__(GitHubReader)
        snap = artifact(10, SNAPSHOT_ARTIFACT, "2026-09-29T22:01:00Z", 202)

        def get(suffix):
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [run(202, "2026-09-29T22:00:00Z")]}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 101, "artifacts": [snap]}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {}), \
             self.assertRaisesRegex(JournalError, "Run artifact listing incomplete"):
            reader.list_recent_journal_artifacts("2026-09-29T16:35:30Z")


if __name__ == "__main__":
    unittest.main()
