import unittest
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.contracts import WORKFLOW_PRODUCERS
from state_journal.github_reducer import restore_snapshot
from state_journal.transport import GitHubReader, SNAPSHOT_ARTIFACT


CREATED = "2026-09-29T16:35:30Z"
SNAPSHOT_TIME = "2026-09-29T22:00:00Z"
PRODUCER_TIME = "2026-09-29T21:30:00Z"


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


class WorkflowRunRequestBudgetRegressionTests(unittest.TestCase):
    def test_registered_workflow_discovery_stays_within_budget_for_many_terminal_runs(self):
        reducer = {
            "id": 201,
            "path": ".github/workflows/portfolio-state-reducer.yml",
            "created_at": SNAPSHOT_TIME,
            "updated_at": SNAPSHOT_TIME,
            "head_branch": "main",
            "head_sha": "a" * 40,
            "status": "completed",
            "conclusion": "success",
            "repository": {"full_name": "P00NSMASHER/portfolio-brain"},
            "head_repository": {"full_name": "P00NSMASHER/portfolio-brain"},
        }
        snapshot = artifact(9, SNAPSHOT_ARTIFACT, SNAPSHOT_TIME, reducer["id"])
        producer_runs = []
        event_artifacts = {}
        index = 0
        for workflow in sorted(WORKFLOW_PRODUCERS):
            for _ in range(6):
                run_id = 1000 + index
                run = {
                    "id": run_id,
                    "path": f".github/workflows/{workflow}.yml",
                    "created_at": PRODUCER_TIME,
                    "updated_at": "2026-09-29T21:31:00Z",
                    "head_branch": "main",
                    "head_sha": "b" * 40,
                    "status": "completed",
                    "conclusion": "success",
                    "run_attempt": 1,
                }
                producer_runs.append(run)
                event_artifacts[run_id] = artifact(
                    2000 + index,
                    f"portfolio-state-event-v2-{run_id}-test-{'b' * 40}-1",
                    "2026-09-29T21:31:00Z",
                    run_id,
                )
                index += 1

        reader = object.__new__(GitHubReader)
        request_count = 0
        calls = []

        def count_request():
            nonlocal request_count
            request_count += 1
            if request_count > 100:
                raise ArtifactRestoreError("artifact API request budget exceeded")

        def get(suffix):
            count_request()
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [reducer]}
            if suffix.startswith("/actions/workflows/"):
                workflow = suffix.split("/actions/workflows/", 1)[1].split(".yml/runs?", 1)[0]
                return {"workflow_runs": [
                    run for run in producer_runs
                    if run["path"] == f".github/workflows/{workflow}.yml"
                ]}
            if suffix.startswith("/actions/runs?"):
                return {"workflow_runs": producer_runs}
            if suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                rows = [snapshot] if run_id == reducer["id"] else [event_artifacts[run_id]]
                return {"total_count": len(rows), "artifacts": rows}
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = get

        def archive(artifact_id):
            count_request()
            return str(artifact_id).encode()

        reader.archive = archive
        with patch("state_journal.github_reducer.artifact_digest"), \
             patch("state_journal.github_reducer.extract_json", return_value={"sequence": 1}), \
             patch("state_journal.github_reducer.validate_snapshot"):
            artifacts = reader.list_recent_journal_artifacts(CREATED)
            restored = restore_snapshot(reader, artifacts, current_run="999")

        self.assertEqual(restored, {"sequence": 1})
        self.assertEqual(len([row for row in artifacts if row["id"] >= 2000]), 6 * len(WORKFLOW_PRODUCERS))
        self.assertEqual(sum(call.startswith("/actions/runs?") for call in calls), 1)
        self.assertLess(request_count, 100)


if __name__ == "__main__":
    unittest.main()
