"""Regression coverage for exact-name durable-artifact candidate filtering."""
import unittest
from unittest.mock import patch

from state_journal.contracts import JournalError
from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader


def run(run_id, created_at, *, conclusion="success", updated_at=None):
    return {
        "id": run_id,
        "created_at": created_at,
        "updated_at": updated_at or created_at,
        "head_branch": "main",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": conclusion,
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


class ExactNameCandidateFilterTests(unittest.TestCase):
    def test_large_post_overlap_set_exact_queries_only_durable_candidates(self):
        reader = object.__new__(GitHubReader)
        calls = []
        reducer_runs = [
            run(202, "2026-10-02T12:00:00Z"),
            run(201, "2026-10-02T11:00:00Z"),
        ]
        snapshots = {
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-10-02T12:00:30Z", 202),
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-10-02T11:00:30Z", 201),
        }
        producer_runs = [
            run(301, "2026-10-02T11:10:00Z"),
            run(302, "2026-10-02T11:11:00Z"),
            run(303, "2026-10-02T11:12:00Z"),
            run(304, "2026-10-02T11:13:00Z"),
        ]
        durable = artifact(
            1303, "portfolio-runtime-state", "2026-10-02T11:12:30Z", 303
        )
        event = artifact(
            2303,
            EVENT_PREFIX + "303-runtime-worker-" + "b" * 40 + "-1",
            "2026-10-02T11:12:31Z",
            303,
        )

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
            if suffix == "/actions/runs/303/artifacts?per_page=100":
                return {"total_count": 2, "artifacts": [durable, event]}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                raise AssertionError("non-candidate producer run was exact-queried: " + suffix)
            if suffix.startswith("/actions/artifacts?name="):
                if "portfolio-runtime-state" in suffix:
                    return {"total_count": 1, "artifacts": [durable]}
                return {"total_count": 0, "artifacts": []}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch(
            "state_journal.transport.WORKFLOW_PRODUCERS",
            {"runtime-hourly-sync": "runtime-worker"},
        ):
            rows = reader.list_recent_journal_artifacts(
                "2026-10-02T10:00:00Z", max_pages=1
            )

        self.assertEqual({row["id"] for row in rows}, {9, 10, 2303})
        self.assertIn("/actions/runs/303/artifacts?per_page=100", calls)
        self.assertFalse(any("/actions/runs/301/artifacts" in call for call in calls))
        self.assertFalse(any("/actions/runs/302/artifacts" in call for call in calls))
        self.assertFalse(any("/actions/runs/304/artifacts" in call for call in calls))
        self.assertFalse(any("/actions/artifacts?per_page=100" in call for call in calls))
        self.assertGreaterEqual(
            sum("actions/artifacts?name=portfolio-runtime-state" in call for call in calls),
            2,
        )

    def test_exact_name_listing_head_drift_fails_closed(self):
        reader = object.__new__(GitHubReader)
        first = artifact(
            1, "portfolio-runtime-state", "2026-10-02T11:00:00Z", 301
        )
        shifted = artifact(
            2, "portfolio-runtime-state", "2026-10-02T11:01:00Z", 302
        )
        calls = []

        def get(_suffix):
            calls.append(1)
            if len(calls) == 1:
                return {"total_count": 1, "artifacts": [first]}
            return {"total_count": 1, "artifacts": [shifted]}

        reader.get = get
        with self.assertRaisesRegex(JournalError, "changed during bounded scan"):
            reader._scan_exact_named_artifacts(
                "portfolio-runtime-state", max_pages=1
            )

    def test_exact_name_listing_respects_page_bound(self):
        reader = object.__new__(GitHubReader)
        reader.get = lambda _suffix: {
            "total_count": 101,
            "artifacts": [
                artifact(
                    index + 1,
                    "portfolio-runtime-state",
                    "2026-10-02T11:00:00Z",
                    301,
                )
                for index in range(100)
            ],
        }
        with self.assertRaisesRegex(JournalError, "incomplete at page bound"):
            reader._scan_exact_named_artifacts(
                "portfolio-runtime-state", max_pages=1
            )


if __name__ == "__main__":
    unittest.main()
