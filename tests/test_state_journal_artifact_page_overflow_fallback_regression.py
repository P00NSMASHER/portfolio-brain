"""Regression coverage for exact-name bounded journal artifact discovery."""
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from state_journal.contracts import JournalError
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader


def run(run_id, created_at):
    return {
        "id": run_id,
        "created_at": created_at,
        "updated_at": created_at,
        "head_branch": "main",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": "success",
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
            "head_sha": "a" * 40,
        },
    }


class ExactNameArtifactIndexRegressionTests(unittest.TestCase):
    def test_large_tail_exact_queries_only_runs_with_durable_artifacts(self):
        reader = object.__new__(GitHubReader)
        reducer_runs = [
            run(202, "2026-10-02T12:00:00Z"),
            run(201, "2026-10-02T11:00:00Z"),
        ]
        snapshots = {
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-10-02T12:00:30Z", 202),
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-10-02T11:00:30Z", 201),
        }
        producer_runs = [
            run(301 + minute, f"2026-10-02T11:{minute:02d}:00Z")
            for minute in range(22)
        ]
        candidate_ids = {305, 319}
        durable = {
            "portfolio-runtime-state": [
                artifact(2305, "portfolio-runtime-state", "2026-10-02T11:05:30Z", 305),
                artifact(2319, "portfolio-runtime-state", "2026-10-02T11:19:30Z", 319),
            ],
            "portfolio-agent-heartbeat-state": [],
            "portfolio-cost-governor-state": [],
        }
        events = {
            run_id: artifact(
                3000 + run_id,
                EVENT_PREFIX + f"{run_id}-runtime-worker-" + "a" * 40 + "-1",
                f"2026-10-02T11:{run_id - 301:02d}:40Z",
                run_id,
            )
            for run_id in candidate_ids
        }
        calls = []

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": reducer_runs}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": producer_runs}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshots[202]]}
            if suffix == "/actions/runs/201/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshots[201]]}
            if suffix.startswith("/actions/artifacts?name="):
                query = parse_qs(urlparse("https://example.invalid" + suffix).query)
                name = query["name"][0]
                rows = durable.get(name, [])
                return {"total_count": len(rows), "artifacts": rows}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/")[3])
                rows = [events[run_id]] if run_id in events else []
                return {"total_count": len(rows), "artifacts": rows}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch(
            "state_journal.transport.WORKFLOW_PRODUCERS",
            {"runtime-hourly-sync": "runtime-worker"},
        ):
            rows = reader.list_recent_journal_artifacts(
                "2026-10-02T10:00:00Z", max_pages=1
            )

        self.assertEqual(
            {row["id"] for row in rows},
            {9, 10, events[305]["id"], events[319]["id"]},
        )
        exact_run_queries = {
            int(call.split("/")[3])
            for call in calls
            if call.startswith("/actions/runs/")
            and call.endswith("/artifacts?per_page=100")
            and int(call.split("/")[3]) not in {201, 202}
        }
        self.assertEqual(exact_run_queries, candidate_ids)
        self.assertFalse(any(
            call.startswith("/actions/artifacts?per_page=100&page=")
            for call in calls
        ))

    def test_exact_name_listing_must_be_complete(self):
        reader = object.__new__(GitHubReader)
        reader.get = lambda _suffix: {
            "total_count": 2,
            "artifacts": [
                artifact(1, "portfolio-runtime-state", "2026-10-02T11:00:00Z", 301)
            ],
        }
        with self.assertRaisesRegex(JournalError, "incomplete"):
            reader._exact_named_artifacts(
                {"portfolio-runtime-state"}, max_pages=1
            )

    def test_exact_name_listing_respects_existing_page_bound(self):
        reader = object.__new__(GitHubReader)
        reader.get = lambda _suffix: {
            "total_count": 101,
            "artifacts": [
                artifact(
                    index + 1,
                    "portfolio-runtime-state",
                    "2026-10-02T11:00:00Z",
                    301,
                )
                for index in range(100)
            ],
        }
        with self.assertRaisesRegex(JournalError, "exceeds page bound"):
            reader._exact_named_artifacts(
                {"portfolio-runtime-state"}, max_pages=1
            )


if __name__ == "__main__":
    unittest.main()
