import json
import unittest
from pathlib import Path

from agents.heartbeat_state import seed_state
from state_journal.contracts import JournalError
from state_journal.reducer import checkpoint, make_snapshot, set_authority, validate_snapshot

ROOT = Path(__file__).resolve().parents[1]


class CanonicalReadyTests(unittest.TestCase):
    def test_authority_promotion_preserves_projection_and_sequence(self):
        base = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
        shadow = make_snapshot(base, [], sequence=7, evidence={})
        ready = set_authority(shadow, mode="CANONICAL", production_authority=True)
        validate_snapshot(ready)
        self.assertEqual(ready["sequence"], shadow["sequence"])
        self.assertEqual(ready["projection"], shadow["projection"])
        self.assertEqual(ready["checkpoint"], shadow["checkpoint"])
        self.assertEqual(ready["events"], shadow["events"])
        self.assertEqual(ready["evidence"], shadow["evidence"])
        self.assertEqual(ready["mode"], "CANONICAL")
        self.assertTrue(ready["production_authority"])
    def test_shadow_snapshot_cannot_claim_production_authority(self):
        base = checkpoint({"heartbeat": seed_state()}, {"heartbeat": "fixture:heartbeat"})
        with self.assertRaises(JournalError):
            make_snapshot(base, [], sequence=0, evidence={},
                          mode="SHADOW", production_authority=True)

    def test_policy_is_ready_but_readers_are_not_switched(self):
        policy = json.loads((ROOT / "state_journal/POLICY.json").read_text())
        self.assertEqual(policy["mode"], "CANONICAL_READY")
        self.assertTrue(policy["canonical_snapshot_authorized"])
        self.assertFalse(policy["production_readers_enabled"])
        self.assertFalse(policy["production_cutover_complete"])
        self.assertFalse(policy["steps_3_to_8_started"])

    def test_reducer_has_one_shot_protected_ready_trigger(self):
        workflow = (ROOT / ".github/workflows/portfolio-state-reducer.yml").read_text()
        self.assertIn('branches: ["main"]', workflow)
        self.assertIn('.github/triggers/step2-canonical-ready.txt', workflow)
        self.assertIn('group: portfolio-state-writer-v1', workflow)
        self.assertIn('cancel-in-progress: false', workflow)
        self.assertIn('queue: max', workflow)
        self.assertNotIn('contents: write', workflow)


if __name__ == "__main__":
    unittest.main()