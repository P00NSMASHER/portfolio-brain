import unittest
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import EVENT_PREFIX, GitHubReader, SNAPSHOT_ARTIFACT


REPOSITORY = "P00NSMASHER/portfolio-brain"
CREATED = "2026-10-01T03:18:34Z"


def run(run_id, workflow, created_at, *, conclusion="success"):
    return {
        "id": run_id,
        "path": f".github/workflows/{workflow}.yml",
        "created_at": created_at,
        "updated_at": created_at,
        "head_branch": "main",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": conclusion,
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


class ProducerScanBudgetRegressionTests(unittest.TestCase):
    def test_producer_scan_batches_workflows_within_request_budget(self):
        producers = {f"producer-{index:02d}": "test" for index in range(80)}
        reducer_runs = [
            run(201, "portfolio-state-reducer", "2026-10-01T21:00:00Z"),
            run(202, "portfolio-state-reducer", "2026-10-01T22:00:00Z"),
        ]
        snapshots = {
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-10-01T21:01:00Z", 201),
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-10-01T22:01:00Z", 202),
        }
        producer_runs = [
            run(
                1000 + index,
                workflow,
                "2026-10-01T22:10:00Z",
            )
            for index, workflow in enumerate(producers)
        ]
        producer_runs_by_workflow = {
            workflow: producer_runs[index]
            for index, workflow in enumerate(producers)
        }
        event_artifacts = {
            1000 + index: artifact(
                2000 + index,
                f"{EVENT_PREFIX}{1000 + index}-{workflow}-{'b' * 40}-1",
                "2026-10-01T22:11:00Z",
                1000 + index,
            )
            for index, workflow in enumerate(producers)
        }

        reader = GitHubReader("token", max_requests=100)
        request_count = 0

        def get(suffix):
            nonlocal request_count
            request_count += 1
            if request_count > 100:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": reducer_runs}
            if suffix.startswith("/actions/workflows/"):
                workflow = suffix.split("/actions/workflows/", 1)[1].split(".yml/runs?", 1)[0]
                return {"workflow_runs": [producer_runs_by_workflow[workflow]]}
            if suffix.startswith("/actions/runs?branch=main&created="):
                return {"workflow_runs": producer_runs}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                if run_id in snapshots:
                    rows = [snapshots[run_id]]
                else:
                    rows = [event_artifacts[run_id]]
                return {"total_count": len(rows), "artifacts": rows}
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", producers):
            artifacts = reader.list_recent_journal_artifacts(CREATED)

        self.assertEqual(request_count, 84)
        self.assertEqual(len(artifacts), 82)
        self.assertEqual(
            sum(row["name"].startswith(EVENT_PREFIX) for row in artifacts),
            len(producers),
        )


if __name__ == "__main__":
    unittest.main()
