import unittest
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.github_reducer import restore_snapshot
from state_journal.transport import GitHubReader, SNAPSHOT_ARTIFACT, WORKFLOW_PRODUCERS


CREATED = "2026-09-29T16:35:30Z"


def workflow_run(run_id, created_at, *, workflow_id=None, path=None):
    row = {
        "id": run_id,
        "created_at": created_at,
        "updated_at": created_at,
        "head_branch": "main",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": "success",
    }
    if workflow_id is not None:
        row["workflow_id"] = workflow_id
    if path is not None:
        row.update({
            "path": path,
            "repository": {"full_name": "P00NSMASHER/portfolio-brain"},
            "head_repository": {"full_name": "P00NSMASHER/portfolio-brain"},
        })
    return row


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


class BulkDiscoveryBudgetRegressionTests(unittest.TestCase):
    def test_many_enrolled_runs_fit_the_fixed_api_budget(self):
        workflows = sorted(WORKFLOW_PRODUCERS)
        workflow_ids = {workflow: 500 + index for index, workflow in enumerate(workflows)}
        reducer_runs = {
            201: workflow_run(
                201, "2026-09-29T21:00:00Z",
                path=".github/workflows/portfolio-state-reducer.yml",
            ),
            202: workflow_run(
                202, "2026-09-29T22:00:00Z",
                path=".github/workflows/portfolio-state-reducer.yml",
            ),
        }
        snapshots = {
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-09-29T21:01:00Z", 201),
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-09-29T22:01:00Z", 202),
        }
        runs_by_workflow = {workflow: [] for workflow in workflows}
        producer_artifacts = {}
        all_run_rows = []
        next_run_id = 1000
        next_artifact_id = 2000
        for workflow in workflows:
            for _ in range(6):
                run_id = next_run_id
                next_run_id += 1
                producer_run = workflow_run(
                    run_id, "2026-09-29T21:30:00Z",
                    workflow_id=workflow_ids[workflow],
                )
                all_run_rows.append(producer_run)
                runs_by_workflow[workflow].append(producer_run)
                producer_artifacts[run_id] = artifact(
                    next_artifact_id,
                    f"portfolio-state-event-v2-{run_id}-test-{'b' * 40}-1",
                    "2026-09-29T21:31:00Z",
                    run_id,
                )
                next_artifact_id += 1

        reader = object.__new__(GitHubReader)
        request_count = 0

        def count_request():
            nonlocal request_count
            request_count += 1
            if request_count > 100:
                raise ArtifactRestoreError("artifact API request budget exceeded")

        def get(suffix):
            count_request()
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [reducer_runs[202], reducer_runs[201]]}
            if suffix.startswith("/actions/workflows/"):
                workflow = suffix.split("/actions/workflows/", 1)[1].split(".yml/runs?", 1)[0]
                return {"workflow_runs": runs_by_workflow[workflow]}
            if suffix == "/actions/workflows?per_page=100&page=1":
                return {"workflows": [
                    {"id": workflow_ids[name], "path": f".github/workflows/{name}.yml"}
                    for name in workflows
                ]}
            if suffix.startswith("/actions/runs?branch=main&created="):
                return {"workflow_runs": all_run_rows}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                if run_id in snapshots:
                    rows = [snapshots[run_id]]
                else:
                    rows = [producer_artifacts[run_id]]
                return {"total_count": len(rows), "artifacts": rows}
            raise AssertionError(f"Unexpected API request: {suffix}")

        def archive(artifact_id):
            count_request()
            return str(artifact_id).encode()

        reader.get = get
        reader.archive = archive
        states = {b"10": {"sequence": 2}, b"9": {"sequence": 1}}
        with patch("state_journal.github_reducer.artifact_digest"), \
             patch("state_journal.github_reducer.extract_json",
                   side_effect=lambda raw, _member: states[raw]), \
             patch("state_journal.github_reducer.validate_snapshot"):
            artifacts = reader.list_recent_journal_artifacts(CREATED)
            restored = restore_snapshot(reader, artifacts, current_run="999")

        self.assertEqual(restored, {"sequence": 2})
        self.assertEqual(len([row for row in artifacts if row["id"] >= 2000]), len(workflows) * 6)
        self.assertLessEqual(request_count, 100)


if __name__ == "__main__":
    unittest.main()
