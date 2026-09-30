"""Source workflow authorization must include each directly enrolled producer."""
import unittest

from agents.heartbeat_state import heartbeat, seed_state
from state_journal.contracts import JournalError, REPOSITORY, validate_source_evidence
from state_journal.events import make_change, make_event
from state_journal.reducer import checkpoint, make_snapshot, validate_snapshot


class WorkflowProducerAuthorizationTests(unittest.TestCase):
    def test_runtime_worker_workflow_can_authorize_its_event(self):
        before = seed_state()
        run_id = "101"
        after = heartbeat(
            before,
            agent_ids=["AGT-DATA-STEWARD"],
            activity_kind="RUNTIME_OBSERVATION",
            source_workflow="runtime-worker",
            source_run_id=run_id,
            at="2026-09-30T20:00:00Z",
        )
        event = make_event(
            "runtime-worker",
            run_id,
            "a" * 40,
            [make_change("heartbeat", before, after)],
            run_attempt=1,
        )
        evidence = {
            "kind": "GITHUB_ACTIONS",
            "repository": REPOSITORY,
            "artifact_id": 12,
            "archive_digest": "sha256:" + "b" * 64,
            "source_run_id": 101,
            "source_run_attempt": 1,
            "source_sha": "a" * 40,
            "workflow_id": 45,
            "workflow_path": ".github/workflows/runtime-worker.yml",
            "source_conclusion": "success",
            "event_hash": event["event_hash"],
            "job_id": 20,
        }

        base = checkpoint({"heartbeat": before}, {"heartbeat": "fixture:heartbeat"})
        snapshot = make_snapshot(
            base,
            [event],
            sequence=1,
            evidence={event["event_id"]: [evidence]},
        )
        validate_snapshot(snapshot)

    def test_factory_workflow_remains_excluded_as_a_reusable_workflow(self):
        before = seed_state()
        after = heartbeat(
            before,
            agent_ids=["AGT-DATA-STEWARD"],
            activity_kind="FACTORY_CYCLE",
            source_workflow="software-factory-candidate",
            source_run_id="101",
            at="2026-09-30T20:00:00Z",
        )
        event = make_event(
            "software-factory-candidate",
            "101",
            "a" * 40,
            [make_change("heartbeat", before, after)],
            run_attempt=1,
        )
        evidence = {
            "kind": "GITHUB_ACTIONS",
            "repository": REPOSITORY,
            "artifact_id": 12,
            "archive_digest": "sha256:" + "b" * 64,
            "source_run_id": 101,
            "source_run_attempt": 1,
            "source_sha": "a" * 40,
            "workflow_id": 45,
            "workflow_path": ".github/workflows/software-factory-candidate.yml",
            "source_conclusion": "success",
            "event_hash": event["event_hash"],
            "job_id": 20,
        }

        with self.assertRaisesRegex(JournalError, "Evidence producer authorization mismatch"):
            validate_source_evidence(evidence, event)


if __name__ == "__main__":
    unittest.main()
