import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.github_reducer import restore_snapshot
from state_journal.transport import GitHubReader, SNAPSHOT_ARTIFACT


REPOSITORY = "P00NSMASHER/portfolio-brain"
CREATED = "2026-09-29T16:35:30Z"


def workflow_run(run_id, created_at, *, sha="a" * 40):
    return {
        "id": run_id,
        "path": ".github/workflows/portfolio-state-reducer.yml",
        "created_at": created_at,
        "updated_at": created_at,
        "head_branch": "main",
        "head_sha": sha,
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
    }


def artifact(artifact_id, name, created_at, run_id, *, sha="a" * 40):
    return {
        "id": artifact_id,
        "name": name,
        "created_at": created_at,
        "expired": False,
        "workflow_run": {
            "id": run_id,
            "head_branch": "main",
            "head_sha": sha,
        },
    }


class SnapshotRequestBudgetRegressionTests(unittest.TestCase):
    def test_snapshot_restore_uses_exact_name_index_within_request_budget(self):
        producers = {
            f"producer-{index:02d}": "runtime-worker"
            for index in range(47)
        }
        runs = {
            201: workflow_run(201, "2026-09-29T21:00:00Z"),
            202: workflow_run(202, "2026-09-29T22:00:00Z"),
        }
        snapshot_rows = {
            201: artifact(9, SNAPSHOT_ARTIFACT, "2026-09-29T21:01:00Z", 201),
            202: artifact(10, SNAPSHOT_ARTIFACT, "2026-09-29T22:01:00Z", 202),
        }
        producer_runs = {}
        event_artifacts = {}
        for index, workflow in enumerate(producers):
            run_id = 1000 + index
            producer_runs[workflow] = workflow_run(
                run_id, "2026-09-29T21:30:00Z", sha="b" * 40
            )
            event_artifacts[run_id] = artifact(
                2000 + index,
                f"portfolio-state-event-v2-{run_id}-runtime-worker-{'b' * 40}-1",
                "2026-09-29T21:31:00Z",
                run_id,
                sha="b" * 40,
            )

        candidate_ids = {1000, 1001}
        durable_rows = [
            artifact(
                3000 + index,
                "portfolio-runtime-state",
                "2026-09-29T21:30:30Z",
                run_id,
                sha="b" * 40,
            )
            for index, run_id in enumerate(sorted(candidate_ids))
        ]

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
                return {"workflow_runs": [runs[202], runs[201]]}
            if suffix.startswith("/actions/workflows/"):
                workflow = suffix.split("/actions/workflows/", 1)[1].split(".yml/runs?", 1)[0]
                return {"workflow_runs": [producer_runs[workflow]]}
            if suffix == "/actions/runs/202/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshot_rows[202]]}
            if suffix == "/actions/runs/201/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshot_rows[201]]}
            if suffix.startswith("/actions/artifacts?name="):
                query = parse_qs(urlparse("https://example.invalid" + suffix).query)
                name = query["name"][0]
                rows = durable_rows if name == "portfolio-runtime-state" else []
                return {"total_count": len(rows), "artifacts": rows}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/")[3])
                rows = [event_artifacts[run_id]] if run_id in candidate_ids else []
                return {"total_count": len(rows), "artifacts": rows}
            raise AssertionError(f"Unexpected API request: {suffix}")

        def archive(artifact_id):
            count_request()
            return str(artifact_id).encode()

        reader.get = get
        reader.archive = archive
        states = {b"10": {"sequence": 2}, b"9": {"sequence": 1}}
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", producers), \
             patch("state_journal.github_reducer.artifact_digest"), \
             patch(
                 "state_journal.github_reducer.extract_json",
                 side_effect=lambda raw, _member: states[raw],
             ), \
             patch("state_journal.github_reducer.validate_snapshot"):
            artifacts = reader.list_recent_journal_artifacts(CREATED)
            restored = restore_snapshot(reader, artifacts, current_run="999")

        self.assertEqual(restored, {"sequence": 2})
        # 1 reducer listing + 2 reducer artifact listings + 47 producer
        # listings + 3 exact durable-name listings + 2 exact candidate-run
        # artifact listings + 2 snapshot downloads.
        self.assertEqual(request_count, 57)


if __name__ == "__main__":
    unittest.main()
