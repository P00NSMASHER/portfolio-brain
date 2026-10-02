"""Regression coverage for high-volume bounded journal artifact discovery."""
import unittest
from unittest.mock import patch

from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader


CREATED = "2026-10-01T03:18:34Z"


def workflow_run(run_id, workflow, created_at):
    return {
        "id": run_id,
        "path": f".github/workflows/{workflow}.yml",
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


class ArtifactBatchBudgetRegressionTests(unittest.TestCase):
    def test_many_candidate_runs_use_bounded_global_scan_filtered_to_admitted_runs(self):
        producers = {f"producer-{index:02d}": f"producer-{index:02d}" for index in range(48)}
        snapshot = artifact(10, SNAPSHOT_ARTIFACT, "2026-10-01T04:01:00Z", 202)
        producer_runs = {
            1000 + index: workflow_run(
                1000 + index, workflow, "2026-10-01T04:02:00Z"
            )
            for index, workflow in enumerate(producers)
        }
        event_artifacts = [
            artifact(
                2000 + index,
                f"{EVENT_PREFIX}{1000 + index}-{workflow}-{'b' * 40}-1",
                "2026-10-01T04:03:00Z",
                1000 + index,
            )
            for index, workflow in enumerate(producers)
        ]
        unrelated = artifact(
            9999, EVENT_PREFIX + "9999-unregistered-" + "c" * 40 + "-1",
            "2026-10-01T04:03:00Z", 9999,
        )
        reader = object.__new__(GitHubReader)
        calls = []

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [
                    workflow_run(202, "portfolio-state-reducer", "2026-10-01T04:00:00Z")
                ]}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshot]}
            if suffix.startswith("/actions/workflows/"):
                workflow = suffix.split("/actions/workflows/", 1)[1].split(".yml/runs?", 1)[0]
                index = int(workflow.rsplit("-", 1)[1])
                return {"workflow_runs": [producer_runs[1000 + index]]}
            if suffix == "/actions/artifacts?per_page=100&page=1":
                return {"artifacts": [*event_artifacts, unrelated]}
            raise AssertionError("unexpected GitHub request: " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", producers):
            rows = reader.list_recent_journal_artifacts(CREATED)

        self.assertEqual(
            {row["id"] for row in rows},
            {snapshot["id"], *(row["id"] for row in event_artifacts)},
        )
        self.assertIn("/actions/artifacts?per_page=100&page=1", calls)
        self.assertFalse(any(
            call.startswith("/actions/runs/") and call.endswith("/artifacts?per_page=100")
            and not call.startswith("/actions/runs/202/")
            for call in calls
        ))


if __name__ == "__main__":
    unittest.main()
