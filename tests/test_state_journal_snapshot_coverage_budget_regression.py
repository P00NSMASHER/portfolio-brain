"""Regression coverage for avoiding redundant producer artifact reads."""
import unittest
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader


def run(run_id, created_at, updated_at=None):
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
        "workflow_run": {
            "id": run_id,
            "head_branch": "main",
            "head_sha": "a" * 40,
        },
    }


class SnapshotCoverageBudgetRegressionTests(unittest.TestCase):
    def test_preserves_producers_overlapping_snapshot_while_skipping_covered_history(self):
        reader = object.__new__(GitHubReader)
        snapshots = {
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-10-02T21:10:00Z", 201),
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-10-02T22:10:00Z", 202),
        }
        producer_runs = [
            run(301, "2026-10-02T21:30:00Z", "2026-10-02T21:45:00Z"),
            run(302, "2026-10-02T21:55:00Z", "2026-10-02T22:05:00Z"),
            run(303, "2026-10-02T22:11:00Z", "2026-10-02T22:12:00Z"),
        ]
        historical_workflows = {
            f"producer-{index:02d}": run(
                400 + index, "2026-10-02T20:30:00Z", "2026-10-02T20:45:00Z"
            )
            for index in range(49)
        }
        calls = 0
        requests = []

        def get(suffix):
            nonlocal calls
            calls += 1
            if calls > 100:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            requests.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [
                    run(202, "2026-10-02T22:00:00Z"),
                    run(201, "2026-10-02T21:00:00Z"),
                ]}
            if suffix in {
                "/actions/runs/201/artifacts?per_page=100",
                "/actions/runs/202/artifacts?per_page=100",
            }:
                run_id = int(suffix.split("/")[3])
                return {"total_count": 1, "artifacts": [snapshots[run_id]]}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": producer_runs}
            if suffix.startswith("/actions/workflows/"):
                workflow = suffix.split("/actions/workflows/", 1)[1].split(".yml/runs?", 1)[0]
                return {"workflow_runs": [historical_workflows[workflow]]}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/")[3])
                return {
                    "total_count": 1,
                    "artifacts": [artifact(
                        run_id, EVENT_PREFIX + f"{run_id}-runtime-worker-" + "b" * 40 + "-1",
                        "2026-10-02T22:13:00Z", run_id,
                    )],
                }
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {
            "runtime-hourly-sync": "runtime-worker",
            **{workflow: "test" for workflow in historical_workflows},
        }):
            rows = reader.list_recent_journal_artifacts("2026-10-02T20:00:00Z")

        artifact_requests = {
            int(call.split("/")[3])
            for call in requests
            if call.startswith("/actions/runs/") and call.endswith("/artifacts?per_page=100")
        }
        self.assertEqual(artifact_requests, {201, 202, 301, 302, 303})
        self.assertEqual({row["id"] for row in rows}, {9, 10, 301, 302, 303})
        self.assertLessEqual(calls, 100)


if __name__ == "__main__":
    unittest.main()
