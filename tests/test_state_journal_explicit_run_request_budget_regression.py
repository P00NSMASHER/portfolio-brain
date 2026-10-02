import unittest
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.github_reducer import restore_snapshot
from state_journal.transport import GitHubReader, SNAPSHOT_ARTIFACT


REPOSITORY = "P00NSMASHER/portfolio-brain"
CREATED = "2026-09-29T16:35:30Z"


def workflow_run(run_id, path, created_at):
    return {
        "id": run_id,
        "path": path,
        "created_at": created_at,
        "updated_at": created_at,
        "head_branch": "main",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
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


class ExplicitRunRequestBudgetRegressionTests(unittest.TestCase):
    def test_explicit_trigger_reuses_run_already_scanned_within_request_budget(self):
        producers = {f"producer-{index:02d}": "test" for index in range(47)}
        reducer_runs = {
            201: workflow_run(
                201, ".github/workflows/portfolio-state-reducer.yml",
                "2026-09-29T21:00:00Z",
            ),
            202: workflow_run(
                202, ".github/workflows/portfolio-state-reducer.yml",
                "2026-09-29T22:00:00Z",
            ),
        }
        snapshots = {
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-09-29T21:01:00Z", 201),
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-09-29T22:01:00Z", 202),
        }
        producer_runs = {}
        event_artifacts = {}
        for index, workflow in enumerate(producers):
            run_id = 1000 + index
            producer_runs[workflow] = workflow_run(
                run_id,
                f".github/workflows/{workflow}.yml",
                "2026-09-29T22:30:00Z",
            )
            event_artifacts[run_id] = artifact(
                2000 + index,
                f"portfolio-state-event-v2-{run_id}-test-{'b' * 40}-1",
                "2026-09-29T22:31:00Z",
                run_id,
            )

        reader = GitHubReader("test-token", max_requests=100)
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
                return {"workflow_runs": [producer_runs[workflow]]}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                rows = [snapshots[run_id]] if run_id in snapshots else [event_artifacts[run_id]]
                return {"total_count": len(rows), "artifacts": rows}
            if suffix == "/actions/runs/1000":
                return producer_runs["producer-00"]
            raise AssertionError(f"Unexpected API request: {suffix}")

        def archive(artifact_id):
            count_request()
            return str(artifact_id).encode()

        reader.get = get
        reader.archive = archive
        states = {b"10": {"sequence": 2}, b"9": {"sequence": 1}}
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", producers), \
             patch("state_journal.github_reducer.artifact_digest"), \
             patch("state_journal.github_reducer.extract_json",
                   side_effect=lambda raw, _member: states[raw]), \
             patch("state_journal.github_reducer.validate_snapshot"):
            artifacts = reader.list_recent_journal_artifacts(
                CREATED, explicit_run_ids=[1000]
            )
            restored = restore_snapshot(reader, artifacts, current_run="999")

        self.assertEqual(restored, {"sequence": 2})
        self.assertEqual(request_count, 99)


if __name__ == "__main__":
    unittest.main()
