import unittest
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.production_reader import _recent_artifacts
from state_journal.transport import GitHubReader


CREATED = "2026-10-01T03:18:34Z"
PRODUCER_COUNT = 47


class GlobalRunScanRegressionTests(unittest.TestCase):
    def test_canonical_discovery_stays_within_budget_across_many_producer_runs(self):
        producer_workflows = {
            f"producer-{index:02d}": "test" for index in range(PRODUCER_COUNT)
        }
        runs = []
        artifacts_by_run = {}
        for workflow_index, workflow in enumerate(producer_workflows):
            for attempt in range(2):
                run_id = 1000 + workflow_index * 2 + attempt
                run = {
                    "id": run_id,
                    "path": f".github/workflows/{workflow}.yml",
                    "created_at": "2026-10-01T21:00:00Z",
                    "updated_at": "2026-10-01T21:01:00Z",
                    "head_branch": "main",
                    "head_sha": "a" * 40,
                    "status": "completed",
                    "conclusion": "success",
                }
                runs.append(run)
                artifacts_by_run[run_id] = {
                    "total_count": 1,
                    "artifacts": [{
                        "id": 2000 + workflow_index * 2 + attempt,
                        "name": f"portfolio-state-event-v2-{run_id}-test-{'a' * 40}-1",
                        "created_at": run["updated_at"],
                        "expired": False,
                        "workflow_run": {
                            "id": run_id,
                            "head_branch": "main",
                            "head_sha": run["head_sha"],
                        },
                    }],
                }

        reader = object.__new__(GitHubReader)
        request_count = 0

        def get(suffix):
            nonlocal request_count
            request_count += 1
            if request_count > 100:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": []}
            if suffix.startswith("/actions/workflows/"):
                workflow_path = suffix.split("/actions/workflows/", 1)[1].split("/runs?", 1)[0]
                return {"workflow_runs": [
                    run for run in runs
                    if run["path"] == f".github/workflows/{workflow_path}"
                ]}
            if suffix.startswith("/actions/runs?"):
                return {"workflow_runs": runs + [{
                    "id": 9999,
                    "path": ".github/workflows/unregistered.yml",
                    "created_at": "2026-10-01T21:00:00Z",
                }]}
            if suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                return artifacts_by_run[run_id]
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", producer_workflows):
            with self.assertRaisesRegex(ArtifactRestoreError, "request budget exceeded"):
                reader.list_recent_journal_artifacts(CREATED)
            request_count = 0
            rows = _recent_artifacts(reader, CREATED, max_pages=20)

        self.assertEqual(len(rows), PRODUCER_COUNT * 2)
        self.assertEqual(request_count, PRODUCER_COUNT * 2 + 2)


if __name__ == "__main__":
    unittest.main()
