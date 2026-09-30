import unittest
from unittest.mock import patch

from hunting.autonomous_hunter import _materialize_repo_scout_hints,load_seed_state,run_cycle

class FakeProvider:
    def __init__(self):
        self.requests=0
        self.inspected_revisions=[]
    def repository_metadata(self,full_name):
        self.requests+=1
        return {"id":4242,"full_name":full_name,"default_branch":"main","private":False}
    def search(self,query):
        self.requests+=1
        return []
    def inspect_revision(self,candidate,revision):
        self.requests+=1
        self.inspected_revisions.append((candidate["full_name"],revision))
        return {"revision":revision,"tree_sha":"b"*40,"paths":["src/gameplay.lua","tests/gameplay_spec.lua","README.md"],"truncated":False}

class RepoScoutHunterHandoffTests(unittest.TestCase):
    def test_scout_hint_uses_existing_hunter_at_pinned_revision_and_project(self):
        provider=FakeProvider()
        receipt={
          "status":"PASS","authority_granted":False,"rights_granted":False,"value_verified":False,
          "hints":[{
            "status":"ELIGIBLE_FOR_EXISTING_HUNTER_INSPECTION","authority_class":"OBSERVE",
            "rights_granted":False,"value_verified":False,
            "repository_full_name":"public/gameplay","exact_revision":"a"*40,
            "project_ids":["PRJ-005"],"source_repository":"P00NSMASHER/github-value-hunt-ledger",
            "source_revision":"1"*40,"finding_identity":"sha256:"+"2"*64
          }]
        }
        hints=_materialize_repo_scout_hints(provider,receipt)
        strategy_id=next(iter(load_seed_state()["strategy_stats"]))
        objective={
          "objective_id":"HOBJ-SCOUT-TEST","gap_id":"HGAP-SCOUT-TEST","project_ids":["PRJ-005"],
          "strategy_id":strategy_id,"queries":["roblox gameplay"],"capability_key":"roblox-gameplay",
          "search_concepts":["gameplay"],"authority_class":"OBSERVE","exploration":False
        }
        with patch("hunting.autonomous_hunter.select_objectives",return_value=[objective]):
            _,cycle=run_cycle(load_seed_state(),provider,at="2026-09-30T14:00:00Z",intake_candidates=hints)
        self.assertEqual(provider.inspected_revisions,[("public/gameplay","a"*40)])
        self.assertEqual(len(cycle["findings"]),1)
        finding=cycle["findings"][0]
        self.assertEqual(finding["project_ids"],["PRJ-005"])
        self.assertEqual(finding["source"]["revision"],"a"*40)
        self.assertTrue(any(x.startswith("repo-scout:P00NSMASHER/github-value-hunt-ledger@") for x in finding["provenance_refs"]))
        self.assertEqual(finding["evidence_state"],"OBSERVED")
        self.assertFalse(finding["decision_trace"]["automatic_reuse_authority_granted"])

if __name__=="__main__":unittest.main()
