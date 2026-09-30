import copy
import gzip
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from agents.heartbeat_state import heartbeat, seed_state
from state_journal.archive import (
    archived_artifact_ids,
    build_rollover,
    load_active_manifest,
    validate_manifest,
)
from state_journal.contracts import JournalError, REPOSITORY, canonical
from state_journal.events import make_change, make_event
from state_journal.github_reducer import reduce_from_provider
from state_journal.production_reader import _pending_events
from state_journal.reducer import checkpoint, make_snapshot, set_authority


SHA = "a" * 40


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
        "agent-heartbeat-sweep", run_id, SHA,
        [make_change("heartbeat", before, after)],
    )
    return after, event


def fixture_evidence(event):
    return {"kind": "FIXTURE", "event_hash": event["event_hash"], "fixture_id": "fixture:archive-lifecycle"}


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


def canonical_state_with_event(sequence=6, *, provider=False):
    base = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
    _after, event = heartbeat_event(base["states"]["heartbeat"])
    evidence = provider_evidence(event) if provider else fixture_evidence(event)
    state = make_snapshot(base, [event], sequence=sequence, evidence={event["event_id"]: [evidence]})
    return set_authority(state, mode="CANONICAL", production_authority=True), event, evidence


def write_archive_root(root, manifest, archive_raw, checkpoint_raw, archive_path):
    (root / "state_journal/archive").mkdir(parents=True, exist_ok=True)
    (root / archive_path).write_bytes(archive_raw)
    (root / manifest["manifest_path"]).write_bytes(canonical(manifest) + b"\n")
    (root / "state_journal/ARCHIVE_MANIFEST.json").write_bytes(canonical(manifest) + b"\n")
    (root / "state_journal/CHECKPOINT.json.gz").write_bytes(checkpoint_raw)


def canonical_state(sequence=5):
    base = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
    state = make_snapshot(base, [], sequence=sequence, evidence={})
    return set_authority(state, mode="CANONICAL", production_authority=True)


class EmptyJournalReader:
    def list_recent_journal_artifacts(self, *args, **kwargs):
        return []


