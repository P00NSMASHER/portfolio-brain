"""Regression coverage for GitHub workflow rerun attempts in the canonical journal."""
import hashlib
import io
import json
import unittest
import zipfile
from pathlib import Path

from agents.heartbeat_state import heartbeat, seed_state
from state_journal.contracts import EVENT_SCHEMA_ATTEMPT, REPOSITORY, digest, validate_source_evidence
from state_journal.events import make_change, make_event, validate_event
from state_journal.reducer import checkpoint, replay
from state_journal.transport import EVENT_PREFIX, EMIT_STEP, REPO_ID, UPLOAD_STEP, validate_provider_event

ROOT = Path(__file__).resolve().parents[1]
UPLOADS = json.loads((ROOT / "state_journal/UPLOAD_STEPS.json").read_text())
SHA = "a" * 40


def tick(state, run_id, at):
    return heartbeat(
        state,
        agent_ids=["AGT-DATA-STEWARD"],
        activity_kind="RUNTIME_OBSERVATION",
        source_workflow="runtime-worker",
        source_run_id=run_id,
        at=at,
    )


class RunAttemptJournalTests(unittest.TestCase):
    def test_two_attempts_of_same_github_run_are_distinct_and_replay_in_order(self):
        base_state = seed_state()
        after_one = tick(base_state, "101", "2026-09-30T08:00:00Z")
        after_two = tick(after_one, "101", "2026-09-30T08:01:00Z")
        first = make_event(
            "runtime-worker", "101", SHA,
            [make_change("heartbeat", base_state, after_one)],
            run_attempt=1,
        )
        second = make_event(
            "runtime-worker", "101", SHA,
            [make_change("heartbeat", after_one, after_two)],
            run_attempt=2,
        )
        self.assertEqual(first["schema_version"], EVENT_SCHEMA_ATTEMPT)
        self.assertNotEqual(first["event_id"], second["event_id"])
        base = checkpoint({"heartbeat": base_state}, {"heartbeat": "fixture:heartbeat"})
        self.assertEqual(replay(base, [second, first])["states"]["heartbeat"], after_two)

    def test_legacy_attempt_two_artifact_is_normalized_without_mutating_archive_identity(self):
        before = seed_state()
        after = tick(before, "101", "2026-09-30T08:01:00Z")
        legacy = make_event("runtime-worker", "101", SHA, [make_change("heartbeat", before, after)])
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("event.json", json.dumps(legacy))
        raw = stream.getvalue()
        meta = {
            "id": 12,
            "name": f"{EVENT_PREFIX}101-runtime-worker-{SHA}-2",
            "expired": False,
            "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "workflow_run": {
                "id": 101, "head_sha": SHA, "head_branch": "main",
                "repository_id": REPO_ID, "head_repository_id": REPO_ID,
            },
        }
        run = {
            "id": 101, "run_attempt": 2, "head_sha": SHA, "head_branch": "main",
            "event": "workflow_dispatch",
            "repository": {"full_name": REPOSITORY, "id": REPO_ID},
            "head_repository": {"full_name": REPOSITORY, "id": REPO_ID},
            "status": "completed", "conclusion": "success",
            "path": ".github/workflows/runtime-hourly-sync.yml", "workflow_id": 45,
        }
        job = {
            "id": 20, "run_id": 101, "run_attempt": 2,
            "steps": [
                {"name": name, "status": "completed", "conclusion": "success"}
                for name in [EMIT_STEP, UPLOAD_STEP, UPLOADS["runtime-worker"]["heartbeat"]]
            ],
        }
        normalized, evidence = validate_provider_event(meta, run, {"total_count": 1, "jobs": [job]}, raw, UPLOADS)
        self.assertEqual(normalized["schema_version"], EVENT_SCHEMA_ATTEMPT)
        self.assertEqual(normalized["run_attempt"], 2)
        self.assertNotEqual(normalized["event_id"], legacy["event_id"])
        self.assertEqual(evidence["archive_digest"], meta["digest"])
        self.assertEqual(evidence["source_run_attempt"], 2)
        validate_event(normalized)
        validate_source_evidence(evidence, normalized)

    def test_attempt_aware_evidence_cannot_claim_another_attempt(self):
        before = seed_state()
        after = tick(before, "101", "2026-09-30T08:00:00Z")
        event = make_event(
            "runtime-worker", "101", SHA,
            [make_change("heartbeat", before, after)],
            run_attempt=2,
        )
        source = {
            "kind": "GITHUB_ACTIONS",
            "repository": REPOSITORY,
            "artifact_id": 12,
            "archive_digest": "sha256:" + "0" * 64,
            "source_run_id": 101,
            "source_run_attempt": 1,
            "source_sha": SHA,
            "workflow_id": 45,
            "workflow_path": ".github/workflows/runtime-hourly-sync.yml",
            "source_conclusion": "success",
            "event_hash": event["event_hash"],
            "job_id": 20,
        }
        with self.assertRaisesRegex(ValueError, "attempt mismatch"):
            validate_source_evidence(source, event)


if __name__ == "__main__":
    unittest.main()
