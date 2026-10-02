"""Regression coverage for bounded journal artifact discovery under artifact volume."""
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


class ArtifactPageOverflowFallbackTests(unittest.TestCase):
    def _base(self, producer_runs):
        reducer_runs = [
            run(202, "2026-10-02T12:00:00Z"),
            run(201, "2026-10-02T11:00:00Z"),
        ]
        snapshots = {
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-10-02T12:00:30Z", 202),
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-10-02T11:00:30Z", 201),
        }
        return reducer_runs, snapshots, producer_runs

    def test_high_run_volume_uses_exact_durable_candidates_not_global_scan(self):
        producer_runs = [
            run(run_id, f"2026-10-02T11:{minute:02d}:00Z")
            for minute, run_id in enumerate(range(301, 323))
        ]
        reducer_runs, snapshots, _ = self._base(producer_runs)
        durables = {
            row["id"]: artifact(
                3000 + row["id"],
                "portfolio-runtime-state",
                row["created_at"],
                row["id"],
            )
            for row in producer_runs
        }
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
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshots[202]]}
            if suffix == "/actions/runs/201/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshots[201]]}
            if suffix.startswith("/actions/artifacts?name="):
                if "portfolio-runtime-state" in suffix:
                    rows = list(durables.values())
                    return {"total_count": len(rows), "artifacts": rows}
                return {"total_count": 0, "artifacts": []}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/")[3])
                rows = [durables[run_id], events[run_id]]
                return {"total_count": len(rows), "artifacts": rows}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader = object.__new__(GitHubReader)
        reader.get = get
        with patch(
            "state_journal.transport.WORKFLOW_PRODUCERS",
            {"runtime-hourly-sync": "runtime-worker"},
        ):
            rows = reader.list_recent_journal_artifacts(
                "2026-10-02T10:00:00Z", max_pages=1
            )

        expected_ids = {9, 10} | {event["id"] for event in events.values()}
        self.assertEqual({row["id"] for row in rows}, expected_ids)
        self.assertFalse(any("/actions/artifacts?per_page=100" in call for call in calls))
        self.assertTrue(any("actions/artifacts?name=portfolio-runtime-state" in call for call in calls))
        self.assertTrue(all(
            f"/actions/runs/{run_id}/artifacts?per_page=100" in calls
            for run_id in events
        ))

    def test_exact_durable_filter_queries_only_candidate_runs(self):
        producer_runs = [
            run(301 + minute, f"2026-10-02T11:{minute:02d}:00Z")
            for minute in range(40)
        ]
        reducer_runs, snapshots, _ = self._base(producer_runs)
        candidate_ids = {330, 335}
        durables = {
            run_id: artifact(
                3000 + run_id,
                "portfolio-runtime-state",
                next(row["created_at"] for row in producer_runs if row["id"] == run_id),
                run_id,
            )
            for run_id in candidate_ids
        }
        events = {
            run_id: artifact(
                4000 + run_id,
                EVENT_PREFIX + f"{run_id}-runtime-worker-" + "b" * 40 + "-1",
                next(row["created_at"] for row in producer_runs if row["id"] == run_id),
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
                if "portfolio-runtime-state" in suffix:
                    rows = list(durables.values())
                    return {"total_count": len(rows), "artifacts": rows}
                return {"total_count": 0, "artifacts": []}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/")[3])
                if run_id not in candidate_ids:
                    raise AssertionError("non-candidate run was exact-queried")
                rows = [durables[run_id], events[run_id]]
                return {"total_count": len(rows), "artifacts": rows}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader = object.__new__(GitHubReader)
        reader.get = get
        with patch(
            "state_journal.transport.WORKFLOW_PRODUCERS",
            {"runtime-hourly-sync": "runtime-worker"},
        ):
            rows = reader.list_recent_journal_artifacts(
                "2026-10-02T10:00:00Z", max_pages=1
            )

        ids = {row["id"] for row in rows}
        self.assertEqual(ids, {9, 10} | {row["id"] for row in events.values()})
        self.assertTrue(all(
            f"/actions/runs/{run_id}/artifacts?per_page=100" in calls
            for run_id in candidate_ids
        ))
        self.assertTrue(all(
            f"/actions/runs/{run_id}/artifacts?per_page=100" not in calls
            for run_id in {row["id"] for row in producer_runs} - candidate_ids
        ))


if __name__ == "__main__":
    unittest.main()
