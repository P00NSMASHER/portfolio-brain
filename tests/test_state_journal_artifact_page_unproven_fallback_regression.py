"""Regression coverage for exact-run fallback after an unproven artifact scan."""
import unittest
from unittest.mock import patch

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


class UnprovenArtifactScanFallbackTests(unittest.TestCase):
    def test_unproven_page_bound_uses_exact_producer_run_artifacts(self):
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
            run(301, "2026-10-02T11:10:00Z"),
            run(302, "2026-10-02T11:20:00Z"),
        ]
        events = {
            row["id"]: artifact(
                1000 + row["id"],
                EVENT_PREFIX + f"{row['id']}-runtime-worker-" + "b" * 40 + "-1",
                row["created_at"],
                row["id"],
            )
            for row in producer_runs
        }
        calls = []

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": reducer_runs}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": producer_runs}
            if suffix.startswith("/actions/workflows/"):
                return {"workflow_runs": []}
            if suffix.startswith("/actions/artifacts?per_page=100&page=1"):
                # A single bounded page with row-order inversion cannot prove
                # which producer runs are fully covered by the global scan.
                rows = [
                    {"id": index + 100, "created_at": "2026-10-02T11:30:00Z"}
                    for index in range(99)
                ]
                rows.append({"id": 199, "created_at": "2026-10-02T11:31:00Z"})
                return {"artifacts": rows}
            if suffix in {
                "/actions/runs/202/artifacts?per_page=100",
                "/actions/runs/201/artifacts?per_page=100",
            }:
                run_id = int(suffix.split("/")[3])
                return {"total_count": 1, "artifacts": [snapshots[run_id]]}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/")[3])
                rows = [events[run_id]] if run_id in events else []
                return {"total_count": len(rows), "artifacts": rows}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {"runtime-hourly-sync": "runtime-worker"}):
            rows = reader.list_recent_journal_artifacts(
                "2026-10-02T10:00:00Z", max_pages=1
            )

        self.assertEqual(
            {row["id"] for row in rows},
            {9, 10, events[301]["id"], events[302]["id"]},
        )
        self.assertTrue(all(
            f"/actions/runs/{run_id}/artifacts?per_page=100" in calls
            for run_id in events
        ))


if __name__ == "__main__":
    unittest.main()
