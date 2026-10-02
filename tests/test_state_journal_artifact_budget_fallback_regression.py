"""Regression coverage for journal discovery under producer-run request pressure."""
import unittest
from unittest.mock import patch

from state_journal.transport import EVENT_PREFIX, SNAPSHOT_ARTIFACT, GitHubReader


CREATED = "2026-10-01T04:00:00Z"


def run(run_id, workflow, *, created_at=CREATED):
    return {
        "id": run_id,
        "path": f".github/workflows/{workflow}.yml",
        "created_at": created_at,
        "updated_at": created_at,
        "head_branch": "main",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": "success",
    }


def artifact(artifact_id, name, run_id, *, created_at=CREATED):
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


class JournalArtifactBudgetFallbackTests(unittest.TestCase):
    def test_uses_bounded_artifact_listing_when_per_run_lookups_exceed_budget(self):
        producers = {f"producer-{index:02d}": f"producer-{index:02d}" for index in range(60)}
        reducer = run(10, "portfolio-state-reducer")
        snapshot = artifact(11, SNAPSHOT_ARTIFACT, 10)
        producer_runs = {
            100 + index: run(100 + index, workflow)
            for index, workflow in enumerate(producers)
        }
        event_artifacts = [
            artifact(
                1000 + index,
                f"{EVENT_PREFIX}{100 + index}-test-{'b' * 40}-1",
                100 + index,
            )
            for index in range(len(producers))
        ]
        unrelated = artifact(2000, "unrelated-artifact", 9999)
        reader = GitHubReader("token", max_requests=100)
        calls = []

        def get(suffix):
            reader.http.requests += 1
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": [reducer]}
            if suffix.startswith("/actions/workflows/"):
                workflow = suffix.split("/actions/workflows/", 1)[1].split(".yml/runs?", 1)[0]
                run_id = next(run_id for run_id, row in producer_runs.items()
                              if row["path"].endswith(f"/{workflow}.yml"))
                return {"workflow_runs": [producer_runs[run_id]]}
            if suffix == "/actions/runs/10/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [snapshot]}
            if suffix == "/actions/artifacts?per_page=100&page=1":
                return {"total_count": len(event_artifacts) + 2,
                        "artifacts": [*event_artifacts, snapshot, unrelated]}
            if suffix.startswith("/actions/runs/") and suffix.endswith("/artifacts?per_page=100"):
                raise AssertionError("budget fallback should avoid producer per-run lookups")
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", producers):
            rows = reader.list_recent_journal_artifacts(CREATED)

        self.assertEqual(
            [row["id"] for row in rows],
            [*(1000 + index for index in reversed(range(60))), snapshot["id"]],
        )
        self.assertEqual(reader.http.requests, 63)
        self.assertEqual(sum("/actions/artifacts?" in call for call in calls), 1)
        self.assertFalse(any(call.startswith("/actions/runs/100/") for call in calls))


if __name__ == "__main__":
    unittest.main()
