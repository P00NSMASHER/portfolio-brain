import unittest
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.github_reducer import restore_snapshot
from state_journal.transport import GitHubReader, SNAPSHOT_ARTIFACT


class RequestLimitedHTTP:
    def __init__(self, _token, *, max_requests, **_kwargs):
        self.max_requests = max_requests
        self.requests = 0

    def _count(self):
        if self.requests >= self.max_requests:
            raise ArtifactRestoreError("artifact API request budget exceeded")
        self.requests += 1

    def json(self, url):
        self._count()
        suffix = url.split("/repos/P00NSMASHER/portfolio-brain", 1)[1]
        if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
            return {"workflow_runs": [reducer_run(202, "2026-10-02T10:00:00Z"),
                                      reducer_run(201, "2026-10-02T09:00:00Z")]}
        if suffix.endswith("/actions/runs/202/artifacts?per_page=100"):
            return {"total_count": 1, "artifacts": [snapshot_artifact(22, 202, "2026-10-02T10:00:00Z")]}
        if suffix.endswith("/actions/runs/201/artifacts?per_page=100"):
            return {"total_count": 1, "artifacts": [snapshot_artifact(21, 201, "2026-10-02T09:00:00Z")]}
        if suffix == "/actions/runs/202":
            return reducer_run(202, "2026-10-02T10:00:00Z")
        if suffix == "/actions/runs/201":
            return reducer_run(201, "2026-10-02T09:00:00Z")
        raise AssertionError(f"Unexpected API request: {suffix}")

    def bytes(self, url):
        self._count()
        return b"new" if url.endswith("/22/zip") else b"old"


def reducer_run(run_id, created_at):
    return {
        "id": run_id,
        "path": ".github/workflows/portfolio-state-reducer.yml",
        "head_branch": "main",
        "head_sha": f"{run_id:040d}",
        "status": "completed",
        "conclusion": "success",
        "created_at": created_at,
        "updated_at": created_at,
        "repository": {"full_name": "P00NSMASHER/portfolio-brain"},
        "head_repository": {"full_name": "P00NSMASHER/portfolio-brain"},
    }


def snapshot_artifact(artifact_id, run_id, created_at):
    return {
        "id": artifact_id,
        "name": SNAPSHOT_ARTIFACT,
        "expired": False,
        "created_at": created_at,
        "workflow_run": {
            "id": run_id,
            "head_branch": "main",
            "head_sha": f"{run_id:040d}",
        },
    }


class SnapshotRequestBudgetRegressionTests(unittest.TestCase):
    def test_discovery_run_metadata_is_reused_within_bounded_restore_budget(self):
        newer = {"sequence": 2, "state_hash": "new"}
        older = {"sequence": 1, "state_hash": "old"}
        documents = {b"new": newer, b"old": older}

        with patch("state_journal.transport.BudgetedHTTP", RequestLimitedHTTP):
            reader = GitHubReader("token", max_requests=6)
            with patch("state_journal.transport.WORKFLOW_PRODUCERS", {}), \
                 patch("state_journal.github_reducer.artifact_digest"), \
                 patch("state_journal.github_reducer.extract_json",
                       side_effect=lambda raw, _member: documents[raw]), \
                 patch("state_journal.github_reducer.validate_snapshot"):
                artifacts = reader.list_recent_journal_artifacts(
                    "2026-10-01T00:00:00Z", max_pages=1
                )
                restored = restore_snapshot(reader, artifacts, current_run="999")

        self.assertEqual(restored, newer)
        self.assertEqual(reader.http.requests, 5)


if __name__ == "__main__":
    unittest.main()
