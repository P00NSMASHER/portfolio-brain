import base64
import copy
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from agents.heartbeat_state import heartbeat, seed_state
from state_journal.archive_checkpoint import (
    build_archive,
    load_durable_archive,
    validate_manifest,
    verify_archive,
)
from state_journal.contracts import JournalError, digest
from state_journal.events import make_change, make_event
from state_journal.github_reducer import _assert_archive_lineage, reduce_from_provider
from state_journal.reducer import checkpoint, make_snapshot, set_authority
from state_journal.transport import EVENT_PREFIX, UPLOAD_STEP, GitHubReader


SHA = "a" * 40


def canonical_state(sequence=5, *, source_ref="fixture:heartbeat", events=None, evidence=None):
    base = checkpoint({"heartbeat": seed_state()}, {"heartbeat": source_ref})
    state = make_snapshot(base, events or [], sequence=sequence, evidence=evidence or {})
    return set_authority(state, mode="CANONICAL", production_authority=True)


def fixture_event(run_id="301"):
    before = seed_state()
    after = heartbeat(
        before,
        agent_ids=["AGT-DATA-STEWARD"],
        activity_kind="RUNTIME_OBSERVATION",
        source_workflow="runtime-worker",
        source_run_id=run_id,
        at="2026-09-30T12:05:00Z",
    )
    return make_event("runtime-worker", run_id, SHA, [make_change("heartbeat", before, after)])


def fixture_evidence(event):
    return {"kind": "FIXTURE", "event_hash": event["event_hash"], "fixture_id": "fixture:step7"}


def archive(state, *, previous=None, run_id=900, artifact_id=901, created="2026-09-30T12:00:00Z"):
    return build_archive(
        state,
        source_reducer_run_id=run_id,
        source_head_sha="b" * 40,
        source_artifact_id=artifact_id,
        source_artifact_digest="sha256:" + "c" * 64,
        source_artifact_created_at=created,
        source_artifact_expires_at="2026-10-30T12:00:00Z",
        archived_at="2026-09-30T12:01:00Z",
        previous=previous,
    )


def run(run_id, created_at="2026-09-30T12:05:00Z"):
    return {
        "id": run_id,
        "created_at": created_at,
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
    }


