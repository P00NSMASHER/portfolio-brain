"""Keep event verification within the API budget by reusing discovered run data."""
import unittest
from unittest.mock import patch

from runtime.artifact_state import ArtifactRestoreError
from state_journal.transport import (
    EMIT_STEP,
    EVENT_PREFIX,
    UPLOAD_STEP,
    GitHubReader,
)


SHA = "a" * 40
WORKFLOW = "runtime-hourly-sync"
CREATED = "2026-10-01T03:18:34Z"
EVENT = {"producer": "runtime-worker", "changes": [{"domain": "heartbeat"}]}
UPLOAD_STEPS = {"runtime-worker": {"heartbeat": "Upload heartbeat"}}


def producer_run(attempt):
    return {
        "id": 301,
        "run_attempt": attempt,
        "created_at": "2026-10-01T04:00:00Z",
        "updated_at": "2026-10-01T04:01:00Z",
        "head_branch": "main",
        "head_sha": SHA,
        "status": "completed",
        "conclusion": "success",
        "event": "workflow_dispatch",
        "path": f".github/workflows/{WORKFLOW}.yml",
        "workflow_id": 45,
        "repository": {"full_name": "P00NSMASHER/portfolio-brain"},
        "head_repository": {"full_name": "P00NSMASHER/portfolio-brain"},
    }


def event_artifact(attempt):
    return {
        "id": 401,
        "name": f"{EVENT_PREFIX}301-runtime-worker-{SHA}-{attempt}",
        "created_at": "2026-10-01T04:01:00Z",
        "expired": False,
        "digest": "sha256:" + "b" * 64,
        "workflow_run": {
            "id": 301,
            "head_branch": "main",
            "head_sha": SHA,
        },
    }


class DiscoveredRunBudgetRegressionTests(unittest.TestCase):
    def make_reader(self, *, listed_attempt, artifact_attempt):
        reader = object.__new__(GitHubReader)
        calls = []
        exact_attempt = producer_run(artifact_attempt)

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": []}
            if suffix.startswith(f"/actions/workflows/{WORKFLOW}.yml/runs?"):
                return {"workflow_runs": [producer_run(listed_attempt)]}
            if suffix == "/actions/runs/301/artifacts?per_page=100":
                return {"total_count": 1, "artifacts": [event_artifact(artifact_attempt)]}
            if suffix == f"/actions/runs/301/attempts/{artifact_attempt}":
                return exact_attempt
            if suffix == f"/actions/runs/301/attempts/{artifact_attempt}/jobs?per_page=100":
                steps = [
                    {"name": name, "status": "completed", "conclusion": "success"}
                    for name in (EMIT_STEP, UPLOAD_STEP, "Upload heartbeat")
                ]
                return {
                    "total_count": 1,
                    "jobs": [{"id": 501, "run_id": 301, "run_attempt": artifact_attempt, "steps": steps}],
                }
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = get
        reader.archive = lambda _artifact_id: b"event archive"
        return reader, calls

    def test_current_attempt_reuses_run_metadata_from_workflow_discovery(self):
        reader, calls = self.make_reader(listed_attempt=2, artifact_attempt=2)

        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {WORKFLOW: "runtime-worker"}), \
             patch("state_journal.transport.extract_json", return_value=EVENT), \
             patch("state_journal.transport.validate_event"), \
             patch("state_journal.transport.validate_provider_event", return_value=(EVENT, {})):
            artifacts = reader.list_recent_journal_artifacts(CREATED)
            reader.event(artifacts[0], UPLOAD_STEPS)

        self.assertEqual(
            sum("/attempts/2" in call and call.endswith("/jobs?per_page=100") for call in calls),
            1,
        )
        self.assertFalse(any(call == "/actions/runs/301/attempts/2" for call in calls))

    def test_prior_attempt_still_fetches_exact_attempt_metadata(self):
        reader, calls = self.make_reader(listed_attempt=2, artifact_attempt=1)

        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {WORKFLOW: "runtime-worker"}), \
             patch("state_journal.transport.extract_json", return_value=EVENT), \
             patch("state_journal.transport.validate_event"), \
             patch("state_journal.transport.validate_provider_event", return_value=(EVENT, {})):
            artifacts = reader.list_recent_journal_artifacts(CREATED)
            reader.event(artifacts[0], UPLOAD_STEPS)

        self.assertIn("/actions/runs/301/attempts/1", calls)
        self.assertIn("/actions/runs/301/attempts/1/jobs?per_page=100", calls)

    def test_discovered_attempt_reuse_keeps_event_replay_inside_api_budget(self):
        workflows = {
            f"producer-{index:02d}": "runtime-worker"
            for index in range(14)
        }
        runs_by_workflow = {workflow: [] for workflow in workflows}
        runs_by_id = {}
        artifacts_by_run = {}
        for index in range(22):
            run_id = 1000 + index
            workflow = sorted(workflows)[index % len(workflows)]
            run = producer_run(1)
            run.update({
                "id": run_id,
                "path": f".github/workflows/{workflow}.yml",
            })
            runs_by_workflow[workflow].append(run)
            runs_by_id[run_id] = run
            artifacts_by_run[run_id] = event_artifact(1)
            artifacts_by_run[run_id].update({
                "id": 2000 + index,
                "name": f"{EVENT_PREFIX}{run_id}-runtime-worker-{SHA}-1",
                "workflow_run": {
                    "id": run_id,
                    "head_branch": "main",
                    "head_sha": SHA,
                },
            })

        reader = object.__new__(GitHubReader)
        requests = 0

        def count_request():
            nonlocal requests
            requests += 1
            if requests > 100:
                raise ArtifactRestoreError("artifact API request budget exceeded")

        def get(suffix):
            count_request()
            if suffix.startswith("/actions/workflows/"):
                workflow_file = suffix.split("/actions/workflows/", 1)[1].split(".yml/runs?", 1)[0]
                if workflow_file == "portfolio-state-reducer":
                    return {"workflow_runs": []}
                return {"workflow_runs": runs_by_workflow[workflow_file]}
            if suffix.endswith("/artifacts?per_page=100"):
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                return {"total_count": 1, "artifacts": [artifacts_by_run[run_id]]}
            if suffix.endswith("/jobs?per_page=100"):
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                steps = [
                    {"name": name, "status": "completed", "conclusion": "success"}
                    for name in (EMIT_STEP, UPLOAD_STEP, "Upload heartbeat")
                ]
                return {
                    "total_count": 1,
                    "jobs": [{"id": run_id + 5000, "run_id": run_id, "run_attempt": 1, "steps": steps}],
                }
            if "/attempts/" in suffix:
                run_id = int(suffix.split("/actions/runs/", 1)[1].split("/", 1)[0])
                return runs_by_id[run_id]
            raise AssertionError(f"Unexpected API request: {suffix}")

        reader.get = get

        def archive(_artifact_id):
            count_request()
            return b"event archive"

        reader.archive = archive
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", workflows), \
             patch("state_journal.transport.extract_json", return_value=EVENT), \
             patch("state_journal.transport.validate_event"), \
             patch("state_journal.transport.validate_provider_event", return_value=(EVENT, {})):
            artifacts = reader.list_recent_journal_artifacts(CREATED)
            for artifact in artifacts:
                reader.event(artifact, UPLOAD_STEPS)

        self.assertEqual(requests, 81)


if __name__ == "__main__":
    unittest.main()
