"""Regression for reducer recovery when unrelated artifacts exhaust pagination."""
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


class ArtifactPageBoundFallbackRegressionTests(unittest.TestCase):
    def test_page_bound_falls_back_to_artifacts_of_allowlisted_producer_runs(self):
        reader = object.__new__(GitHubReader)
        reducer_new = run(202, "2026-10-02T12:00:00Z")
        reducer_old = run(201, "2026-10-02T11:00:00Z")
        snapshots = {
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-10-02T12:01:00Z", 202),
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-10-02T11:01:00Z", 201),
        }
        producer_runs = [
            run(run_id, "2026-10-02T13:00:00Z")
            for run_id in range(301, 322)
        ]
        producer_artifacts = {
            row["id"]: artifact(
                row["id"] + 1000,
                f"{EVENT_PREFIX}{row['id']}-runtime-worker-{'b' * 40}-1",
                "2026-10-02T13:01:00Z",
                row["id"],
            )
            for row in producer_runs
        }
        calls = []

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [reducer_new, reducer_old]}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshots[202]]}
            if suffix == "/actions/runs/201/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshots[201]]}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": producer_runs}
            if suffix.startswith("/actions/artifacts?per_page=100&page="):
                return {
                    "artifacts": [
                        artifact(index + 5000, "unrelated", "2026-10-02T13:02:00Z", 9000)
                        for index in range(100)
                    ]
                }
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                rows = [producer_artifacts[run_id]] if run_id in producer_artifacts else []
                return {"total_count": len(rows), "artifacts": rows}
            raise AssertionError(f"unexpected GitHub request: {suffix}")

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {"runtime-hourly-sync": "runtime-worker"}):
            rows = reader.list_recent_journal_artifacts("2026-10-02T10:00:00Z")

        self.assertEqual(
            {row["id"] for row in rows},
            {
                snapshots[202]["id"],
                snapshots[201]["id"],
                *(row["id"] for row in producer_artifacts.values()),
            },
        )
        self.assertEqual(sum(call.startswith("/actions/artifacts?") for call in calls), 20)
        self.assertEqual(
            sum("/actions/runs/" in call and call.endswith("/artifacts?per_page=100") for call in calls),
            23,
        )


if __name__ == "__main__":
    unittest.main()
