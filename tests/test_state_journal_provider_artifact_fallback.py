import hashlib
import io
import json
import unittest
import zipfile
from pathlib import Path

from agents.heartbeat_state import heartbeat, seed_state
from state_journal.contracts import REPOSITORY, validate_source_evidence
from state_journal.events import make_change, make_event
from state_journal.transport import (
    EVENT_PREFIX, EMIT_STEP, REPO_ID, JournalError, validate_provider_event,
)

ROOT = Path(__file__).resolve().parents[1]
UPLOAD_STEPS = json.loads((ROOT / "state_journal/UPLOAD_STEPS.json").read_text())
UPLOAD_ARTIFACTS = json.loads((ROOT / "state_journal/UPLOAD_ARTIFACTS.json").read_text())
SHA = "a" * 40


def zipped(member, document):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as zf:
        zf.writestr(member, json.dumps(document, sort_keys=True))
    return stream.getvalue()


def fixture():
    before = seed_state()
    after = heartbeat(
        before,
        agent_ids=["AGT-DATA-STEWARD"],
        activity_kind="RUNTIME_OBSERVATION",
        source_workflow="runtime-worker",
        source_run_id="101",
        at="2026-09-30T12:00:00Z",
    )
    event = make_event("runtime-worker", "101", SHA, [make_change("heartbeat", before, after)])
    event_raw = zipped("event.json", event)
    event_meta = {
        "id": 12,
        "name": f"{EVENT_PREFIX}101-runtime-worker-{SHA}-1",
        "expired": False,
        "created_at": "2026-09-30T12:00:02Z",
        "digest": "sha256:" + hashlib.sha256(event_raw).hexdigest(),
        "workflow_run": {
            "id": 101, "head_sha": SHA, "head_branch": "main",
            "repository_id": REPO_ID, "head_repository_id": REPO_ID,
        },
    }
    state_raw = zipped("agent_heartbeat_state.json", after)
    state_meta = {
        "id": 13,
        "name": "portfolio-agent-heartbeat-state",
        "expired": False,
        "created_at": "2026-09-30T12:00:01Z",
        "digest": "sha256:" + hashlib.sha256(state_raw).hexdigest(),
        "workflow_run": {
            "id": 101, "head_sha": SHA, "head_branch": "main",
            "repository_id": REPO_ID, "head_repository_id": REPO_ID,
        },
    }
    run = {
        "id": 101, "run_attempt": 1, "head_sha": SHA, "head_branch": "main",
        "event": "workflow_dispatch",
        "repository": {"full_name": REPOSITORY, "id": REPO_ID},
        "head_repository": {"full_name": REPOSITORY, "id": REPO_ID},
        "status": "completed", "conclusion": "success",
        "path": ".github/workflows/runtime-hourly-sync.yml", "workflow_id": 45,
    }
    job = {
        "id": 20, "run_id": 101, "run_attempt": 1,
        "status": "completed", "conclusion": "success", "steps": [],
    }
    return event_meta, run, {"total_count": 1, "jobs": [job]}, event_raw, event, state_meta, state_raw


class ProviderArtifactFallbackTests(unittest.TestCase):
    def admit(self, mutate=None):
        meta, run, jobs, event_raw, event, state_meta, state_raw = fixture()
        if mutate:
            mutate(meta, run, jobs, event, state_meta, state_raw)
        actual, evidence = validate_provider_event(
            meta, run, jobs, event_raw, UPLOAD_STEPS,
            run_artifacts=[state_meta],
            artifact_bytes={state_meta["id"]: state_raw},
            artifact_names=UPLOAD_ARTIFACTS,
        )
        return actual, evidence, event

    def test_success_with_completely_missing_step_metadata_uses_exact_state_artifact(self):
        actual, evidence, event = self.admit()
        self.assertEqual(actual, event)
        self.assertEqual(evidence["job_id"], 20)
        self.assertEqual(evidence["source_conclusion"], "success")
        validate_source_evidence(evidence, event)

    def test_failed_run_cannot_use_artifact_fallback(self):
        with self.assertRaisesRegex(JournalError, "successful source run"):
            self.admit(lambda _m, r, _j, _e, _sm, _sr: r.update(conclusion="failure"))

    def test_partial_step_metadata_cannot_use_artifact_fallback(self):
        def mutate(_m, _r, jobs, _e, _sm, _sr):
            jobs["jobs"][0]["steps"] = [{"name": "Setup", "status": "completed", "conclusion": "success"}]
        with self.assertRaisesRegex(JournalError, "Source emitter job missing"):
            self.admit(mutate)

    def test_missing_state_artifact_fails_closed(self):
        meta, run, jobs, event_raw, _event, _state_meta, _state_raw = fixture()
        with self.assertRaisesRegex(JournalError, "missing or ambiguous"):
            validate_provider_event(
                meta, run, jobs, event_raw, UPLOAD_STEPS,
                run_artifacts=[], artifact_bytes={}, artifact_names=UPLOAD_ARTIFACTS,
            )

    def test_duplicate_state_artifact_fails_closed(self):
        meta, run, jobs, event_raw, _event, state_meta, state_raw = fixture()
        duplicate = dict(state_meta)
        duplicate["id"] = 14
        with self.assertRaisesRegex(JournalError, "missing or ambiguous"):
            validate_provider_event(
                meta, run, jobs, event_raw, UPLOAD_STEPS,
                run_artifacts=[state_meta, duplicate],
                artifact_bytes={13: state_raw, 14: state_raw},
                artifact_names=UPLOAD_ARTIFACTS,
            )

    def test_state_artifact_payload_must_equal_event_after_state(self):
        meta, run, jobs, event_raw, _event, state_meta, _state_raw = fixture()
        wrong = seed_state()
        wrong_raw = zipped("agent_heartbeat_state.json", wrong)
        state_meta = dict(state_meta)
        state_meta["digest"] = "sha256:" + hashlib.sha256(wrong_raw).hexdigest()
        with self.assertRaisesRegex(JournalError, "hash does not match"):
            validate_provider_event(
                meta, run, jobs, event_raw, UPLOAD_STEPS,
                run_artifacts=[state_meta],
                artifact_bytes={13: wrong_raw},
                artifact_names=UPLOAD_ARTIFACTS,
            )

    def test_state_artifact_must_precede_event_publication(self):
        def mutate(_m, _r, _j, _e, sm, _sr):
            sm["created_at"] = "2026-09-30T12:00:03Z"
        with self.assertRaisesRegex(JournalError, "published after event"):
            self.admit(mutate)

    def test_state_artifact_must_be_exact_run_bound(self):
        def mutate(_m, _r, _j, _e, sm, _sr):
            sm["workflow_run"]["id"] = 999
        with self.assertRaisesRegex(JournalError, "source mismatch"):
            self.admit(mutate)

    def test_normal_step_evidence_remains_primary(self):
        meta, run, jobs, event_raw, event, _state_meta, _state_raw = fixture()
        jobs["jobs"][0]["steps"] = [
            {"name": name, "status": "completed", "conclusion": "success"}
            for name in [
                EMIT_STEP,
                "Upload immutable state transition event",
                UPLOAD_STEPS["runtime-worker"]["heartbeat"],
            ]
        ]
        actual, evidence = validate_provider_event(meta, run, jobs, event_raw, UPLOAD_STEPS)
        self.assertEqual(actual, event)
        self.assertEqual(evidence["job_id"], 20)


if __name__ == "__main__":
    unittest.main()
