"""Regression coverage for bounded semantic journal event discovery."""
import unittest
from unittest.mock import patch

from state_journal.contracts import JournalError
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader


SHA = "a" * 40


def run(run_id, created_at, *, conclusion="success"):
    return {
        "id": run_id,
        "created_at": created_at,
        "updated_at": created_at,
        "head_branch": "main",
        "head_sha": SHA,
        "status": "completed",
        "conclusion": conclusion,
        "run_attempt": 1,
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
            "head_sha": SHA,
        },
    }


class StateArtifactDiscoveryTests(unittest.TestCase):
    def test_complete_exact_name_lists_identify_only_possible_event_runs(self):
        reader = object.__new__(GitHubReader)
        calls = []

        def get(suffix):
            calls.append(suffix)
            if "name=portfolio-runtime-state" in suffix:
                return {
                    "total_count": 1,
                    "artifacts": [
                        artifact(9001, "portfolio-runtime-state", "2026-10-02T12:00:00Z", 301)
                    ],
                }
            if (
                "name=portfolio-agent-heartbeat-state" in suffix
                or "name=portfolio-cost-governor-state" in suffix
            ):
                return {"total_count": 0, "artifacts": []}
            raise AssertionError("unexpected request: " + suffix)

        reader.get = get
        with patch(
            "state_journal.transport.WORKFLOW_PRODUCERS",
            {"runtime-hourly-sync": "runtime-worker"},
        ):
            matched = reader._runs_with_published_state_artifacts(
                {301, 302, 303}, max_pages=20
            )

        self.assertEqual(matched, {301})
        self.assertEqual(len(calls), 3)
        self.assertTrue(all("name=" in call for call in calls))

    def test_multi_page_name_scan_rechecks_page_one_stability(self):
        reader = object.__new__(GitHubReader)
        calls = []
        page1 = [
            artifact(
                10000 + index,
                "portfolio-runtime-state",
                "2026-10-02T12:00:00Z",
                400 + index,
            )
            for index in range(100)
        ]
        page2 = [
            artifact(20000, "portfolio-runtime-state", "2026-10-02T11:00:00Z", 301)
        ]

        def get(suffix):
            calls.append(suffix)
            if "name=portfolio-runtime-state" in suffix:
                if "page=2" in suffix:
                    return {"total_count": 101, "artifacts": page2}
                return {"total_count": 101, "artifacts": page1}
            if (
                "name=portfolio-agent-heartbeat-state" in suffix
                or "name=portfolio-cost-governor-state" in suffix
            ):
                return {"total_count": 0, "artifacts": []}
            raise AssertionError("unexpected request: " + suffix)

        reader.get = get
        with patch(
            "state_journal.transport.WORKFLOW_PRODUCERS",
            {"runtime-hourly-sync": "runtime-worker"},
        ):
            matched = reader._runs_with_published_state_artifacts({301}, max_pages=20)

        self.assertEqual(matched, {301})
        runtime_calls = [call for call in calls if "name=portfolio-runtime-state" in call]
        self.assertEqual(len(runtime_calls), 3)
        self.assertTrue(runtime_calls[0].endswith("page=1"))
        self.assertTrue(runtime_calls[1].endswith("page=2"))
        self.assertTrue(runtime_calls[2].endswith("page=1"))

    def test_multi_page_name_scan_fails_closed_if_provider_count_changes(self):
        reader = object.__new__(GitHubReader)
        page1 = [
            artifact(
                10000 + index,
                "portfolio-runtime-state",
                "2026-10-02T12:00:00Z",
                400 + index,
            )
            for index in range(100)
        ]

        def get(suffix):
            if "name=portfolio-runtime-state" in suffix:
                if "page=1" in suffix:
                    return {"total_count": 101, "artifacts": page1}
                return {
                    "total_count": 102,
                    "artifacts": [
                        artifact(20000, "portfolio-runtime-state", "2026-10-02T11:00:00Z", 301)
                    ],
                }
            if (
                "name=portfolio-agent-heartbeat-state" in suffix
                or "name=portfolio-cost-governor-state" in suffix
            ):
                return {"total_count": 0, "artifacts": []}
            raise AssertionError("unexpected request: " + suffix)

        reader.get = get
        with patch(
            "state_journal.transport.WORKFLOW_PRODUCERS",
            {"runtime-hourly-sync": "runtime-worker"},
        ):
            with self.assertRaisesRegex(
                JournalError, "count changed during bounded scan"
            ):
                reader._runs_with_published_state_artifacts({301}, max_pages=20)

    def test_large_post_overlap_tail_queries_only_state_publishing_candidates(self):
        reader = object.__new__(GitHubReader)
        calls = []
        reducer_runs = [
            run(202, "2026-10-02T12:00:00Z"),
            run(201, "2026-10-02T11:00:00Z"),
        ]
        snapshots = {
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-10-02T12:00:30Z", 202),
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-10-02T11:00:30Z", 201),
        }
        producer_runs = [
            run(301 + index, f"2026-10-02T11:{10 + index:02d}:00Z", conclusion="failure")
            for index in range(21)
        ]
        event = artifact(
            8001,
            EVENT_PREFIX + "301-runtime-worker-" + SHA + "-1",
            "2026-10-02T11:10:30Z",
            301,
        )

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": reducer_runs}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": producer_runs}
            if suffix.startswith("/actions/workflows/"):
                return {"workflow_runs": []}
            if suffix in {
                "/actions/runs/202/artifacts?per_page=100",
                "/actions/runs/201/artifacts?per_page=100",
            }:
                run_id = int(suffix.split("/")[3])
                return {"total_count": 1, "artifacts": [snapshots[run_id]]}
            if suffix == "/actions/runs/301/artifacts?per_page=100":
                return {"total_count": 2, "artifacts": [
                    artifact(7001, "portfolio-runtime-state", "2026-10-02T11:10:20Z", 301),
                    event,
                ]}
            if "name=portfolio-runtime-state" in suffix:
                return {"total_count": 1, "artifacts": [
                    artifact(7001, "portfolio-runtime-state", "2026-10-02T11:10:20Z", 301)
                ]}
            if (
                "name=portfolio-agent-heartbeat-state" in suffix
                or "name=portfolio-cost-governor-state" in suffix
            ):
                return {"total_count": 0, "artifacts": []}
            raise AssertionError("unexpected request: " + suffix)

        reader.get = get
        with patch(
            "state_journal.transport.WORKFLOW_PRODUCERS",
            {"runtime-hourly-sync": "runtime-worker"},
        ):
            rows = reader.list_recent_journal_artifacts(
                "2026-10-02T10:00:00Z", max_pages=20
            )

        self.assertEqual({row["id"] for row in rows}, {9, 10, 8001})
        exact_producer_queries = [
            call for call in calls
            if call.startswith("/actions/runs/")
            and call.endswith("/artifacts?per_page=100")
            and call not in {
                "/actions/runs/202/artifacts?per_page=100",
                "/actions/runs/201/artifacts?per_page=100",
            }
        ]
        self.assertEqual(exact_producer_queries, ["/actions/runs/301/artifacts?per_page=100"])
        self.assertFalse(any(
            call.startswith("/actions/artifacts?per_page=100")
            for call in calls
        ))


if __name__ == "__main__":
    unittest.main()
