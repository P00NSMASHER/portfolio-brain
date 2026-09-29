import json
import unittest
from unittest.mock import patch
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

    def test_many_historical_snapshots_restore_from_newest_monotonic_pair_only(self):
        base = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
        artifacts = [
            {
                "id": i,
                "name": "portfolio-canonical-shadow-state",
                "expired": False,
                "created_at": f"2026-09-29T20:{i:02d}:00Z",
                "workflow_run": {"id": 1000 + i, "head_branch": "main", "head_sha": f"{i:040x}"},
            }
            for i in range(1, 26)
        ]
        def validate(_reader, artifact):
            return make_snapshot(
                base, [], sequence=artifact["id"], evidence={},
                mode="CANONICAL", production_authority=True,
            )
        with patch("state_journal.github_reducer._validated_snapshot", side_effect=validate) as checked:
            state = restore_snapshot(object(), artifacts, current_run="9999")
        self.assertEqual(state["sequence"], 25)
        self.assertEqual(checked.call_count, 2)

    def test_newest_snapshot_sequence_rollback_fails_closed(self):
        base = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
        artifacts = [
            {"id": 2, "name": "portfolio-canonical-shadow-state", "expired": False,
             "created_at": "2026-09-29T20:02:00Z", "workflow_run": {"id": 102, "head_branch": "main", "head_sha": "b"*40}},
            {"id": 1, "name": "portfolio-canonical-shadow-state", "expired": False,
             "created_at": "2026-09-29T20:01:00Z", "workflow_run": {"id": 101, "head_branch": "main", "head_sha": "a"*40}},
        ]
        newest = make_snapshot(base, [], sequence=8, evidence={}, mode="CANONICAL", production_authority=True)
        previous = make_snapshot(base, [], sequence=9, evidence={}, mode="CANONICAL", production_authority=True)
        with patch("state_journal.github_reducer._validated_snapshot", side_effect=[newest, previous]):
            with self.assertRaisesRegex(JournalError, "sequence rollback"):
                restore_snapshot(object(), artifacts, current_run="9999")

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