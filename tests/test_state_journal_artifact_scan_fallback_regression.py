"""Regression coverage for bounded journal artifact discovery fallback."""
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


class ArtifactScanFallbackRegressionTests(unittest.TestCase):
    def test_incomplete_repository_scan_falls_back_to_allowlisted_run_artifacts(self):
        reader = object.__new__(GitHubReader)
        snapshot_new = artifact(10, SNAPSHOT_ARTIFACT, "2026-10-02T12:01:00Z", 202)
        snapshot_old = artifact(9, SNAPSHOT_ARTIFACT, "2026-10-02T11:01:00Z", 201)
        producer_runs = [
            run(
                300 + index,
                f"2026-10-02T12:{index + 1:02d}:00Z",
                updated_at=f"2026-10-02T12:{index + 1:02d}:30Z",
            )
            for index in range(21)
        ]
        producer_artifacts = {
            producer_run["id"]: artifact(
                100 + index,
                EVENT_PREFIX + f"{producer_run['id']}-runtime-worker-" + "b" * 40 + "-1",
                producer_run["updated_at"],
                producer_run["id"],
            )
            for index, producer_run in enumerate(producer_runs)
        }
        calls = []

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [
                    run(202, "2026-10-02T12:00:00Z"),
                    run(201, "2026-10-02T11:00:00Z"),
                ]}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshot_new]}
            if suffix == "/actions/runs/201/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshot_old]}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": producer_runs}
            if suffix.startswith("/actions/artifacts?per_page=100&page=1"):
                return {
                    "artifacts": [
                        artifact(index + 1000, "unrelated-artifact", "2026-10-02T13:00:00Z", 999)
                        for index in range(100)
                    ]
                }
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/")[3])
                event_artifact = producer_artifacts[run_id]
                return {"total_count": 1, "artifacts": [event_artifact]}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {
            "runtime-hourly-sync": "runtime-worker",
        }):
            rows = reader.list_recent_journal_artifacts(
                "2026-10-02T10:00:00Z", max_pages=1
            )

        event_ids = {row["id"] for row in rows if row["name"].startswith(EVENT_PREFIX)}
        self.assertEqual(event_ids, set(range(100, 121)))
        self.assertEqual(sum(call.startswith("/actions/runs/") and "artifacts?" in call
                             for call in calls), 23)
        self.assertEqual(sum(call.startswith("/actions/artifacts?") for call in calls), 1)
        self.assertFalse(any(row["name"] == "unrelated-artifact" for row in rows))


if __name__ == "__main__":
    unittest.main()
