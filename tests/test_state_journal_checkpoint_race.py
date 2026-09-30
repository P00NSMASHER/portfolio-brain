import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.heartbeat_state import heartbeat, seed_state
from state_journal.archive import (
    ARCHIVE_SCHEMA,
    ARCHIVE_SCHEMA_LEGACY,
    REPLAY_OVERLAP_SECONDS,
    archived_artifact_ids,
    build_rollover,
    load_active_manifest,
)
from state_journal.contracts import JournalError, REPOSITORY, canonical, digest
from state_journal.events import make_change, make_event
from state_journal.github_reducer import reduce_from_provider
from state_journal.production_reader import _pending_events
from state_journal.reducer import checkpoint, make_snapshot, set_authority
from state_journal.transport import EVENT_PREFIX

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
V2_ONLY_FIELDS = {
    "checkpoint_id",
    "checkpoint_freshness_at",
    "previous_manifest_path",
    "previous_checkpoint_hash",
    "replay_overlap_seconds",
}


def canonical_state(sequence=8):
    base = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
    state = make_snapshot(base, [], sequence=sequence, evidence={})
    return set_authority(state, mode="CANONICAL", production_authority=True)


def heartbeat_event(before, *, run_id="101", at="2026-09-30T13:18:00Z"):
    agent_id = sorted(before["agents"])[0]
    after = heartbeat(
        before,
        agent_ids=[agent_id],
        activity_kind="TEST",
        source_workflow="agent-heartbeat-sweep",
        source_run_id=run_id,
        at=at,
    )
    event = make_event(
        "agent-heartbeat-sweep",
        run_id,
        SHA,
        [make_change("heartbeat", before, after)],
    )
    return after, event


def fixture_evidence(event):
    return {
        "kind": "FIXTURE",
        "event_hash": event["event_hash"],
        "fixture_id": "fixture:archive-race",
    }


def provider_evidence(event, *, artifact_id=77, archive_digest="sha256:" + "c" * 64):
    return {
        "kind": "GITHUB_ACTIONS",
        "repository": REPOSITORY,
        "artifact_id": artifact_id,
        "archive_digest": archive_digest,
        "source_run_id": int(event["run_id"]),
        "source_run_attempt": 1,
        "source_sha": event["source_sha"],
        "workflow_id": 11,
        "workflow_path": ".github/workflows/agent-heartbeat-sweep.yml",
        "source_conclusion": "success",
        "event_hash": event["event_hash"],
        "job_id": 12,
    }


def state_with_event(*, sequence=8, provider=False):
    base = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
    _after, event = heartbeat_event(base["states"]["heartbeat"])
    evidence = provider_evidence(event) if provider else fixture_evidence(event)
    state = make_snapshot(
        base,
        [event],
        sequence=sequence,
        evidence={event["event_id"]: [evidence]},
    )
    return set_authority(state, mode="CANONICAL", production_authority=True), event, evidence


def rollover(state, *, previous=None, created_at="2026-09-30T13:20:00Z"):
    return build_rollover(
        state,
        source_reducer_run_id=900,
        source_artifact_id=901,
        source_head_sha="b" * 40,
        source_artifact_digest="sha256:" + "d" * 64,
        source_artifact_created_at=created_at,
        previous_manifest=previous,
    )


def legacy_manifest(manifest):
    legacy = {
        key: copy.deepcopy(value)
        for key, value in manifest.items()
        if key not in V2_ONLY_FIELDS
    }
    legacy["schema_version"] = ARCHIVE_SCHEMA_LEGACY
    legacy["artifact_scan_start"] = legacy["source_artifact_created_at"]
    core = {key: value for key, value in legacy.items() if key != "manifest_hash"}
    legacy["manifest_hash"] = digest(core)
    return legacy


class EmptyReader:
    def list_recent_journal_artifacts(self, *args, **kwargs):
        return []


