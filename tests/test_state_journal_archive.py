import json
import tempfile
import unittest
from pathlib import Path

from agents.heartbeat_state import seed_state
from state_journal.archive import (
    _require_sanitized_archive,
    archived_artifact_ids,
    build_rollover,
    load_active_manifest,
    validate_manifest,
)
from state_journal.github_reducer import reduce_from_provider
from state_journal.production_reader import _pending_events
from state_journal.reducer import checkpoint, make_snapshot, set_authority


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

    def test_public_archive_rejects_credential_like_material(self):
        for raw in (
            b"github_pat_" + b"A" * 32,
            b"ghp_" + b"B" * 32,
            b"sk-" + b"C" * 32,
            b"-----BEGIN PRIVATE KEY-----",
        ):
            with self.subTest(raw=raw[:16]), self.assertRaisesRegex(Exception, "Credential-like material"):
                _require_sanitized_archive(raw)

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

    def test_archived_overlap_artifact_is_not_pending_or_replayed(self):
        state = canonical_state()
        artifact = {
            "id": 77,
            "name": "portfolio-state-event-v2-123-agent-heartbeat-sweep-" + "a" * 40 + "-1",
            "expired": True,
            "digest": "sha256:" + "c" * 64,
            "workflow_run": {"id": 123, "head_branch": "main", "head_sha": "a" * 40},
        }
        manifest = {
            "archive_id": "fixture-archive",
            "archived_provider_artifacts": {"77": artifact["digest"]},
            "archived_event_hashes": {},
            "new_checkpoint_hash": state["checkpoint"]["checkpoint_hash"],
            "checkpoint_sequence": state["sequence"],
        }
        self.assertEqual(_pending_events(state, [artifact], archived_ids=archived_artifact_ids(manifest)), [])

        class Reader:
            def list_recent_journal_artifacts(self, *args, **kwargs):
                return [artifact]
            def event(self, *args, **kwargs):
                raise AssertionError("archived event must not be re-opened")

        import state_journal.github_reducer as reducer_module
        original = reducer_module.restore_snapshot
        reducer_module.restore_snapshot = lambda *args, **kwargs: state
        try:
            candidate, receipt = reduce_from_provider(
                Reader(),
                since="2026-09-30T13:17:34Z",
                current_run="999",
                upload_steps={},
                explicit_checkpoint=state["checkpoint"],
                archive_manifest=manifest,
            )
            self.assertEqual(candidate, state)
            self.assertEqual(receipt["new_deliveries"], 0)
        finally:
            reducer_module.restore_snapshot = original

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
        self.assertIn("actions: write", candidate)
        self.assertIn("contents: write", candidate)
        self.assertIn("pull-requests: write", candidate)
        self.assertIn("workflow_run:", candidate)
        self.assertIn("- portfolio-state-reducer", candidate)
        self.assertIn("Journal capacity exceeded; do not drop evidence", candidate)
        self.assertIn("receipt.get(\"reason_type\") == \"JournalError\"", candidate)
        self.assertIn('BRANCH="factory/checkpoint-archive-${GITHUB_RUN_ID}"', candidate)
        self.assertIn('gh workflow run foundation-ci.yml --ref "$BRANCH"', candidate)
        self.assertNotIn('BRANCH="checkpoint/archive-${GITHUB_RUN_ID}"', candidate)


if __name__ == "__main__":
    unittest.main()
