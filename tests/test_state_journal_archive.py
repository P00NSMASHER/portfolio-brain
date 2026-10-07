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
from state_journal.checkpoint_archive import archive_due, _latest_attempt_snapshot_artifact
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

    def test_latest_attempt_snapshot_selects_newest_snapshot_before_current_receipt(self):
        run = {"id": 55, "run_attempt": 3}
        rows = [
            {"id": 101, "name": "portfolio-canonical-shadow-state", "expired": False, "created_at": "2026-10-07T06:27:17Z"},
            {"id": 102, "name": "portfolio-state-reducer-receipt-55-1", "expired": False, "created_at": "2026-10-07T06:27:18Z"},
            {"id": 201, "name": "portfolio-canonical-shadow-state", "expired": False, "created_at": "2026-10-07T06:35:23Z"},
            {"id": 202, "name": "portfolio-state-reducer-receipt-55-2", "expired": False, "created_at": "2026-10-07T06:35:24Z"},
            {"id": 301, "name": "portfolio-canonical-shadow-state", "expired": False, "created_at": "2026-10-07T06:39:50Z"},
            {"id": 302, "name": "portfolio-state-reducer-receipt-55-3", "expired": False, "created_at": "2026-10-07T06:39:51Z"},
        ]
        self.assertEqual(_latest_attempt_snapshot_artifact(run, rows)["id"], 301)

    def test_latest_attempt_snapshot_requires_current_attempt_receipt(self):
        run = {"id": 55, "run_attempt": 3}
        rows = [
            {"id": 101, "name": "portfolio-canonical-shadow-state", "expired": False, "created_at": "2026-10-07T06:27:17Z"},
            {"id": 102, "name": "portfolio-state-reducer-receipt-55-2", "expired": False, "created_at": "2026-10-07T06:27:18Z"},
        ]
        with self.assertRaisesRegex(Exception, "Latest reducer attempt receipt missing or ambiguous"):
            _latest_attempt_snapshot_artifact(run, rows)

    def test_latest_attempt_snapshot_rejects_snapshot_after_receipt(self):
        run = {"id": 55, "run_attempt": 3}
        rows = [
            {"id": 301, "name": "portfolio-canonical-shadow-state", "expired": False, "created_at": "2026-10-07T06:39:50Z"},
            {"id": 302, "name": "portfolio-state-reducer-receipt-55-3", "expired": False, "created_at": "2026-10-07T06:39:51Z"},
            {"id": 303, "name": "portfolio-canonical-shadow-state", "expired": False, "created_at": "2026-10-07T06:39:52Z"},
        ]
        with self.assertRaisesRegex(Exception, "Reducer snapshot appeared after latest attempt receipt"):
            _latest_attempt_snapshot_artifact(run, rows)

    def test_archive_high_water_precedes_hard_event_and_byte_limits(self):
        self.assertFalse(archive_due(69, 699, max_events=100, max_bytes=1000))
        self.assertTrue(archive_due(70, 1, max_events=100, max_bytes=1000))
        self.assertTrue(archive_due(0, 700, max_events=100, max_bytes=1000))

    def test_repeated_rollovers_keep_a_hash_pinned_archive_chain(self):
        first, _archive1, compacted1, _checkpoint1, _path1 = self.build(sequence=12)
        next_state = set_authority(make_snapshot(
            compacted1, [], sequence=first["checkpoint_sequence"], evidence={}
        ), mode="CANONICAL", production_authority=True)
        second, _archive2, compacted2, _checkpoint2, _path2 = build_rollover(
            next_state,
            source_reducer_run_id=902,
            source_artifact_id=903,
            source_head_sha="c" * 40,
            source_artifact_digest="sha256:" + "d" * 64,
            source_artifact_created_at="2026-09-30T14:17:34Z",
            previous_manifest=first,
        )
        validate_manifest(
            second, root=None, archived_state=next_state, checkpoint_doc=compacted2,
            previous_manifest=first,
        )
        self.assertEqual(second["previous_manifest_hash"], first["manifest_hash"])
        self.assertEqual(second["previous_manifest_path"], first["manifest_path"])
        self.assertEqual(second["previous_checkpoint_hash"], first["new_checkpoint_hash"])
        self.assertEqual(second["archived_checkpoint_hash"], first["new_checkpoint_hash"])
        self.assertEqual(compacted2["states"], compacted1["states"])

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
        self.assertIn('cron: "19 * * * *"', candidate)
        self.assertIn("actions: read", reducer)
        self.assertNotIn("actions: write", reducer)
        self.assertIn("portfolio-schedule-delivery", candidate)
        self.assertIn("Resolve reducer capacity source", candidate)
        self.assertIn("steps.reducer_source.outputs.run_id", candidate)
        self.assertIn("MANUAL_FORCE", candidate)
        self.assertIn('force = event_name == "push"', candidate)
        self.assertIn("python -m state_journal.checkpoint_archive", candidate)
        self.assertIn("--force", candidate)
        self.assertIn("checkpoint_force", candidate)
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
        workflow_header = candidate.split("jobs:", 1)[0]
        checkpoint_job = candidate.split("  checkpoint:", 1)[1].split("  acceptance-progress:", 1)[0]
        progress_job = candidate.split("  acceptance-progress:", 1)[1]
        self.assertNotIn("group: portfolio-state-checkpoint-candidate", workflow_header)
        self.assertIn("group: portfolio-state-checkpoint-candidate", checkpoint_job)
        self.assertNotIn("group: portfolio-state-checkpoint-candidate", progress_job)
        self.assertIn('BRANCH="factory/checkpoint-archive-${GITHUB_RUN_ID}"', candidate)
        self.assertIn("headRefOid", candidate)
        self.assertIn('gh workflow run foundation-ci.yml --ref "$CHECKPOINT_BRANCH"', candidate)
        self.assertIn("checks: read", candidate)
        self.assertIn("Resolve and validate active checkpoint candidate", candidate)
        self.assertIn("multiple open checkpoint recovery candidates", candidate)
        self.assertIn("merge_base_commit", candidate)
        self.assertIn('["gh", "pr", "close", str(candidate["number"])]', candidate)
        self.assertIn("stale_retired=true", candidate)
        self.assertIn("Wait for trusted exact-head verification", candidate)
        self.assertIn('row.get("name")=="portfolio-phase1-gate"', candidate)
        self.assertIn('row.get("app",{}).get("id")==5121826', candidate)
        self.assertIn("actions/workflows/foundation-ci.yml/runs?branch=", candidate)
        self.assertIn("event=workflow_dispatch", candidate)
        self.assertIn('row.get("head_sha")==sha', candidate)
        self.assertIn('row.get("status")!="completed"', candidate)
        self.assertIn('latest("portfolio-phase1-gate",5121826)', candidate)
        self.assertIn("Merge verified checkpoint candidate through branch protection", candidate)
        self.assertIn('-f sha="$CHECKPOINT_SHA"', candidate)
        self.assertIn("checkpoint candidate escaped protected path allowlist", candidate)
        self.assertIn('pr_detail.get("user")', candidate)
        self.assertIn('"github-actions[bot]"', candidate)
        self.assertNotIn('pr.get("author")', candidate)
        self.assertNotIn('BRANCH="checkpoint/archive-${GITHUB_RUN_ID}"', candidate)


if __name__ == "__main__":
    unittest.main()
