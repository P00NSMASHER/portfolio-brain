"""Regression coverage for ambiguous bounded artifact scans."""
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


class ArtifactScanAmbiguityRegressionTests(unittest.TestCase):
    def test_ambiguous_page_bound_uses_exact_artifacts_for_known_producer_runs(self):
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
            run(301 + index, f"2026-10-02T11:0{index + 1}:00Z")
            for index in range(3)
        ]
        events = {
            producer["id"]: artifact(
                1000 + producer["id"],
                EVENT_PREFIX + f"{producer['id']}-runtime-worker-" + "b" * 40 + "-1",
                producer["created_at"],
                producer["id"],
            )
            for producer in producer_runs
        }
        page_one = [
            {"id": index + 1, "created_at": "2026-10-02T12:30:00Z"}
            for index in range(100)
        ]
        page_two = [
            {"id": 101, "created_at": "2026-10-02T12:31:00Z"},
            *[
                {"id": index + 102, "created_at": "2026-10-02T12:20:00Z"}
                for index in range(99)
            ],
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
                return {"total_count": 1, "artifacts": [snapshots[202]]}
            if suffix == "/actions/runs/201/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshots[201]]}
            if suffix == "/actions/artifacts?per_page=100&page=1":
                return {"artifacts": page_one}
            if suffix == "/actions/artifacts?per_page=100&page=2":
                return {"artifacts": page_two}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/")[3])
                return {"total_count": 1, "artifacts": [events[run_id]]}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {
            "runtime-hourly-sync": "runtime-worker",
        }):
            rows = reader.list_recent_journal_artifacts(
                "2026-10-02T10:00:00Z", max_pages=2
            )

        self.assertEqual(
            {row["id"] for row in rows},
            {9, 10, *(event["id"] for event in events.values())},
        )
        self.assertTrue(all(
            f"/actions/runs/{producer['id']}/artifacts?per_page=100" in calls
            for producer in producer_runs
        ))


if __name__ == "__main__":
    unittest.main()
