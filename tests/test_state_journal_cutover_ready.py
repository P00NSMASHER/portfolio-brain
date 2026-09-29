import json
import unittest
from pathlib import Path

from agents.heartbeat_state import seed_state
from state_journal.contracts import JournalError
from state_journal.reducer import checkpoint, make_snapshot, set_authority, validate_snapshot

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