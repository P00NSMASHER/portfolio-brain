import json
import unittest
from pathlib import Path

from agents.heartbeat_state import heartbeat, seed_state
from state_journal.contracts import JournalError
from state_journal.reducer import checkpoint, make_snapshot, set_authority, validate_snapshot
from state_journal.github_reducer import restore_snapshot, select_latest_snapshot

ROOT = Path(__file__).resolve().parents[1]


class CanonicalCutoverPolicyTests(unittest.TestCase):
    def test_authority_promotion_preserves_projection_and_sequence(self):
        base = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
        shadow = make_snapshot(base, [], sequence=7, evidence={})
        ready = set_authority(shadow, mode="CANONICAL", production_authority=True)
        validate_snapshot(ready)
        self.assertEqual(ready["sequence"], shadow["sequence"])
        self.assertEqual(ready["projection"], shadow["projection"])
        self.assertEqual(ready["checkpoint"], shadow["checkpoint"])
        self.assertEqual(ready["mode"], "CANONICAL")
        self.assertTrue(ready["production_authority"])

    def test_same_sequence_authority_promotion_selects_canonical_without_data_choice(self):
        base = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
        shadow = make_snapshot(base, [], sequence=7, evidence={})
        canonical = set_authority(shadow, mode="CANONICAL", production_authority=True)
        selected = select_latest_snapshot([shadow, canonical])
        self.assertEqual(selected["state_hash"], canonical["state_hash"])
        self.assertEqual(selected["projection"], shadow["projection"])

    def test_same_sequence_real_payload_divergence_still_fails_closed(self):
        base = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
        shadow = make_snapshot(base, [], sequence=7, evidence={})
        canonical = set_authority(shadow, mode="CANONICAL", production_authority=True)
        changed = heartbeat(
            seed_state(), agent_ids=["AGT-HUNTER"], activity_kind="TEST",
            source_workflow="test", source_run_id="1", at="2026-09-29T19:00:00Z",
        )
        divergent_base = checkpoint({"heartbeat": changed}, {"heartbeat": "fixture:changed"})
        divergent = make_snapshot(divergent_base, [], sequence=7, evidence={})
        with self.assertRaisesRegex(JournalError, "Conflicting canonical snapshots"):
            select_latest_snapshot([canonical, divergent])


    def test_historical_snapshot_growth_does_not_deadlock_canonical_restore(self):
        base = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
        canonical = set_authority(make_snapshot(base, [], sequence=25, evidence={}),
                                  mode="CANONICAL", production_authority=True)
        artifacts = [{
            "id": index,
            "name": "portfolio-canonical-shadow-state",
            "expired": False,
            "created_at": f"2026-09-29T20:{index:02d}:00Z",
            "digest": "sha256:" + "0" * 64,
            "workflow_run": {"id": index, "head_branch": "main", "head_sha": "a" * 40},
        } for index in range(1, 26)]
        class Reader:
            def __init__(self):
                self.run_ids = []
                self.archives = []
            def get(self, suffix):
                self.run_ids.append(suffix)
                return {
                    "path": ".github/workflows/portfolio-state-reducer.yml",
                    "head_branch": "main", "head_sha": "a" * 40,
                    "status": "completed", "conclusion": "success",
                    "repository": {"full_name": "P00NSMASHER/portfolio-brain"},
                    "head_repository": {"full_name": "P00NSMASHER/portfolio-brain"},
                }
            def archive(self, artifact_id):
                self.archives.append(artifact_id)
                return b"fixture"
        reader = Reader()
        from unittest.mock import patch
        with patch("state_journal.github_reducer.artifact_digest"), \
             patch("state_journal.github_reducer.extract_json", return_value=canonical):
            restored = restore_snapshot(reader, artifacts, current_run="999")
        self.assertEqual(restored["state_hash"], canonical["state_hash"])
        self.assertEqual(reader.run_ids, ["/actions/runs/25", "/actions/runs/24"])
        self.assertEqual(reader.archives, [25, 24])

    def test_latest_snapshot_cannot_roll_sequence_backward(self):
        base = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
        newer = set_authority(make_snapshot(base, [], sequence=8, evidence={}),
                              mode="CANONICAL", production_authority=True)
        older = set_authority(make_snapshot(base, [], sequence=9, evidence={}),
                              mode="CANONICAL", production_authority=True)
        artifacts = [
            {"id": 2, "name": "portfolio-canonical-shadow-state", "expired": False,
             "created_at": "2026-09-29T20:02:00Z", "digest": "sha256:" + "0" * 64,
             "workflow_run": {"id": 2, "head_branch": "main", "head_sha": "b" * 40}},
            {"id": 1, "name": "portfolio-canonical-shadow-state", "expired": False,
             "created_at": "2026-09-29T20:01:00Z", "digest": "sha256:" + "0" * 64,
             "workflow_run": {"id": 1, "head_branch": "main", "head_sha": "a" * 40}},
        ]
        class Reader:
            def get(self, suffix):
                run_id = int(suffix.rsplit("/", 1)[1])
                return {
                    "path": ".github/workflows/portfolio-state-reducer.yml",
                    "head_branch": "main", "head_sha": ("b" if run_id == 2 else "a") * 40,
                    "status": "completed", "conclusion": "success",
                    "repository": {"full_name": "P00NSMASHER/portfolio-brain"},
                    "head_repository": {"full_name": "P00NSMASHER/portfolio-brain"},
                }
            def archive(self, artifact_id):
                return str(artifact_id).encode()
        from unittest.mock import patch
        with patch("state_journal.github_reducer.artifact_digest"), \
             patch("state_journal.github_reducer.extract_json",
                   side_effect=lambda raw, _member: newer if raw == b"2" else older), \
             self.assertRaisesRegex(JournalError, "sequence regressed"):
            restore_snapshot(Reader(), artifacts, current_run="999")

    def test_shadow_snapshot_cannot_claim_production_authority(self):
        base = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
        with self.assertRaises(JournalError):
            make_snapshot(base, [], sequence=0, evidence={}, mode="SHADOW", production_authority=True)

    def test_policy_switches_readers_and_cutover_together(self):
        policy = json.loads((ROOT / "state_journal/POLICY.json").read_text())
        self.assertEqual(policy["mode"], "CANONICAL")
        self.assertTrue(policy["canonical_snapshot_authorized"])
        self.assertTrue(policy["production_readers_enabled"])
        self.assertTrue(policy["production_cutover_complete"])
        self.assertFalse(policy["steps_3_to_8_started"])


if __name__ == "__main__":
    unittest.main()