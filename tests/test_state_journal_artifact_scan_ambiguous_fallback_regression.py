"""Regression coverage for ambiguous bounded artifact scans."""
import unittest

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


class AmbiguousArtifactScanFallbackTests(unittest.TestCase):
    def test_unordered_bounded_scan_falls_back_to_exact_run_artifact_queries(self):
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
            run(run_id, f"2026-10-02T11:{minute:02d}:00Z")
            for minute, run_id in enumerate(range(301, 322))
        ]
        events = {
            source["id"]: artifact(
                1000 + source["id"],
                EVENT_PREFIX + f"{source['id']}-runtime-worker-" + "b" * 40 + "-1",
                source["created_at"],
                source["id"],
            )
            for source in producer_runs
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
            if suffix == "/actions/artifacts?per_page=100&page=1":
                rows = [
                    {"id": 1, "created_at": "2026-10-02T12:30:00Z"},
                    {"id": 2, "created_at": "2026-10-02T12:31:00Z"},
                ] + [
                    {"id": index + 3, "created_at": "2026-10-02T12:29:00Z"}
                    for index in range(98)
                ]
                return {"artifacts": rows}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/")[3])
                rows = [events[run_id]] if run_id in events else []
                return {"total_count": len(rows), "artifacts": rows}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        rows = reader.list_recent_journal_artifacts(
            "2026-10-02T10:00:00Z", max_pages=1
        )

        self.assertEqual(
            {row["id"] for row in rows},
            {9, 10} | {event["id"] for event in events.values()},
        )
        self.assertTrue(all(
            f"/actions/runs/{run_id}/artifacts?per_page=100" in calls
            for run_id in events
        ))


if __name__ == "__main__":
    unittest.main()
