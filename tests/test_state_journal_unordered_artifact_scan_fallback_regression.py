"""Regression coverage for exact-run fallback after an unordered page-bounded scan."""
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


class UnorderedArtifactScanFallbackTests(unittest.TestCase):
    def test_unordered_partial_global_scan_falls_back_to_exact_source_runs(self):
        reader = object.__new__(GitHubReader)
        reducer_runs = [
            run(202, "2026-10-02T12:20:00Z"),
            run(201, "2026-10-02T12:00:00Z"),
        ]
        snapshots = {
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-10-02T12:20:30Z", 202),
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-10-02T12:00:30Z", 201),
        }
        producer_runs = [
            run(301, "2026-10-02T12:10:00Z"),
            run(302, "2026-10-02T12:05:00Z"),
        ]
        events = {
            row["id"]: artifact(
                1000 + row["id"],
                EVENT_PREFIX + f"{row['id']}-runtime-worker-" + "b" * 40 + "-1",
                row["created_at"].replace(":00Z", ":30Z"),
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
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshots[202]]}
            if suffix == "/actions/runs/201/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshots[201]]}
            if suffix.startswith("/actions/artifacts?per_page=100&page=1"):
                rows = [
                    {"id": 500, "created_at": "2026-10-02T12:15:00Z"},
                    {"id": 501, "created_at": "2026-10-02T12:16:00Z"},
                ]
                rows.extend(
                    {"id": 600 + index, "created_at": "2026-10-02T12:14:00Z"}
                    for index in range(98)
                )
                return {"artifacts": rows}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/")[3])
                rows = [events[run_id]] if run_id in events else []
                return {"total_count": len(rows), "artifacts": rows}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {
            "runtime-hourly-sync": "runtime-worker",
        }):
            rows = reader.list_recent_journal_artifacts(
                "2026-10-02T10:00:00Z", max_pages=1
            )

        self.assertEqual(
            {row["id"] for row in rows},
            {9, 10, events[301]["id"], events[302]["id"]},
        )
        self.assertTrue(all(
            f"/actions/runs/{run_id}/artifacts?per_page=100" in calls
            for run_id in (301, 302)
        ))


if __name__ == "__main__":
    unittest.main()