class CheckpointArchiveRaceTests(unittest.TestCase):
    def test_checked_in_active_archive_is_valid_and_backward_compatible(self):
        active = load_active_manifest(ROOT)
        self.assertIsNotNone(active)
        self.assertIn(active["schema_version"], {ARCHIVE_SCHEMA_LEGACY, ARCHIVE_SCHEMA})
        self.assertGreaterEqual(active["archived_sequence"], 0)

    def test_successor_manifest_records_checkpoint_identity_lineage_and_overlap(self):
        first, _raw1, cp1, _cpraw1, _path1 = rollover(canonical_state(8))
        rooted = set_authority(
            make_snapshot(cp1, [], sequence=first["checkpoint_sequence"], evidence={}),
            mode="CANONICAL",
            production_authority=True,
        )
        second, _raw2, _cp2, _cpraw2, _path2 = rollover(
            rooted,
            previous=first,
            created_at="2026-09-30T14:20:00Z",
        )
        self.assertEqual(second["schema_version"], ARCHIVE_SCHEMA)
        self.assertEqual(second["previous_manifest_hash"], first["manifest_hash"])
        self.assertEqual(second["previous_manifest_path"], first["manifest_path"])
        self.assertEqual(second["previous_checkpoint_hash"], first["new_checkpoint_hash"])
        self.assertEqual(second["archived_checkpoint_hash"], first["new_checkpoint_hash"])
        self.assertTrue(second["checkpoint_id"].startswith("canonical-checkpoint-seq-"))
        self.assertEqual(second["checkpoint_freshness_at"], second["source_artifact_created_at"])
        self.assertEqual(second["replay_overlap_seconds"], REPLAY_OVERLAP_SECONDS)
        self.assertEqual(second["artifact_scan_start"], "2026-09-30T08:20:00Z")

    def test_legacy_predecessor_can_seed_v11_successor(self):
        first, _raw1, cp1, _cpraw1, _path1 = rollover(canonical_state(8))
        previous = legacy_manifest(first)
        rooted = set_authority(
            make_snapshot(cp1, [], sequence=previous["checkpoint_sequence"], evidence={}),
            mode="CANONICAL",
            production_authority=True,
        )
        second, _raw2, _cp2, _cpraw2, _path2 = rollover(
            rooted,
            previous=previous,
            created_at="2026-09-30T14:20:00Z",
        )
        self.assertEqual(second["schema_version"], ARCHIVE_SCHEMA)
        self.assertEqual(second["previous_manifest_hash"], previous["manifest_hash"])
        self.assertEqual(second["previous_checkpoint_hash"], previous["new_checkpoint_hash"])

    def test_event_racing_checkpoint_publication_is_retained_exactly(self):
        archived = canonical_state(8)
        manifest, _raw, compacted, _cpraw, _path = rollover(archived)
        _after, event = heartbeat_event(
            archived["projection"]["states"]["heartbeat"],
            run_id="102",
            at="2026-09-30T13:20:30Z",
        )
        live = set_authority(
            make_snapshot(
                archived["checkpoint"],
                [event],
                sequence=9,
                evidence={event["event_id"]: [fixture_evidence(event)]},
            ),
            mode="CANONICAL",
            production_authority=True,
        )
        with patch("state_journal.github_reducer.restore_snapshot", return_value=live):
            candidate, receipt = reduce_from_provider(
                EmptyReader(),
                since=manifest["artifact_scan_start"],
                current_run="999",
                upload_steps={},
                explicit_checkpoint=compacted,
                archive_manifest=manifest,
            )
        self.assertEqual(candidate["projection"], live["projection"])
        self.assertEqual(candidate["checkpoint"]["checkpoint_hash"], manifest["new_checkpoint_hash"])
        self.assertEqual(candidate["events"], [event])
        self.assertTrue(receipt["checkpoint_rollover"])
        self.assertEqual(receipt["checkpoint_rollover_replay_events"], 1)
        self.assertEqual(receipt["checkpoint_recovery_status"], "VALID_CHECKPOINT")

    def test_event_after_checkpoint_replays_from_explicit_overlap(self):
        archived = canonical_state(8)
        manifest, _raw, compacted, _cpraw, _path = rollover(archived)
        _after, event = heartbeat_event(
            compacted["states"]["heartbeat"],
            run_id="103",
            at="2026-09-30T13:21:00Z",
        )
        evidence = fixture_evidence(event)
        artifact = {
            "id": 902,
            "name": f"{EVENT_PREFIX}103-agent-heartbeat-sweep-{SHA}-1",
            "expired": False,
            "digest": "sha256:" + "e" * 64,
            "created_at": "2026-09-30T13:21:01Z",
            "workflow_run": {"id": 103, "head_branch": "main", "head_sha": SHA},
        }

        class Reader:
            def __init__(self):
                self.since = None
            def list_recent_journal_artifacts(self, since, **kwargs):
                self.since = since
                return [artifact]
            def event(self, *args, **kwargs):
                return event, evidence

        reader = Reader()
        with patch("state_journal.github_reducer.restore_snapshot", return_value=None):
            candidate, receipt = reduce_from_provider(
                reader,
                since=manifest["artifact_scan_start"],
                current_run="999",
                upload_steps={},
                explicit_checkpoint=compacted,
                archive_manifest=manifest,
            )
        self.assertEqual(reader.since, manifest["artifact_scan_start"])
        self.assertEqual(candidate["projection"]["event_ids"], [event["event_id"]])
        self.assertEqual(candidate["projection"]["states"]["heartbeat"]["sequence"], 1)
        self.assertEqual(receipt["new_deliveries"], 1)
        self.assertTrue(receipt["recovered_from_archive_checkpoint"])

    def test_expired_old_artifact_covered_by_checkpoint_is_routine(self):
        archived, event, evidence = state_with_event(sequence=8, provider=True)
        manifest, _raw, compacted, _cpraw, _path = rollover(archived)
        artifact = {
            "id": evidence["artifact_id"],
            "name": f"{EVENT_PREFIX}{event['run_id']}-agent-heartbeat-sweep-{SHA}-1",
            "expired": True,
            "digest": evidence["archive_digest"],
            "created_at": "2026-09-30T13:18:01Z",
            "workflow_run": {
                "id": int(event["run_id"]),
                "head_branch": "main",
                "head_sha": SHA,
            },
        }
        self.assertEqual(
            _pending_events(archived, [artifact], archived_ids=archived_artifact_ids(manifest)),
            [],
        )

        class Reader:
            def list_recent_journal_artifacts(self, *args, **kwargs):
                return [artifact]
            def event(self, *args, **kwargs):
                raise AssertionError("archived evidence must not be reopened")

        with patch("state_journal.github_reducer.restore_snapshot", return_value=archived):
            candidate, receipt = reduce_from_provider(
                Reader(),
                since=manifest["artifact_scan_start"],
                current_run="999",
                upload_steps={},
                explicit_checkpoint=compacted,
                archive_manifest=manifest,
            )
        self.assertEqual(
            candidate["projection"]["states"],
            archived["projection"]["states"],
        )
        self.assertEqual(
            candidate["projection"]["projection_hash"],
            archived["projection"]["projection_hash"],
        )
        self.assertEqual(candidate["events"], [])
        self.assertEqual(receipt["new_deliveries"], 0)

    def test_unconsumed_expired_artifact_is_distinct_failure(self):
        archived = canonical_state(8)
        manifest, _raw, compacted, _cpraw, _path = rollover(archived)
        artifact = {
            "id": 999,
            "name": f"{EVENT_PREFIX}106-agent-heartbeat-sweep-{SHA}-1",
            "expired": True,
            "digest": "sha256:" + "9" * 64,
            "created_at": "2026-09-30T13:22:00Z",
            "workflow_run": {"id": 106, "head_branch": "main", "head_sha": SHA},
        }

        class Reader:
            def list_recent_journal_artifacts(self, *args, **kwargs):
                return [artifact]

        with patch("state_journal.github_reducer.restore_snapshot", return_value=None):
            with self.assertRaisesRegex(JournalError, "EXPIRED_EVIDENCE"):
                reduce_from_provider(
                    Reader(),
                    since=manifest["artifact_scan_start"],
                    current_run="999",
                    upload_steps={},
                    explicit_checkpoint=compacted,
                    archive_manifest=manifest,
                )

    def test_corrupted_checkpoint_hash_is_distinct_failure(self):
        manifest, archive_raw, compacted, _cpraw, archive_path = rollover(canonical_state(8))
        corrupted = copy.deepcopy(compacted)
        corrupted["checkpoint_hash"] = "sha256:" + "0" * 64
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "state_journal/archive").mkdir(parents=True)
            (root / archive_path).write_bytes(archive_raw)
            (root / manifest["manifest_path"]).write_bytes(canonical(manifest) + b"\n")
            (root / "state_journal/ARCHIVE_MANIFEST.json").write_bytes(canonical(manifest) + b"\n")
            (root / "state_journal/CHECKPOINT.json.gz").write_bytes(
                gzip.compress(canonical(corrupted) + b"\n", compresslevel=9, mtime=0)
            )
            with self.assertRaisesRegex(JournalError, "CORRUPTED_CHECKPOINT"):
                load_active_manifest(root)

    def test_incomplete_archived_prefix_replay_fails_closed(self):
        archived, _event, _evidence = state_with_event(sequence=8)
        manifest, _raw, compacted, _cpraw, _path = rollover(archived)
        incomplete = set_authority(
            make_snapshot(archived["checkpoint"], [], sequence=9, evidence={}),
            mode="CANONICAL",
            production_authority=True,
        )
        with patch("state_journal.github_reducer.restore_snapshot", return_value=incomplete):
            with self.assertRaisesRegex(JournalError, "INCOMPLETE_REPLAY"):
                reduce_from_provider(
                    EmptyReader(),
                    since=manifest["artifact_scan_start"],
                    current_run="999",
                    upload_steps={},
                    explicit_checkpoint=compacted,
                    archive_manifest=manifest,
                )

    def test_missing_post_checkpoint_predecessor_is_distinct_failure(self):
        archived = canonical_state(8)
        manifest, _raw, compacted, _cpraw, _path = rollover(archived)
        intermediate = heartbeat(
            compacted["states"]["heartbeat"],
            agent_ids=[sorted(compacted["states"]["heartbeat"]["agents"])[0]],
            activity_kind="TEST",
            source_workflow="agent-heartbeat-sweep",
            source_run_id="104",
            at="2026-09-30T13:21:00Z",
        )
        _after, event = heartbeat_event(intermediate, run_id="105", at="2026-09-30T13:22:00Z")
        evidence = fixture_evidence(event)
        artifact = {
            "id": 905,
            "name": f"{EVENT_PREFIX}105-agent-heartbeat-sweep-{SHA}-1",
            "expired": False,
            "digest": "sha256:" + "5" * 64,
            "created_at": "2026-09-30T13:22:01Z",
            "workflow_run": {"id": 105, "head_branch": "main", "head_sha": SHA},
        }

        class Reader:
            def list_recent_journal_artifacts(self, *args, **kwargs):
                return [artifact]
            def event(self, *args, **kwargs):
                return event, evidence

        with patch("state_journal.github_reducer.restore_snapshot", return_value=None):
            with self.assertRaisesRegex(JournalError, "MISSING_REPLAY"):
                reduce_from_provider(
                    Reader(),
                    since=manifest["artifact_scan_start"],
                    current_run="999",
                    upload_steps={},
                    explicit_checkpoint=compacted,
                    archive_manifest=manifest,
                )

    def test_conflicting_live_checkpoint_lineage_fails_closed(self):
        archived = canonical_state(8)
        manifest, _raw, compacted, _cpraw, _path = rollover(archived)
        foreign_base = checkpoint(
            {"heartbeat": seed_state()},
            {"heartbeat": "fixture:foreign-root"},
        )
        foreign = set_authority(
            make_snapshot(foreign_base, [], sequence=9, evidence={}),
            mode="CANONICAL",
            production_authority=True,
        )
        with patch("state_journal.github_reducer.restore_snapshot", return_value=foreign):
            with self.assertRaisesRegex(JournalError, "CONFLICTING_LINEAGE"):
                reduce_from_provider(
                    EmptyReader(),
                    since=manifest["artifact_scan_start"],
                    current_run="999",
                    upload_steps={},
                    explicit_checkpoint=compacted,
                    archive_manifest=manifest,
                )

    def test_checkpoint_root_cannot_be_silently_substituted(self):
        archived = canonical_state(8)
        manifest, _raw, compacted, _cpraw, _path = rollover(archived)
        changed_state = heartbeat(
            compacted["states"]["heartbeat"],
            agent_ids=[sorted(compacted["states"]["heartbeat"]["agents"])[0]],
            activity_kind="TEST",
            source_workflow="agent-heartbeat-sweep",
            source_run_id="107",
            at="2026-09-30T13:23:00Z",
        )
        changed_checkpoint = checkpoint(
            {"heartbeat": changed_state},
            compacted["source_refs"],
        )
        with patch("state_journal.github_reducer.restore_snapshot", return_value=archived):
            with self.assertRaisesRegex(JournalError, "binding mismatch"):
                reduce_from_provider(
                    EmptyReader(),
                    since=manifest["artifact_scan_start"],
                    current_run="999",
                    upload_steps={},
                    explicit_checkpoint=changed_checkpoint,
                    archive_manifest=manifest,
                )

    def test_successor_rejects_predecessor_hash_mismatch_and_sequence_regression(self):
        first, _raw1, cp1, _cpraw1, _path1 = rollover(canonical_state(8))
        wrong_root = canonical_state(first["checkpoint_sequence"])
        with self.assertRaisesRegex(JournalError, "predecessor hash mismatch"):
            rollover(wrong_root, previous=first, created_at="2026-09-30T14:20:00Z")

        regressed = set_authority(
            make_snapshot(cp1, [], sequence=first["checkpoint_sequence"] - 1, evidence={}),
            mode="CANONICAL",
            production_authority=True,
        )
        with self.assertRaisesRegex(JournalError, "sequence regressed"):
            rollover(regressed, previous=first, created_at="2026-09-30T14:20:00Z")

    def test_bounded_discovery_limits_are_not_raised(self):
        policy = json.loads((ROOT / "state_journal/POLICY.json").read_text())
        self.assertEqual(policy["limits"]["max_artifact_pages"], 20)
        self.assertEqual(policy["limits"]["max_read_requests"], 100)


if __name__ == "__main__":
    unittest.main()
