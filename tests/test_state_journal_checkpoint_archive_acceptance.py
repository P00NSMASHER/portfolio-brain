import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from agents.heartbeat_state import heartbeat, seed_state
from state_journal.archive import build_rollover, load_active_manifest
from state_journal.checkpoint_archive import _proposed_scan_start, _validate_replay_retention
from state_journal.contracts import JournalError, MissingPredecessor, REPOSITORY, canonical, digest
from state_journal.events import make_change, make_event
from state_journal.github_reducer import reduce_from_provider
from state_journal.reducer import checkpoint, make_snapshot, set_authority

SHA = "a" * 40


def tick(before, *, run="101", at="2026-09-30T13:30:00Z"):
    return heartbeat(
        before,
        agent_ids=["AGT-DATA-STEWARD"],
        activity_kind="RUNTIME_OBSERVATION",
        source_workflow="runtime-worker",
        source_run_id=run,
        at=at,
    )


def canonical_state(sequence=5, base=None):
    if base is None:
        base = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
    state = make_snapshot(base, [], sequence=sequence, evidence={})
    return set_authority(state, mode="CANONICAL", production_authority=True)


def provider_evidence(event, *, artifact_id=77, archive_digest=None):
    return {
        "kind": "GITHUB_ACTIONS",
        "repository": REPOSITORY,
        "artifact_id": artifact_id,
        "archive_digest": archive_digest or ("sha256:" + "c" * 64),
        "source_run_id": int(event["run_id"]),
        "source_run_attempt": event.get("run_attempt", 1),
        "source_sha": event["source_sha"],
        "workflow_id": 999,
        "workflow_path": ".github/workflows/runtime-hourly-sync.yml",
        "source_conclusion": "success",
        "event_hash": event["event_hash"],
        "job_id": 1001,
    }


def state_with_event(*, artifact_id=77):
    before = seed_state()
    event = make_event(
        "runtime-worker",
        "123",
        SHA,
        [make_change("heartbeat", before, tick(before, run="123"))],
        run_attempt=1,
    )
    evidence = provider_evidence(event, artifact_id=artifact_id)
    base = checkpoint({"heartbeat": before}, {"heartbeat": "fixture:heartbeat"})
    state = make_snapshot(base, [event], sequence=5, evidence={event["event_id"]: [evidence]})
    return set_authority(state, mode="CANONICAL", production_authority=True), event, evidence


def rollover(state, *, run_id, artifact_id, created_at, previous=None, scan_start=None):
    return build_rollover(
        state,
        source_reducer_run_id=run_id,
        source_artifact_id=artifact_id,
        source_head_sha=SHA,
        source_artifact_digest="sha256:" + format(artifact_id, "064x")[-64:],
        source_artifact_created_at=created_at,
        artifact_scan_start=scan_start,
        previous_manifest_hash=None if previous is None else previous["manifest_hash"],
    )


def persist_rollover(root, result, *, active):
    manifest, archive_raw, _checkpoint_doc, checkpoint_raw, archive_path = result
    (root / "state_journal/archive").mkdir(parents=True, exist_ok=True)
    (root / archive_path).write_bytes(archive_raw)
    (root / manifest["manifest_path"]).write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    )
    if active:
        (root / "state_journal/ARCHIVE_MANIFEST.json").write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":"))
        )
        (root / "state_journal/CHECKPOINT.json.gz").write_bytes(checkpoint_raw)


def rehash_manifest(document):
    result = copy.deepcopy(document)
    result["manifest_hash"] = digest({k: v for k, v in result.items() if k != "manifest_hash"})
    return result


def overwrite_active_manifest(root, manifest):
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    (root / manifest["manifest_path"]).write_text(raw)
    (root / "state_journal/ARCHIVE_MANIFEST.json").write_text(raw)


def gzip_document(document):
    return gzip.compress(canonical(document) + b"\n", compresslevel=9, mtime=0)


class EventReader:
    def __init__(self, artifact, event):
        self.artifact = artifact
        self.event_doc = event

    def list_recent_journal_artifacts(self, *args, **kwargs):
        return [self.artifact]

    def event(self, meta, upload_steps):
        self.assert_meta(meta)
        return self.event_doc, {
            "kind": "FIXTURE",
            "event_hash": self.event_doc["event_hash"],
            "fixture_id": "fixture:checkpoint-replay",
        }

    def assert_meta(self, meta):
        if meta["id"] != self.artifact["id"]:
            raise AssertionError("unexpected artifact")


