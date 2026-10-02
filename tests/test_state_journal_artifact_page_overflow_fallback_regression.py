"""Regression coverage for bounded journal artifact discovery under artifact volume."""
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


class ArtifactPageOverflowFallbackTests(unittest.TestCase):
    def test_page_bound_falls_back_to_artifacts_for_known_producer_runs(self):
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
            for minute, run_id in enumerate(range(301, 323))
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
                # A full page newer than the requested boundary cannot prove
                # that the repository-wide scan has reached the journal tail.
                return {"artifacts": [
                    {"id": index + 1, "created_at": "2026-10-02T12:30:00Z"}
                    for index in range(100)
                ]}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshots[202]]}
            if suffix == "/actions/runs/201/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshots[201]]}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/")[3])
                rows = [events[run_id]] if run_id in events else []
                return {"total_count": len(rows), "artifacts": rows}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        rows = reader.list_recent_journal_artifacts(
            "2026-10-02T10:00:00Z", max_pages=1
        )

        expected_ids = {9, 10} | {event["id"] for event in events.values()}
        self.assertEqual({row["id"] for row in rows}, expected_ids)
        self.assertTrue(any("/actions/artifacts?per_page=100&page=1" in call for call in calls))
        self.assertTrue(all(
            f"/actions/runs/{run_id}/artifacts?per_page=100" in calls
            for run_id in events
        ))


    def test_partial_monotonic_scan_queries_only_unresolved_older_tail(self):
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
            run(301 + minute, f"2026-10-02T11:{minute:02d}:00Z")
            for minute in range(40)
        ]
        older_ids = {row["id"] for row in producer_runs[:21]}
        newer_ids = {row["id"] for row in producer_runs[21:]}
        scanned_events = {
            330: artifact(
                1330,
                EVENT_PREFIX + "330-runtime-worker-" + "b" * 40 + "-1",
                "2026-10-02T11:30:30Z",
                330,
            ),
            335: artifact(
                1335,
                EVENT_PREFIX + "335-runtime-worker-" + "b" * 40 + "-1",
                "2026-10-02T11:35:30Z",
                335,
            ),
        }
        older_events = {
            run_id: artifact(
                2000 + run_id,
                EVENT_PREFIX + f"{run_id}-runtime-worker-" + "b" * 40 + "-1",
                "2026-10-02T11:20:30Z",
                run_id,
            )
            for run_id in older_ids
        }
        calls = []

        filler = [
            {"id": 5000 + index, "created_at": "2026-10-02T11:20:30Z"}
            for index in range(98)
        ]
        scan_page = [
            scanned_events[335],
            scanned_events[330],
            *filler,
        ]

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
                return {"artifacts": scan_page}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/")[3])
                rows = [older_events[run_id]] if run_id in older_events else []
                return {"total_count": len(rows), "artifacts": rows}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        rows = reader.list_recent_journal_artifacts(
            "2026-10-02T10:00:00Z", max_pages=1
        )

        ids = {row["id"] for row in rows}
        self.assertIn(scanned_events[330]["id"], ids)
        self.assertIn(scanned_events[335]["id"], ids)
        self.assertTrue(all(older_events[run_id]["id"] in ids for run_id in older_ids))
        self.assertTrue(all(
            f"/actions/runs/{run_id}/artifacts?per_page=100" in calls
            for run_id in older_ids
        ))
        self.assertTrue(all(
            f"/actions/runs/{run_id}/artifacts?per_page=100" not in calls
            for run_id in newer_ids
        ))


if __name__ == "__main__":
    unittest.main()
