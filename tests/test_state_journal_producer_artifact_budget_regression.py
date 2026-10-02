import unittest
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import GitHubReader, SNAPSHOT_ARTIFACT


CREATED = "2026-10-01T00:00:00Z"
REPOSITORY = "P00NSMASHER/portfolio-brain"


def run(run_id, created_at):
    return {
        "id": run_id,
        "path": ".github/workflows/portfolio-state-reducer.yml",
        "created_at": created_at,
        "updated_at": created_at,
        "head_branch": "main",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
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


class ProducerArtifactBudgetRegressionTests(unittest.TestCase):
    def test_journal_discovery_does_not_spend_one_artifact_request_per_producer_run(self):
        producers = {f"producer-{index:02d}": "test" for index in range(47)}
        reducer_runs = [
            run(202, "2026-10-02T11:00:00Z"),
            run(201, "2026-10-02T10:00:00Z"),
        ]
        snapshots = {
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-10-02T11:01:00Z", 202),
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-10-02T10:01:00Z", 201),
        }
        event = artifact(
            3000,
            "portfolio-state-event-v2-10000-test-" + "b" * 40 + "-1",
            "2026-10-02T11:30:00Z",
            10000,
        )
        unrelated = artifact(3001, "unrelated-preview", "2026-10-02T11:29:00Z", 3000)
        reader = object.__new__(GitHubReader)
        requests = []

        def get(suffix):
            requests.append(suffix)
            if len(requests) > 100:
                raise ArtifactRestoreError("artifact API request budget exceeded")
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": reducer_runs}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                if run_id in snapshots:
                    rows = [snapshots[run_id]]
                else:
                    rows = [artifact(
                        run_id,
                        f"portfolio-state-event-v2-{run_id}-test-{'b' * 40}-1",
                        "2026-10-02T09:01:00Z",
                        run_id,
                    )]
                return {"total_count": len(rows), "artifacts": rows}
            if suffix == "/actions/artifacts?per_page=100&page=1":
                return {"artifacts": [
                    event, unrelated, snapshots[202], snapshots[201],
                ]}
            if suffix.startswith("/actions/workflows/"):
                workflow = suffix.split("/actions/workflows/", 1)[1].split(".yml/runs?", 1)[0]
                base = 10_000 + list(producers).index(workflow) * 2
                return {"workflow_runs": [
                    {
                        "id": base + offset,
                        "created_at": "2026-10-02T11:30:00Z",
                        "updated_at": "2026-10-02T11:31:00Z",
                        "head_branch": "main",
                        "status": "completed",
                        "conclusion": "success",
                    }
                    for offset in (0, 1)
                ]}
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", producers):
            rows = reader.list_recent_journal_artifacts(CREATED)

        self.assertEqual([row["id"] for row in rows], [3000, 10, 9])
        self.assertEqual(len(requests), 51)
        self.assertTrue(any(suffix.startswith("/actions/artifacts?") for suffix in requests))
        self.assertFalse(any(
            suffix.startswith("/actions/runs/10000/artifacts")
            for suffix in requests
        ))


if __name__ == "__main__":
    unittest.main()
