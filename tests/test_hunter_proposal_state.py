import copy
import unittest

from hunting.autonomous_hunter import load_seed_state, run_cycle
from hunting.proposal_state import HunterProposalStateError, build_proposal_state, validate_state


class BroadHighProvider:
    def __init__(self):
        self.requests=0
    def search(self,q):
        self.requests+=1
        return [
          {"id":1,"full_name":"public/high-a","default_branch":"main","private":False},
          {"id":2,"full_name":"public/high-b","default_branch":"main","private":False},
        ]
    def inspect(self,c):
        self.requests+=1
        revision=("a" if c["id"]==1 else "b")*40
        return {
          "revision":revision,
          "tree_sha":("c" if c["id"]==1 else "d")*40,
          "paths":[
            "src/government_contract_proposal_freight_audit_zoning_permits_claims_recovery_quiz_engine_data_lineage.py",
            "tests/test_government_contract_proposal_freight_audit_zoning_permits_claims_recovery_quiz_engine_data_lineage.py",
            "docs/government-contract-proposal-freight-audit-zoning-permits-claims-recovery-quiz-engine-data-lineage.md",
          ],
          "truncated":False,
        }


class HunterProposalStateTests(unittest.TestCase):
    def test_quality_gated_cycle_builds_valid_durable_proposal_state(self):
        hunter,receipt=run_cycle(load_seed_state(),BroadHighProvider(),at="2026-09-27T06:30:00Z")
        state=build_proposal_state(hunter,receipt)
        validate_state(state)
        self.assertEqual(state["sequence"],hunter["sequence"])
        self.assertEqual(state["cycle_id"],receipt["cycle_id"])
        self.assertEqual(state["cycle_receipt_hash"],receipt["receipt_hash"])
        self.assertEqual(len(state["proposals"]),len(receipt["experiment_proposals"]))
        self.assertEqual(len(state["findings"]),len(state["proposals"]))
        self.assertLessEqual(len(state["proposals"]),6)
        self.assertTrue(all(p["candidate_rank_band"] in {"MEDIUM","HIGH"} for p in state["proposals"]))
        self.assertTrue(all(f["capability_key"].startswith("capability-coverage:") for f in state["findings"]))
        self.assertEqual(state["rights_state"],"NOT_GRANTED_BY_DISCOVERY")
        self.assertEqual(state["authority_class"],"OBSERVE")

    def test_proposal_state_rejects_low_rank_promotion(self):
        hunter,receipt=run_cycle(load_seed_state(),BroadHighProvider(),at="2026-09-27T06:30:00Z")
        state=build_proposal_state(hunter,receipt)
        self.assertTrue(state["proposals"])
        bad=copy.deepcopy(state)
        bad["proposals"][0]["candidate_rank_band"]="LOW"
        bad["findings"][0]["rank_band"]="LOW"
        with self.assertRaises(HunterProposalStateError):
            validate_state(bad)

    def test_proposal_state_rejects_rights_upgrade(self):
        hunter,receipt=run_cycle(load_seed_state(),BroadHighProvider(),at="2026-09-27T06:30:00Z")
        state=build_proposal_state(hunter,receipt)
        bad=copy.deepcopy(state);bad["rights_state"]="LICENSED_FOR_REUSE"
        with self.assertRaises(HunterProposalStateError):
            validate_state(bad)


if __name__=="__main__":
    unittest.main()
