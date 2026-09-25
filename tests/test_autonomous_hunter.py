import copy, unittest
from hunting.autonomous_hunter import (
    HunterError, apply_verified_feedback, candidate_fingerprint, detect_gaps,
    load_seed_state, run_cycle, select_objectives, validate_state
)

class FakeProvider:
    def __init__(self,results=None,inspection=None):
        self.results=results if results is not None else [{"id":1,"full_name":"public/example","default_branch":"main","private":False}]
        self.inspection=inspection or {"revision":"a"*40,"tree_sha":"b"*40,"paths":["src/recoveryworks.py","tests/test_recoveryworks.py","docs/recoveryworks.md"],"truncated":False}
        self.requests=0
    def search(self,q):
        self.requests+=1;return copy.deepcopy(self.results)
    def inspect(self,c):
        self.requests+=1;return copy.deepcopy(self.inspection)

class HunterTests(unittest.TestCase):
    def test_structural_gaps_are_detected_without_claiming_missing_functionality(self):
        gaps=detect_gaps()
        self.assertGreaterEqual(len(gaps),1)
        self.assertTrue(all(g["need_type"]=="UNMAPPED_CAPABILITY_COVERAGE" for g in gaps))

    def test_objective_selection_reserves_exploration_budget(self):
        objectives=select_objectives(load_seed_state())
        self.assertTrue(any(x["exploration"] for x in objectives))
        self.assertTrue(all(x["authority_class"]=="OBSERVE" for x in objectives))

    def test_public_exact_revision_candidate_can_be_retained_and_proposed(self):
        state,receipt=run_cycle(load_seed_state(),FakeProvider(),at="2026-09-25T18:00:00Z")
        retained=[x for x in receipt["findings"] if x["disposition"]=="RETAIN"]
        self.assertGreaterEqual(len(retained),1)
        self.assertEqual(len(receipt["experiment_proposals"]),len(retained))
        self.assertTrue(all(x["evidence_state"]=="OBSERVED" for x in retained))
        self.assertTrue(all(x["source"]["revision"]=="a"*40 for x in retained))

    def test_readme_only_or_no_tests_is_rejected(self):
        provider=FakeProvider(inspection={"revision":"a"*40,"tree_sha":"b"*40,"paths":["src/core.py","README.md"],"truncated":False})
        _,receipt=run_cycle(load_seed_state(),provider,at="2026-09-25T18:00:00Z")
        self.assertTrue(receipt["findings"])
        self.assertTrue(all(x["disposition"]!="RETAIN" for x in receipt["findings"]))
        self.assertTrue(any(x["negative_reason"]=="NO_TEST_OR_REGRESSION_PATHS" for x in receipt["findings"]))

    def test_exact_revision_capability_deduplication(self):
        s=load_seed_state(); provider=FakeProvider()
        s,r1=run_cycle(s,provider,at="2026-09-25T18:00:00Z")
        s,r2=run_cycle(s,FakeProvider(),at="2026-09-25T19:00:00Z")
        self.assertTrue(any(x["disposition"]=="DUPLICATE" for x in r2["findings"]))

    def test_no_find_is_recorded_as_negative_knowledge(self):
        s,r=run_cycle(load_seed_state(),FakeProvider(results=[]),at="2026-09-25T18:00:00Z")
        self.assertEqual(r["findings"],[])
        self.assertGreater(len(s["negative_knowledge"]),0)

    def test_repeated_dead_end_is_suppressed(self):
        s=load_seed_state()
        for hour in range(2):
            s,_=run_cycle(s,FakeProvider(results=[]),at=f"2026-09-25T{18+hour:02d}:00:00Z")
        before=sum(x["queries"] for x in s["strategy_stats"].values())
        s,r=run_cycle(s,FakeProvider(results=[]),at="2026-09-25T20:00:00Z")
        after=sum(x["queries"] for x in s["strategy_stats"].values())
        self.assertGreaterEqual(after,before)
        self.assertTrue(any(x["reason_code"]=="REPEATED_DEAD_END_SUPPRESSED" for x in s["negative_knowledge"]))

    def test_private_candidate_fails_closed(self):
        with self.assertRaises(HunterError):
            run_cycle(load_seed_state(),FakeProvider(results=[{"id":1,"full_name":"x/y","default_branch":"main","private":True}]),at="2026-09-25T18:00:00Z")

    def test_unverified_feedback_cannot_train_strategy_value(self):
        s=load_seed_state()
        feedback={"feedback_id":"FB-1","strategy_id":"STRAT:capability-conjunction-search-claim-tracing","finding_id":"HFD-X","outcome_event_id":"EVT-X","evidence_state":"OBSERVED","value_realized":True}
        with self.assertRaises(HunterError):apply_verified_feedback(s,feedback)

    def test_verified_feedback_is_idempotent_and_value_specific(self):
        s=load_seed_state()
        feedback={"feedback_id":"FB-1","strategy_id":"STRAT:capability-conjunction-search-claim-tracing","finding_id":"HFD-X","outcome_event_id":"EVT-X","evidence_state":"VERIFIED","value_realized":True}
        apply_verified_feedback(s,feedback)
        self.assertEqual(s["strategy_stats"][feedback["strategy_id"]]["verified_value_outcomes"],1)
        with self.assertRaises(HunterError):apply_verified_feedback(s,feedback)

    def test_repository_count_has_no_direct_reward(self):
        from hunting.autonomous_hunter import load_policy
        self.assertEqual(load_policy()["repository_count_reward"],0)

    def test_state_is_bounded_and_valid(self):
        s=load_seed_state(); validate_state(s)
        self.assertEqual(s["sequence"],0)

if __name__=="__main__":unittest.main()