class RetentionReader:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def list_recent_artifacts(self, since, *, max_pages=20):
        self.calls.append((since, max_pages))
        return list(self.rows)


class CheckpointArchiveAcceptanceTests(unittest.TestCase):
    def first_rollover(self, state=None):
        state = canonical_state() if state is None else state
        return rollover(
            state,
            run_id=900,
            artifact_id=901,
            created_at="2026-09-30T13:00:00Z",
        )

    def second_rollover(self, first, *, state=None):
        first_manifest, _raw, first_checkpoint, _checkpoint_raw, _path = first
        state = canonical_state(sequence=6, base=first_checkpoint) if state is None else state
        return rollover(
            state,
            run_id=902,
            artifact_id=903,
            created_at="2026-09-30T14:00:00Z",
            previous=first_manifest,
            scan_start=first_manifest["source_artifact_created_at"],
        )

    def test_valid_checkpoint_lineage_round_trips(self):
        first = self.first_rollover()
        second = self.second_rollover(first)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            persist_rollover(root, first, active=False)
            persist_rollover(root, second, active=True)
            active = load_active_manifest(root)
            self.assertEqual(active["previous_manifest_hash"], first[0]["manifest_hash"])
            self.assertEqual(active["archived_checkpoint_hash"], first[0]["new_checkpoint_hash"])
            self.assertEqual(active["artifact_scan_start"], first[0]["source_artifact_created_at"])

    def test_corrupted_checkpoint_hash_fails_closed(self):
        first = self.first_rollover()
        manifest, _raw, checkpoint_doc, _checkpoint_raw, _path = first
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            persist_rollover(root, first, active=True)
            corrupted = copy.deepcopy(checkpoint_doc)
            corrupted["checkpoint_hash"] = "sha256:" + "f" * 64
            (root / "state_journal/CHECKPOINT.json.gz").write_bytes(gzip_document(corrupted))
            with self.assertRaisesRegex(Exception, "Checkpoint integrity mismatch"):
                load_active_manifest(root)

    def test_checkpoint_sequence_regression_fails_closed(self):
        first = self.first_rollover()
        bad = copy.deepcopy(first[0])
        bad["checkpoint_sequence"] = bad["archived_sequence"]
        bad = rehash_manifest(bad)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            persist_rollover(root, first, active=True)
            overwrite_active_manifest(root, bad)
            with self.assertRaisesRegex(Exception, "Checkpoint sequence must advance exactly once"):
                load_active_manifest(root)

    def test_mismatched_predecessor_manifest_hash_fails_closed(self):
        first = self.first_rollover()
        second = self.second_rollover(first)
        bad = copy.deepcopy(second[0])
        bad["previous_manifest_hash"] = "sha256:" + "9" * 64
        bad = rehash_manifest(bad)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            persist_rollover(root, first, active=False)
            persist_rollover(root, second, active=True)
            overwrite_active_manifest(root, bad)
            with self.assertRaisesRegex(Exception, "predecessor manifest hash missing"):
                load_active_manifest(root)

    def test_mismatched_predecessor_checkpoint_hash_fails_closed(self):
        first = self.first_rollover()
        unrelated = canonical_state(sequence=6)
        second = self.second_rollover(first, state=unrelated)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            persist_rollover(root, first, active=False)
            persist_rollover(root, second, active=True)
            with self.assertRaisesRegex(Exception, "predecessor checkpoint hash mismatch"):
                load_active_manifest(root)

    def test_conflicting_checkpoint_lineage_fails_closed(self):
        first = self.first_rollover()
        second = self.second_rollover(first)
        alternate_base = checkpoint(
            {"heartbeat": tick(seed_state(), run="333", at="2026-09-30T13:10:00Z")},
            {"heartbeat": "fixture:alternate"},
        )
        alternate_state = canonical_state(sequence=6, base=alternate_base)
        alternate = self.second_rollover(first, state=alternate_state)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            persist_rollover(root, first, active=False)
            persist_rollover(root, alternate, active=False)
            persist_rollover(root, second, active=True)
            with self.assertRaisesRegex(Exception, "Conflicting archive lineage"):
                load_active_manifest(root)

    def test_checkpoint_cannot_silently_change_root_state(self):
        first = self.first_rollover()
        manifest, _raw, checkpoint_doc, _checkpoint_raw, _path = first
        changed = checkpoint(
            {"heartbeat": tick(checkpoint_doc["states"]["heartbeat"], run="444")},
            checkpoint_doc["source_refs"],
        )
        bad_manifest = copy.deepcopy(manifest)
        bad_manifest["new_checkpoint_hash"] = changed["checkpoint_hash"]
        bad_manifest = rehash_manifest(bad_manifest)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            persist_rollover(root, first, active=True)
            overwrite_active_manifest(root, bad_manifest)
            (root / "state_journal/CHECKPOINT.json.gz").write_bytes(gzip_document(changed))
            with self.assertRaisesRegex(Exception, "checkpoint state differs"):
                load_active_manifest(root)

    def test_event_after_checkpoint_still_replays(self):
        first = self.first_rollover()
        manifest, _raw, checkpoint_doc, _checkpoint_raw, _path = first
        before = checkpoint_doc["states"]["heartbeat"]
        after = tick(before, run="200", at="2026-09-30T13:30:00Z")
        event = make_event(
            "runtime-worker",
            "200",
            SHA,
            [make_change("heartbeat", before, after)],
        )
        artifact = {
            "id": 1200,
            "name": "portfolio-state-event-v2-200-runtime-worker-" + SHA + "-1",
            "expired": False,
            "digest": "sha256:" + "d" * 64,
            "created_at": "2026-09-30T13:30:01Z",
            "workflow_run": {"head_branch": "main", "head_sha": SHA},
        }
        state, receipt = reduce_from_provider(
            EventReader(artifact, event),
            since=manifest["artifact_scan_start"],
            current_run="999",
            upload_steps={},
            explicit_checkpoint=checkpoint_doc,
            archive_manifest=manifest,
        )
        self.assertEqual(state["projection"]["states"]["heartbeat"], after)
        self.assertEqual(receipt["new_deliveries"], 1)
        self.assertEqual(state["checkpoint"]["checkpoint_hash"], manifest["new_checkpoint_hash"])

    def test_missing_required_replay_predecessor_fails_closed(self):
        first = self.first_rollover()
        manifest, _raw, checkpoint_doc, _checkpoint_raw, _path = first
        hidden = tick(checkpoint_doc["states"]["heartbeat"], run="199", at="2026-09-30T13:20:00Z")
        after = tick(hidden, run="201", at="2026-09-30T13:30:00Z")
        event = make_event(
            "runtime-worker",
            "201",
            SHA,
            [make_change("heartbeat", hidden, after)],
        )
        artifact = {
            "id": 1201,
            "name": "portfolio-state-event-v2-201-runtime-worker-" + SHA + "-1",
            "expired": False,
            "digest": "sha256:" + "e" * 64,
            "created_at": "2026-09-30T13:30:01Z",
            "workflow_run": {"head_branch": "main", "head_sha": SHA},
        }
        with self.assertRaises(MissingPredecessor):
            reduce_from_provider(
                EventReader(artifact, event),
                since=manifest["artifact_scan_start"],
                current_run="999",
                upload_steps={},
                explicit_checkpoint=checkpoint_doc,
                archive_manifest=manifest,
            )

    def test_racing_event_is_retained_across_checkpoint_publication(self):
        first = self.first_rollover()
        first_manifest = first[0]
        policy = {
            "artifact_scan_start": first_manifest["artifact_scan_start"],
            "limits": {"max_artifact_pages": 20},
        }
        proposed = _proposed_scan_start(policy, first_manifest)
        self.assertEqual(proposed, first_manifest["source_artifact_created_at"])
        row = {
            "id": 1300,
            "name": "portfolio-state-event-v2-300-runtime-worker-" + SHA + "-1",
            "expired": False,
            "digest": "sha256:" + "1" * 64,
            "created_at": "2026-09-30T13:30:00Z",
            "workflow_run": {"head_branch": "main", "head_sha": SHA},
        }
        reader = RetentionReader([row])
        result = _validate_replay_retention(
            reader,
            policy=policy,
            state=canonical_state(sequence=6, base=first[2]),
            active=first_manifest,
            proposed_scan_start=proposed,
        )
        self.assertEqual(result["retained_replay_events"], 1)
        self.assertEqual(reader.calls, [(first_manifest["artifact_scan_start"], 20)])

        second = self.second_rollover(first)
        self.assertLess(second[0]["artifact_scan_start"], second[0]["source_artifact_created_at"])
        self.assertEqual(second[0]["artifact_scan_start"], first_manifest["source_artifact_created_at"])

    def test_next_checkpoint_cannot_drop_unconsumed_overlap_event(self):
        first = self.first_rollover()
        second = self.second_rollover(first)
        second_manifest = second[0]
        policy = {
            "artifact_scan_start": second_manifest["artifact_scan_start"],
            "limits": {"max_artifact_pages": 20},
        }
        proposed = _proposed_scan_start(policy, second_manifest)
        self.assertEqual(proposed, second_manifest["source_artifact_created_at"])
        row = {
            "id": 1301,
            "name": "portfolio-state-event-v2-301-runtime-worker-" + SHA + "-1",
            "expired": False,
            "digest": "sha256:" + "2" * 64,
            "created_at": "2026-09-30T13:30:00Z",
            "workflow_run": {"head_branch": "main", "head_sha": SHA},
        }
        with self.assertRaisesRegex(JournalError, "would drop unconsumed replay event"):
            _validate_replay_retention(
                RetentionReader([row]),
                policy=policy,
                state=canonical_state(sequence=7, base=second[2]),
                active=second_manifest,
                proposed_scan_start=proposed,
            )

    def test_expired_unconsumed_overlap_is_distinct_failure(self):
        first = self.first_rollover()
        manifest = first[0]
        policy = {
            "artifact_scan_start": manifest["artifact_scan_start"],
            "limits": {"max_artifact_pages": 20},
        }
        row = {
            "id": 1302,
            "name": "portfolio-state-event-v2-302-runtime-worker-" + SHA + "-1",
            "expired": True,
            "digest": "sha256:" + "3" * 64,
            "created_at": "2026-09-30T13:30:00Z",
            "workflow_run": {"head_branch": "main", "head_sha": SHA},
        }
        with self.assertRaisesRegex(JournalError, "Expired unconsumed replay evidence"):
            _validate_replay_retention(
                RetentionReader([row]),
                policy=policy,
                state=canonical_state(sequence=6, base=first[2]),
                active=manifest,
                proposed_scan_start=manifest["artifact_scan_start"],
            )

    def test_expired_artifact_already_covered_by_checkpoint_is_routine(self):
        state, _event, evidence = state_with_event(artifact_id=77)
        first = self.first_rollover(state)
        manifest = first[0]
        policy = {
            "artifact_scan_start": manifest["artifact_scan_start"],
            "limits": {"max_artifact_pages": 20},
        }
        row = {
            "id": 77,
            "name": "portfolio-state-event-v2-123-runtime-worker-" + SHA + "-1",
            "expired": True,
            "digest": evidence["archive_digest"],
            "created_at": "2026-09-30T12:59:59Z",
            "workflow_run": {"head_branch": "main", "head_sha": SHA},
        }
        result = _validate_replay_retention(
            RetentionReader([row]),
            policy=policy,
            state=state,
            active=manifest,
            proposed_scan_start=manifest["artifact_scan_start"],
        )
        self.assertEqual(result["covered_journal_events"], 1)
        self.assertEqual(result["retained_replay_events"], 0)

    def test_bounded_discovery_keeps_policy_page_bound(self):
        first = self.first_rollover()
        manifest = first[0]
        policy = {
            "artifact_scan_start": manifest["artifact_scan_start"],
            "limits": {"max_artifact_pages": 7},
        }
        reader = RetentionReader([])
        _validate_replay_retention(
            reader,
            policy=policy,
            state=canonical_state(sequence=6, base=first[2]),
            active=manifest,
            proposed_scan_start=manifest["artifact_scan_start"],
        )
        self.assertEqual(reader.calls, [(manifest["artifact_scan_start"], 7)])


if __name__ == "__main__":
    unittest.main()
