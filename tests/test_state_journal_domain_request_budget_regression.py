import unittest
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import GitHubReader, SNAPSHOT_ARTIFACT


CREATED = "2026-09-29T16:35:30Z"
OVERLAP = "2026-09-29T21:00:00Z"
PUBLISHED = "2026-09-29T21:30:00Z"


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


class DomainRequestBudgetRegressionTests(unittest.TestCase):
    def test_domain_restore_avoids_unrelated_producer_artifact_requests(self):
        producers = {
            f"producer-{index:02d}": ("TEST", {"heartbeat"} if index < 2 else {"runtime"})
            for index in range(50)
        }
        workflows = {name: name for name in producers}
        reducer_runs = {
            201: run(201, OVERLAP),
            202: run(202, "2026-09-29T22:00:00Z"),
        }
        snapshots = {
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-09-29T21:01:00Z", 201),
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-09-29T22:01:00Z", 202),
        }
        producer_runs = {
            name: run(1000 + index, PUBLISHED)
            for index, name in enumerate(workflows)
        }
        event_artifacts = {
            producer_runs[name]["id"]: artifact(
                2000 + index, f"portfolio-state-event-v2-{1000 + index}-{name}-{'b' * 40}-1",
                PUBLISHED, 1000 + index,
            )
            for index, name in enumerate(workflows)
        }

        def make_reader():
            reader = object.__new__(GitHubReader)
            request_count = 0

            def get(suffix):
                nonlocal request_count
                request_count += 1
                if request_count > 100:
                    raise ArtifactRestoreError("artifact API request budget exceeded")
                if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                    return {"workflow_runs": [reducer_runs[202], reducer_runs[201]]}
                if suffix.startswith("/actions/workflows/"):
                    workflow = suffix.split("/actions/workflows/", 1)[1].split(".yml/runs?", 1)[0]
                    return {"workflow_runs": [producer_runs[workflow]]}
                if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                    run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                    rows = [snapshots[run_id]] if run_id in snapshots else [event_artifacts[run_id]]
                    return {"total_count": len(rows), "artifacts": rows}
                raise AssertionError(f"Unexpected API request: {suffix}")

            reader.get = get
            return reader

        with patch("state_journal.transport.PRODUCERS", producers), \
             patch("state_journal.transport.WORKFLOW_PRODUCERS", workflows):
            with self.assertRaisesRegex(ArtifactRestoreError, "request budget exceeded"):
                make_reader().list_recent_journal_artifacts(CREATED)

            reader = make_reader()
            rows = reader.list_recent_journal_artifacts(CREATED, domains={"heartbeat"})

        self.assertEqual(
            [row["id"] for row in rows],
            [10, 2001, 2000, 9],
        )


if __name__ == "__main__":
    unittest.main()