class Step7CheckpointLifecycleTests(unittest.TestCase):
    def test_old_expired_or_deleted_event_is_routine_when_checkpoint_covers_run(self):
        reader = object.__new__(GitHubReader)
        calls = []

        def get(suffix):
            calls.append(suffix)
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": []}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": [run(301)]}
            if suffix == "/actions/runs/301/artifacts?per_page=100":
                return {"total_count": 0, "artifacts": []}
            raise AssertionError("unexpected request " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {"runtime-hourly-sync": "runtime-worker"}):
            rows = reader.list_recent_journal_artifacts(
                "2026-09-30T11:30:00Z", covered_run_ids={301}
            )
        self.assertEqual(rows, [])
        self.assertFalse(any("/actions/runs/301/jobs" in call for call in calls))

    def test_missing_required_replay_fails_closed(self):
        reader = object.__new__(GitHubReader)

        def get(suffix):
            if suffix.startswith("/actions/workflows/portfolio-state-reducer.yml/runs?"):
                return {"workflow_runs": []}
            if suffix.startswith("/actions/workflows/runtime-hourly-sync.yml/runs?"):
                return {"workflow_runs": [run(302)]}
            if suffix == "/actions/runs/302/artifacts?per_page=100":
                return {"total_count": 0, "artifacts": []}
            if suffix == "/actions/runs/302/jobs?per_page=100":
                return {
                    "total_count": 1,
                    "jobs": [{"steps": [{"name": UPLOAD_STEP, "status": "completed", "conclusion": "success"}]}],
                }
            raise AssertionError("unexpected request " + suffix)

        reader.get = get
        with patch("state_journal.transport.WORKFLOW_PRODUCERS", {"runtime-hourly-sync": "runtime-worker"}), \
             self.assertRaisesRegex(JournalError, "MISSING_REPLAY"):
            reader.list_recent_journal_artifacts("2026-09-30T11:30:00Z")

    def test_event_after_checkpoint_replays_and_advances_canonical_sequence(self):
        archived = canonical_state(sequence=5)
        event = fixture_event()
        meta = {
            "id": 77,
            "name": EVENT_PREFIX + "301-runtime-worker-" + SHA + "-1",
            "expired": False,
            "created_at": "2026-09-30T12:05:01Z",
            "digest": "sha256:" + "d" * 64,
            "workflow_run": {"id": 301, "head_branch": "main", "head_sha": SHA},
        }

        class Reader:
            def list_recent_journal_artifacts(self, *_args, **_kwargs):
                return [meta]
            def event(self, _meta, _upload_steps):
                return event, fixture_evidence(event)

        state, receipt = reduce_from_provider(
            Reader(),
            since="2026-09-30T11:30:00Z",
            current_run="999",
            upload_steps={},
            archived_state=archived,
            archive_manifest={
                "canonical_sequence": archived["sequence"],
                "canonical_state_hash": archived["state_hash"],
            },
        )
        self.assertEqual(state["sequence"], 6)
        self.assertEqual(state["event_count"], 1)
        self.assertEqual(receipt["new_deliveries"], 1)
        self.assertEqual(state["projection"]["states"]["heartbeat"], event["changes"][0]["after"])

    def test_corrupted_checkpoint_hash_fails_closed(self):
        raw, manifest = archive(canonical_state())
        damaged = bytearray(raw)
        damaged[-1] ^= 1
        with self.assertRaises(Exception):
            verify_archive(bytes(damaged), manifest)

    def test_checkpoint_sequence_regression_fails(self):
        _, first = archive(canonical_state(7))
        with self.assertRaisesRegex(JournalError, "sequence regressed"):
            archive(canonical_state(6), previous=first, run_id=901, artifact_id=902)

    def test_mismatched_predecessor_hash_fails(self):
        _, first = archive(canonical_state(7))
        _, second = archive(canonical_state(8), previous=first, run_id=901, artifact_id=902)
        changed = copy.deepcopy(second)
        changed["previous_manifest_hash"] = "sha256:" + "e" * 64
        body = {k: v for k, v in changed.items() if k not in {"manifest_hash", "archive_id"}}
        changed["manifest_hash"] = digest(body)
        changed["archive_id"] = "PARCH-" + changed["manifest_hash"].split(":", 1)[1][:24].upper()
        with self.assertRaisesRegex(JournalError, "manifest lineage mismatch"):
            validate_manifest(changed, previous=first)

    def test_conflicting_checkpoint_lineage_fails(self):
        archived = canonical_state(7, source_ref="fixture:a")
        live = canonical_state(7, source_ref="fixture:b")
        manifest = {"canonical_sequence": 7, "canonical_state_hash": archived["state_hash"]}
        with self.assertRaisesRegex(JournalError, "CONFLICTING_LINEAGE"):
            _assert_archive_lineage(live, archived, manifest)

    def test_incomplete_replay_fails(self):
        event = fixture_event()
        archived = canonical_state(
            7,
            events=[event],
            evidence={event["event_id"]: [fixture_evidence(event)]},
        )
        live = canonical_state(8)
        manifest = {"canonical_sequence": 7, "canonical_state_hash": archived["state_hash"]}
        with self.assertRaisesRegex(JournalError, "INCOMPLETE_REPLAY"):
            _assert_archive_lineage(live, archived, manifest)

    def test_checkpoint_cannot_silently_change_root_state(self):
        archived = canonical_state(7, source_ref="fixture:a")
        live = canonical_state(8, source_ref="fixture:b")
        manifest = {"canonical_sequence": 7, "canonical_state_hash": archived["state_hash"]}
        with self.assertRaisesRegex(JournalError, "checkpoint root changed"):
            _assert_archive_lineage(live, archived, manifest)

    def test_durable_archive_loader_distinguishes_valid_corrupt_and_expired(self):
        raw, manifest = archive(canonical_state())
        files = {
            "archive/manifest.json": (json.dumps(manifest, sort_keys=True) + "\n").encode(),
            "archive/snapshot.json.gz": raw,
        }

        class Reader:
            def __init__(self, payload):
                self.payload = payload
            def read_archive_branch_files(self, _paths):
                return self.payload, {"branch": "archive/state-journal", "ref_sha": "f" * 40, "tree_sha": "e" * 40}

        state, loaded, status = load_durable_archive(
            Reader(files), now=datetime(2026, 9, 30, 13, tzinfo=timezone.utc)
        )
        self.assertEqual(status["status"], "VALID_CHECKPOINT")
        self.assertEqual(state["state_hash"], loaded["canonical_state_hash"])

        bad = dict(files)
        bad["archive/snapshot.json.gz"] = raw[:-1] + bytes([raw[-1] ^ 1])
        with self.assertRaisesRegex(JournalError, "CORRUPTED_CHECKPOINT"):
            load_durable_archive(Reader(bad), now=datetime(2026, 9, 30, 13, tzinfo=timezone.utc))

        with self.assertRaisesRegex(JournalError, "EXPIRED_EVIDENCE"):
            load_durable_archive(
                Reader(files), now=datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
            )

    def test_archive_branch_read_is_bounded_and_targeted(self):
        reader = object.__new__(GitHubReader)
        calls = []
        manifest_raw = b'{"x":1}\n'
        snapshot_raw = b"gzip-bytes"
        encoded = {
            "1" * 40: base64.b64encode(manifest_raw).decode(),
            "2" * 40: base64.b64encode(snapshot_raw).decode(),
        }

        def get(suffix):
            calls.append(suffix)
            if suffix == "/git/ref/heads/archive/state-journal":
                return {"object": {"sha": "a" * 40}}
            if suffix == "/git/commits/" + "a" * 40:
                return {"tree": {"sha": "b" * 40}}
            if suffix == "/git/trees/" + "b" * 40 + "?recursive=1":
                return {
                    "truncated": False,
                    "tree": [
                        {"path": "archive/manifest.json", "type": "blob", "sha": "1" * 40},
                        {"path": "archive/snapshot.json.gz", "type": "blob", "sha": "2" * 40},
                    ],
                }
            if suffix == "/git/blobs/" + "1" * 40:
                return {"encoding": "base64", "content": encoded["1" * 40], "size": len(manifest_raw)}
            if suffix == "/git/blobs/" + "2" * 40:
                return {"encoding": "base64", "content": encoded["2" * 40], "size": len(snapshot_raw)}
            raise AssertionError("unexpected request " + suffix)

        reader.get = get
        files, meta = reader.read_archive_branch_files(
            ["archive/manifest.json", "archive/snapshot.json.gz"]
        )
        self.assertEqual(files["archive/manifest.json"], manifest_raw)
        self.assertEqual(files["archive/snapshot.json.gz"], snapshot_raw)
        self.assertEqual(meta["ref_sha"], "a" * 40)
        self.assertEqual(len(calls), 5)
        self.assertFalse(any("/actions/artifacts" in call for call in calls))


if __name__ == "__main__":
    unittest.main()
