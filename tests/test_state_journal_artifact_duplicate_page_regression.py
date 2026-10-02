"""Regression coverage for duplicate offset pages in bounded artifact scans."""
import unittest
from datetime import datetime, timedelta, timezone
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


class ArtifactDuplicatePageRegressionTests(unittest.TestCase):
    def test_duplicate_page_does_not_invalidate_later_unseen_page_coverage(self):
        reader = object.__new__(GitHubReader)
        reducer_runs = [
            run(202, "2026-10-02T12:00:00Z"),
            run(201, "2026-10-02T11:00:00Z"),
        ]
        snapshots = {
            202: artifact(500, SNAPSHOT_ARTIFACT, "2026-10-02T12:00:30Z", 202),
            201: artifact(499, SNAPSHOT_ARTIFACT, "2026-10-02T11:00:30Z", 201),
        }
        producer_runs = [
            run(run_id, f"2026-10-02T11:29:{second:02d}Z")
            for run_id, second in zip((301, 302, 303, 304), (50, 49, 48, 47))
        ]
        event_artifacts = [
            artifact(
                600 + index,
                EVENT_PREFIX + f"{source['id']}-runtime-worker-" + "b" * 40 + "-1",
                source["created_at"],
                source["id"],
            )
            for index, source in enumerate(producer_runs)
        ]

        page1 = event_artifacts + [
            artifact(
                index + 1,
                "unrelated-artifact",
                (datetime(2026, 10, 2, 11, 28, tzinfo=timezone.utc) - timedelta(seconds=index)).isoformat(),
                900,
            )
            for index in range(96)
        ]
        page3 = [
            artifact(
                1000 + index,
                "older-unrelated-artifact",
                (datetime(2026, 10, 2, 11, 25, tzinfo=timezone.utc) - timedelta(seconds=index)).isoformat(),
                901,
            )
            for index in range(100)
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
                return {"artifacts": page1}
            if suffix == "/actions/artifacts?per_page=100&page=2":
                # New artifacts arriving between offset requests can make a
                # later page repeat rows already returned by the first page.
                return {"artifacts": page1}
            if suffix == "/actions/artifacts?per_page=100&page=3":
                return {"artifacts": page3}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                raise AssertionError("resolved producer runs should not need per-run artifact reads")
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {"runtime-hourly-sync": "runtime-worker"}):
            rows = reader.list_recent_journal_artifacts(
                "2026-10-02T10:00:00Z", max_pages=3
            )

        self.assertEqual(
            {row["id"] for row in rows},
            {499, 500, *(row["id"] for row in event_artifacts)},
        )
        self.assertIn("/actions/artifacts?per_page=100&page=3", calls)


if __name__ == "__main__":
    unittest.main()
