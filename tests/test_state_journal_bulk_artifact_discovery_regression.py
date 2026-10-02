import unittest
from unittest.mock import patch

from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader


CREATED = "2026-10-01T03:18:34Z"


def run(run_id, created_at):
    return {
        "id": run_id,
        "created_at": created_at,
        "updated_at": created_at,
        "head_branch": "main",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": "success",
    }


def artifact(artifact_id, name, created_at, run_id):
    return {
        "id": artifact_id,
        "name": name,
        "created_at": created_at,
        "expired": False,
        "workflow_run": {"id": run_id, "head_branch": "main", "head_sha": "a" * 40},
    }


class BulkArtifactDiscoveryRegressionTests(unittest.TestCase):
    def test_many_producer_runs_use_run_scoped_artifact_discovery(self):
        producers = {f"producer-{index:02d}": "test" for index in range(47)}
        reducer_runs = {
            201: run(201, "2026-10-01T21:00:00Z"),
            202: run(202, "2026-10-01T22:00:00Z"),
        }
        snapshots = {
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-10-01T21:01:00Z", 201),
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-10-01T22:01:00Z", 202),
        }
        producer_runs = {
            workflow: run(1000 + index, "2026-10-01T22:02:00Z")
            for index, workflow in enumerate(producers)
        }
        events = [
            artifact(
                2000 + index,
                f"{EVENT_PREFIX}{1000 + index}-{workflow}-{'b' * 40}-1",
                "2026-10-01T22:03:00Z",
                1000 + index,
            )
            for index, workflow in enumerate(producers)
        ]
        unrelated = artifact(
            3000, "portfolio-command-center-preview-unrelated",
            "2026-10-01T22:03:00Z", 9999,
        )

        reader = object.__new__(GitHubReader)
        requests = 0

        def get(suffix):
            nonlocal requests
            requests += 1
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [reducer_runs[202], reducer_runs[201]]}
            if suffix.startswith("/actions/workflows/"):
                workflow = suffix.split("/actions/workflows/", 1)[1].split(".yml/runs?", 1)[0]
                return {"workflow_runs": [producer_runs[workflow]]}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                if run_id in snapshots:
                    rows = [snapshots[run_id]]
                else:
                    rows = [events[run_id - 1000], unrelated]
                return {"total_count": len(rows), "artifacts": rows}
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", producers):
            rows = reader.list_recent_journal_artifacts(CREATED)

        self.assertEqual(requests, len(producers) * 2 + 3)
        self.assertEqual(
            {row["id"] for row in rows},
            {9, 10, *(2000 + index for index in range(len(producers)))},
        )
        self.assertNotIn(3000, {row["id"] for row in rows})


if __name__ == "__main__":
    unittest.main()
