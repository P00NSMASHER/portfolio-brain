import copy
import unittest

from hunting.autonomous_hunter import load_seed_state, run_cycle
from hunting.proposal_state import HunterProposalStateError, build_proposal_state, normalize_state, validate_state


class BroadHighProvider:
    def __init__(self,base_id=1):
        self.requests=0
        self.base_id=base_id
    def search(self,q):
        self.requests+=1
        return [
          {"id":self.base_id,"full_name":f"public/high-{self.base_id}","default_branch":"main","private":False},
          {"id":self.base_id+1,"full_name":f"public/high-{self.base_id+1}","default_branch":"main","private":False},
        ]
    def inspect(self,c):
        self.requests+=1
        revision=("abcdef0123456789"[c["id"]%16])*40
        return {
          "revision":revision,
          "tree_sha":("0123456789abcdef"[(c["id"]+3)%16])*40,
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
        self.assertEqual(set(state["origins"]),{p["proposal_id"] for p in state["proposals"]})
        self.assertTrue(all(o["first_cycle_id"]==receipt["cycle_id"] for o in state["origins"].values()))

    def test_prior_quality_proposals_survive_later_hunter_cycles(self):
        hunter=load_seed_state()
        hunter,r1=run_cycle(hunter,BroadHighProvider(1),at="2026-09-27T06:30:00Z")
        state1=build_proposal_state(hunter,r1)
        first_ids={p["proposal_id"] for p in state1["proposals"]}
        first_origins=copy.deepcopy(state1["origins"])
        self.assertTrue(first_ids)

        hunter,r2=run_cycle(hunter,BroadHighProvider(101),at="2026-09-27T12:30:00Z")
        state2=build_proposal_state(hunter,r2,prior_state=state1)
        ids2={p["proposal_id"] for p in state2["proposals"]}
        current_ids={p["proposal_id"] for p in r2["experiment_proposals"]}

        self.assertTrue(first_ids<=ids2)
        self.assertTrue(current_ids<=ids2)
        self.assertGreater(len(ids2),len(current_ids))
        for proposal_id in first_ids:
            self.assertEqual(
                state2["origins"][proposal_id]["first_cycle_id"],
                first_origins[proposal_id]["first_cycle_id"],
            )
            self.assertEqual(
                state2["origins"][proposal_id]["first_hunter_sequence"],
                first_origins[proposal_id]["first_hunter_sequence"],
            )
        validate_state(state2)

    def test_legacy_single_cycle_artifact_is_migrated_without_inventing_provenance(self):
        hunter,receipt=run_cycle(load_seed_state(),BroadHighProvider(),at="2026-09-27T06:30:00Z")
        current=build_proposal_state(hunter,receipt)
        legacy=copy.deepcopy(current)
        legacy.pop("origins")
        validate_state(legacy)
        normalized=normalize_state(legacy)
        self.assertEqual(set(normalized["origins"]),{p["proposal_id"] for p in legacy["proposals"]})
        for origin in normalized["origins"].values():
            self.assertEqual(origin["first_cycle_id"],legacy["cycle_id"])
            self.assertEqual(origin["last_cycle_id"],legacy["cycle_id"])
            self.assertEqual(origin["first_hunter_sequence"],legacy["sequence"])
            self.assertEqual(origin["last_hunter_sequence"],legacy["sequence"])
            self.assertEqual(origin["first_seen_at"],legacy["updated_at"])
            self.assertEqual(origin["last_seen_at"],legacy["updated_at"])

    def test_backlog_is_bounded_and_compacts_only_after_capacity(self):
        hunter=load_seed_state()
        backlog=None
        earliest=set()
        for cycle in range(18):
            hunter,receipt=run_cycle(
                hunter,
                BroadHighProvider(1000+cycle*10),
                at=f"2026-09-{(cycle%3)+20:02d}T{cycle%24:02d}:30:00Z",
            )
            backlog=build_proposal_state(hunter,receipt,prior_state=backlog)
            if cycle==0:
                earliest={p["proposal_id"] for p in backlog["proposals"]}
        self.assertIsNotNone(backlog)
        cap=__import__("hunting.autonomous_hunter",fromlist=["load_policy"]).load_policy()["proposal_persistence"]["max_backlog_proposals"]
        self.assertLessEqual(len(backlog["proposals"]),cap)
        self.assertEqual(len(backlog["proposals"]),len(backlog["findings"]))
        self.assertEqual(len(backlog["proposals"]),len(backlog["origins"]))
        self.assertFalse(earliest<={p["proposal_id"] for p in backlog["proposals"]})
        validate_state(backlog)

    def test_proposal_backlog_rejects_sequence_rollback(self):
        hunter=load_seed_state()
        hunter,r1=run_cycle(hunter,BroadHighProvider(1),at="2026-09-27T06:30:00Z")
        older_hunter=copy.deepcopy(hunter)
        prior=build_proposal_state(hunter,r1)
        hunter,r2=run_cycle(hunter,BroadHighProvider(101),at="2026-09-27T12:30:00Z")
        newer=build_proposal_state(hunter,r2,prior_state=prior)
        with self.assertRaises(HunterProposalStateError):
            build_proposal_state(older_hunter,r1,prior_state=newer)

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
