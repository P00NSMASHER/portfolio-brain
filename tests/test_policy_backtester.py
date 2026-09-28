import unittest

from policy_replay.policy_backtester import PolicyReplayError, replay, validate_replay_receipt

def cycle(cid, *, duplicate=False, authority=0):
    return {
        "cycle_id": cid,
        "proposal_id": "P-" + cid,
        "project_id": "PRJ-001",
        "source_id": "SRC-A",
        "agent_id": "Hunter",
        "started_at": "2026-09-20T10:00:00+00:00",
        "completed_at": "2026-09-20T12:00:00+00:00",
        "result": "PASSED",
        "evidence_state": "VERIFIED",
        "cost_usd": 1.0,
        "model_calls": 1,
        "api_calls": 1,
        "github_jobs": 1,
        "duplicate_candidate": duplicate,
        "deferred": False,
        "authority_violations": authority,
        "estimated_cost_usd": 1.0,
        "planned_model_calls": 1,
        "planned_api_calls": 1,
        "planned_github_jobs": 1,
    }

class PolicyBacktesterTests(unittest.TestCase):
    def test_duplicate_suppression_is_shadow_only(self):
        receipt = replay([cycle("1"), cycle("2", duplicate=True), cycle("3")], {
            "candidate_id": "candidate-a",
            "suppress_duplicate_candidates": True,
        })
        validate_replay_receipt(receipt)
        self.assertEqual(receipt["candidate"]["cycle_count"], 2)
        self.assertEqual(receipt["candidate"]["wasted_duplicate_work"], 0)
        self.assertFalse(receipt["promotion_allowed"])
        self.assertTrue(receipt["forward_canary_required"])

    def test_result_field_cannot_be_used_as_candidate_policy(self):
        with self.assertRaises(PolicyReplayError):
            replay([cycle("1"), cycle("2"), cycle("3")], {
                "candidate_id": "bad",
                "result": "PASSED",
            })

    def test_replay_is_deterministic(self):
        cycles = [cycle("1"), cycle("2"), cycle("3")]
        candidate = {"candidate_id": "stable"}
        self.assertEqual(replay(cycles, candidate)["replay_hash"], replay(cycles, candidate)["replay_hash"])

if __name__ == "__main__":
    unittest.main()