class ArchiveLifecycleTests(unittest.TestCase):
    def build(self, sequence=5):
        return build_rollover(
            canonical_state(sequence),
            source_reducer_run_id=900,
            source_artifact_id=901,
            source_head_sha="a" * 40,
            source_artifact_digest="sha256:" + "b" * 64,
            source_artifact_created_at="2026-09-30T13:17:34Z",
        )

    def test_rollover_binds_full_archive_to_compacted_checkpoint(self):
        manifest, archive_raw, compacted, checkpoint_raw, archive_path = self.build()
        self.assertEqual(manifest["archived_sequence"], 5)
        self.assertEqual(manifest["checkpoint_sequence"], 6)
        self.assertEqual(manifest["archived_event_count"], 0)
        self.assertEqual(compacted["states"], canonical_state()["projection"]["states"])
        self.assertTrue(archive_path.startswith("state_journal/archive/"))
        self.assertTrue(archive_raw.startswith(b"\x1f\x8b"))
        self.assertTrue(checkpoint_raw.startswith(b"\x1f\x8b"))

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "state_journal/archive").mkdir(parents=True)
            (root / archive_path).write_bytes(archive_raw)
            (root / manifest["manifest_path"]).write_text(
                json.dumps(manifest, sort_keys=True, separators=(",", ":"))
            )
            (root / "state_journal/ARCHIVE_MANIFEST.json").write_text(
                json.dumps(manifest, sort_keys=True, separators=(",", ":"))
            )
            (root / "state_journal/CHECKPOINT.json.gz").write_bytes(checkpoint_raw)
            loaded = load_active_manifest(root)
            self.assertEqual(loaded["manifest_hash"], manifest["manifest_hash"])

    def test_repository_archive_tamper_fails_closed(self):
        manifest, archive_raw, _compacted, checkpoint_raw, archive_path = self.build()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "state_journal/archive").mkdir(parents=True)
            (root / archive_path).write_bytes(archive_raw + b"tamper")
            (root / manifest["manifest_path"]).write_text(
                json.dumps(manifest, sort_keys=True, separators=(",", ":"))
            )
            (root / "state_journal/ARCHIVE_MANIFEST.json").write_text(
                json.dumps(manifest, sort_keys=True, separators=(",", ":"))
            )
            (root / "state_journal/CHECKPOINT.json.gz").write_bytes(checkpoint_raw)
            with self.assertRaisesRegex(Exception, "file digest mismatch"):
                load_active_manifest(root)

    def test_reducer_rebuilds_from_checkpoint_when_actions_history_is_empty(self):
        manifest, _archive_raw, compacted, _checkpoint_raw, _archive_path = self.build(sequence=8)
        state, receipt = reduce_from_provider(
            EmptyJournalReader(),
            since="2026-09-30T13:17:34Z",
            current_run="999",
            upload_steps={},
            explicit_checkpoint=compacted,
            archive_manifest=manifest,
        )
        self.assertEqual(state["sequence"], 9)
        self.assertEqual(state["event_count"], 0)
        self.assertEqual(state["checkpoint"]["checkpoint_hash"], manifest["new_checkpoint_hash"])
        self.assertTrue(receipt["recovered_from_archive_checkpoint"])
        self.assertFalse(receipt["checkpoint_rollover"])

    def test_existing_archived_source_rolls_forward_exactly_once(self):
        old = canonical_state(sequence=12)
        manifest, _archive_raw, compacted, _checkpoint_raw, _archive_path = build_rollover(
            old,
            source_reducer_run_id=900,
            source_artifact_id=901,
            source_head_sha="a" * 40,
            source_artifact_digest="sha256:" + "b" * 64,
            source_artifact_created_at="2026-09-30T13:17:34Z",
        )

        class Reader(EmptyJournalReader):
            pass

        import state_journal.github_reducer as reducer_module
        original = reducer_module.restore_snapshot
        reducer_module.restore_snapshot = lambda *args, **kwargs: old
        try:
            state, receipt = reduce_from_provider(
                Reader(),
                since="2026-09-30T13:17:34Z",
                current_run="999",
                upload_steps={},
                explicit_checkpoint=compacted,
                archive_manifest=manifest,
            )
        finally:
            reducer_module.restore_snapshot = original

        self.assertEqual(state["sequence"], 13)
        self.assertEqual(state["projection"]["states"], old["projection"]["states"])
        self.assertTrue(receipt["checkpoint_rollover"])
        self.assertFalse(receipt["recovered_from_archive_checkpoint"])

    def test_expired_event_artifact_covered_by_validated_checkpoint_is_routine(self):
        state, event, evidence = canonical_state_with_event(sequence=8, provider=True)
        manifest, _archive_raw, compacted, _checkpoint_raw, _archive_path = build_rollover(
            state,
            source_reducer_run_id=900,
            source_artifact_id=901,
            source_head_sha="b" * 40,
            source_artifact_digest="sha256:" + "d" * 64,
            source_artifact_created_at="2026-09-30T13:20:00Z",
        )
        artifact = {
            "id": evidence["artifact_id"],
            "name": f"portfolio-state-event-v2-{event['run_id']}-agent-heartbeat-sweep-{SHA}-1",
            "expired": True,
            "digest": evidence["archive_digest"],
            "workflow_run": {"id": int(event["run_id"]), "head_branch": "main", "head_sha": SHA},
        }
        self.assertEqual(_pending_events(state, [artifact], archived_ids=archived_artifact_ids(manifest)), [])

        class Reader:
            def list_recent_journal_artifacts(self, *args, **kwargs):
                return [artifact]
            def event(self, *args, **kwargs):
                raise AssertionError("archived event must not be re-opened")

        with patch("state_journal.github_reducer.restore_snapshot", return_value=state):
            candidate, receipt = reduce_from_provider(
                Reader(),
                since=manifest["artifact_scan_start"],
                current_run="999",
                upload_steps={},
                explicit_checkpoint=compacted,
                archive_manifest=manifest,
            )
        self.assertEqual(candidate["projection"], state["projection"])
        self.assertEqual(candidate["checkpoint"]["checkpoint_hash"], manifest["new_checkpoint_hash"])
        self.assertEqual(receipt["new_deliveries"], 0)

    def test_event_after_checkpoint_replays_from_retained_overlap(self):
        archived = canonical_state(sequence=8)
        manifest, _archive_raw, compacted, _checkpoint_raw, _archive_path = build_rollover(
            archived,
            source_reducer_run_id=900,
            source_artifact_id=901,
            source_head_sha="b" * 40,
            source_artifact_digest="sha256:" + "d" * 64,
            source_artifact_created_at="2026-09-30T13:20:00Z",
        )
        _after, event = heartbeat_event(compacted["states"]["heartbeat"], run_id="102", at="2026-09-30T13:21:00Z")
        evidence = fixture_evidence(event)
        artifact = {
            "id": 902,
            "name": f"portfolio-state-event-v2-102-agent-heartbeat-sweep-{SHA}-1",
            "expired": False,
            "digest": "sha256:" + "e" * 64,
            "created_at": "2026-09-30T13:21:01Z",
            "workflow_run": {"id": 102, "head_branch": "main", "head_sha": SHA},
        }

        class Reader:
            def list_recent_journal_artifacts(self, *args, **kwargs):
                return [artifact]
            def event(self, *args, **kwargs):
                return event, evidence

        with patch("state_journal.github_reducer.restore_snapshot", return_value=None):
            candidate, receipt = reduce_from_provider(
                Reader(),
                since=manifest["artifact_scan_start"],
                current_run="999",
                upload_steps={},
                explicit_checkpoint=compacted,
                archive_manifest=manifest,
            )
        self.assertEqual(candidate["event_ids"] if "event_ids" in candidate else candidate["projection"]["event_ids"], [event["event_id"]])
        self.assertEqual(candidate["projection"]["states"]["heartbeat"]["sequence"], 1)
        self.assertEqual(receipt["new_deliveries"], 1)
        self.assertTrue(receipt["recovered_from_archive_checkpoint"])

    def test_event_racing_checkpoint_publication_is_retained_and_reconstructed_exactly(self):
        archived = canonical_state(sequence=8)
        manifest, _archive_raw, compacted, _checkpoint_raw, _archive_path = build_rollover(
            archived,
            source_reducer_run_id=900,
            source_artifact_id=901,
            source_head_sha="b" * 40,
            source_artifact_digest="sha256:" + "d" * 64,
            source_artifact_created_at="2026-09-30T13:20:00Z",
        )
        _after, event = heartbeat_event(
            archived["projection"]["states"]["heartbeat"],
            run_id="103",
            at="2026-09-30T13:20:30Z",
        )
        live = make_snapshot(
            archived["checkpoint"], [event], sequence=9,
            evidence={event["event_id"]: [fixture_evidence(event)]},
            mode="CANONICAL", production_authority=True,
        )
        with patch("state_journal.github_reducer.restore_snapshot", return_value=live):
            candidate, receipt = reduce_from_provider(
                EmptyJournalReader(),
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

    def test_missing_required_replay_fails_closed(self):
        archived, _event, _evidence = canonical_state_with_event(sequence=8)
        manifest, _archive_raw, compacted, _checkpoint_raw, _archive_path = build_rollover(
            archived,
            source_reducer_run_id=900,
            source_artifact_id=901,
            source_head_sha="b" * 40,
            source_artifact_digest="sha256:" + "d" * 64,
            source_artifact_created_at="2026-09-30T13:20:00Z",
        )
        incomplete = set_authority(
            make_snapshot(archived["checkpoint"], [], sequence=9, evidence={}),
            mode="CANONICAL", production_authority=True,
        )
        with patch("state_journal.github_reducer.restore_snapshot", return_value=incomplete):
            with self.assertRaisesRegex(JournalError, "INCOMPLETE_REPLAY"):
                reduce_from_provider(
                    EmptyJournalReader(),
                    since=manifest["artifact_scan_start"],
                    current_run="999",
                    upload_steps={},
                    explicit_checkpoint=compacted,
                    archive_manifest=manifest,
                )

    def test_conflicting_checkpoint_lineage_fails_closed(self):
        archived = canonical_state(sequence=8)
        manifest, _archive_raw, compacted, _checkpoint_raw, _archive_path = build_rollover(
            archived,
            source_reducer_run_id=900,
            source_artifact_id=901,
            source_head_sha="b" * 40,
            source_artifact_digest="sha256:" + "d" * 64,
            source_artifact_created_at="2026-09-30T13:20:00Z",
        )
        foreign_base = checkpoint(
            {"heartbeat": seed_state()},
            {"heartbeat": "fixture:different-root"},
        )
        foreign = set_authority(
            make_snapshot(foreign_base, [], sequence=9, evidence={}),
            mode="CANONICAL", production_authority=True,
        )
        with patch("state_journal.github_reducer.restore_snapshot", return_value=foreign):
            with self.assertRaisesRegex(JournalError, "CONFLICTING_LINEAGE"):
                reduce_from_provider(
                    EmptyJournalReader(),
                    since=manifest["artifact_scan_start"],
                    current_run="999",
                    upload_steps={},
                    explicit_checkpoint=compacted,
                    archive_manifest=manifest,
                )

    def test_corrupted_checkpoint_hash_fails_closed(self):
        manifest, archive_raw, compacted, checkpoint_raw, archive_path = self.build()
        corrupted = copy.deepcopy(compacted)
        corrupted["checkpoint_hash"] = "sha256:" + "0" * 64
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_archive_root(root, manifest, archive_raw, checkpoint_raw, archive_path)
            (root / "state_journal/CHECKPOINT.json.gz").write_bytes(
                gzip.compress(canonical(corrupted) + b"\n", compresslevel=9, mtime=0)
            )
            with self.assertRaisesRegex(Exception, "Checkpoint integrity mismatch"):
                load_active_manifest(root)

    def test_checkpoint_cannot_silently_change_root_state(self):
        archived = canonical_state(sequence=8)
        manifest, _archive_raw, compacted, _checkpoint_raw, _archive_path = build_rollover(
            archived,
            source_reducer_run_id=900,
            source_artifact_id=901,
            source_head_sha="b" * 40,
            source_artifact_digest="sha256:" + "d" * 64,
            source_artifact_created_at="2026-09-30T13:20:00Z",
        )
        after, _event = heartbeat_event(compacted["states"]["heartbeat"], run_id="104", at="2026-09-30T13:22:00Z")
        changed_root = checkpoint({"heartbeat": after}, compacted["source_refs"])
        with patch("state_journal.github_reducer.restore_snapshot", return_value=archived):
            with self.assertRaisesRegex(JournalError, "binding mismatch"):
                reduce_from_provider(
                    EmptyJournalReader(),
                    since=manifest["artifact_scan_start"],
                    current_run="999",
                    upload_steps={},
                    explicit_checkpoint=changed_root,
                    archive_manifest=manifest,
                )

    def test_successor_archive_requires_exact_predecessor_checkpoint_hash_and_sequence(self):
        previous, _archive_raw, previous_checkpoint, _checkpoint_raw, _archive_path = self.build(sequence=5)
        correct_root = set_authority(
            make_snapshot(previous_checkpoint, [], sequence=previous["checkpoint_sequence"], evidence={}),
            mode="CANONICAL", production_authority=True,
        )
        manifest2, _raw2, _cp2, _cpr2, _path2 = build_rollover(
            correct_root,
            source_reducer_run_id=902,
            source_artifact_id=903,
            source_head_sha="c" * 40,
            source_artifact_digest="sha256:" + "e" * 64,
            source_artifact_created_at="2026-09-30T14:20:00Z",
            previous_manifest=previous,
        )
        self.assertEqual(manifest2["previous_manifest_hash"], previous["manifest_hash"])
        self.assertEqual(manifest2["previous_manifest_path"], previous["manifest_path"])
        self.assertEqual(manifest2["archived_checkpoint_hash"], previous["new_checkpoint_hash"])

        wrong_root = canonical_state(sequence=previous["checkpoint_sequence"])
        with self.assertRaisesRegex(JournalError, "predecessor hash mismatch"):
            build_rollover(
                wrong_root,
                source_reducer_run_id=904,
                source_artifact_id=905,
                source_head_sha="d" * 40,
                source_artifact_digest="sha256:" + "f" * 64,
                source_artifact_created_at="2026-09-30T15:20:00Z",
                previous_manifest=previous,
            )

        regressed = set_authority(
            make_snapshot(previous_checkpoint, [], sequence=previous["checkpoint_sequence"] - 1, evidence={}),
            mode="CANONICAL", production_authority=True,
        )
        with self.assertRaisesRegex(JournalError, "sequence regressed"):
            build_rollover(
                regressed,
                source_reducer_run_id=906,
                source_artifact_id=907,
                source_head_sha="e" * 40,
                source_artifact_digest="sha256:" + "1" * 64,
                source_artifact_created_at="2026-09-30T16:20:00Z",
                previous_manifest=previous,
            )

    def test_manifest_records_explicit_bounded_replay_overlap(self):
        manifest, _archive_raw, _compacted, _checkpoint_raw, _archive_path = self.build()
        self.assertEqual(manifest["replay_overlap_seconds"], 6 * 60 * 60)
        self.assertEqual(manifest["artifact_scan_start"], "2026-09-30T07:17:34Z")

    def test_checkpoint_candidate_and_reducer_are_recurring_but_protected(self):
        root = Path(__file__).resolve().parents[1]
        reducer = (root / ".github/workflows/portfolio-state-reducer.yml").read_text()
        candidate = (root / ".github/workflows/portfolio-state-checkpoint-candidate.yml").read_text()
        self.assertIn('cron: "11 4 * * *"', reducer)
        self.assertIn('cron: "19 4 * * 0"', candidate)
        self.assertIn("python -m state_journal.checkpoint_archive", candidate)
        self.assertIn("gh pr create", candidate)
        self.assertNotIn("gh pr merge", candidate)
        self.assertNotIn("git push origin main", candidate)
        self.assertIn("actions: read", candidate)
        self.assertIn("contents: write", candidate)
        self.assertIn("pull-requests: write", candidate)


if __name__ == "__main__":
    unittest.main()
