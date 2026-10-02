"""Regression coverage for ambiguous bounded artifact ordering."""
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


class ArtifactOrderingFallbackRegressionTests(unittest.TestCase):
    def test_ambiguous_repository_order_falls_back_to_exact_run_artifacts(self):
        reader = object.__new__(GitHubReader)
        reducer_runs = [
            run(202, "2026-10-02T12:00:00Z"),
            run(201, "2026-10-02T11:00:00Z"),
        ]
        snapshots = [
            artifact(10, SNAPSHOT_ARTIFACT, "2026-10-02T12:00:30Z", 202),
            artifact(9, SNAPSHOT_ARTIFACT, "2026-10-02T11:00:30Z", 201),
        ]
        producer_runs = [
            run(301, "2026-10-02T11:10:00Z"),
            run(302, "2026-10-02T11:20:00Z"),
        ]
        events = [
            artifact(
                1301 + index,
                EVENT_PREFIX + f"{source_run['id']}-runtime-worker-" + "b" * 40 + "-1",
                source_run["created_at"],
                source_run["id"],
            )
            for index, source_run in enumerate(producer_runs)
        ]
        calls = []

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": reducer_runs}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": producer_runs}
            if suffix.startswith("/actions/workflows/"):
                return {"workflow_runs": []}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshots[0]]}
            if suffix == "/actions/runs/201/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshots[1]]}
            if suffix == "/actions/artifacts?per_page=100&page=1":
                return {"artifacts": [
                    {"id": 500, "created_at": "2026-10-02T11:30:00Z"},
                    {"id": 501, "created_at": "2026-10-02T11:31:00Z"},
                    *[
                        {"id": 502 + index, "created_at": "2026-10-02T11:20:00Z"}
                        for index in range(98)
                    ],
                ]}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                source_run_id = int(suffix.split("/")[3])
                rows = [row for row in events if row["workflow_run"]["id"] == source_run_id]
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

        self.assertEqual({row["id"] for row in rows}, {9, 10, 1301, 1302})
        self.assertTrue(all(
            f"/actions/runs/{source_run['id']}/artifacts?per_page=100" in calls
            for source_run in producer_runs
        ))


if __name__ == "__main__":
    unittest.main()
