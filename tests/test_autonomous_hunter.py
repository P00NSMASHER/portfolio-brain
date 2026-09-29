import copy, unittest
from pathlib import Path
from hunting.autonomous_hunter import (
    CandidateInspectionError, GitHubPublicProvider, HunterError, _queries, candidate_fingerprint, classify_candidate, detect_gaps,
    load_policy, load_seed_state, load_strategies, rank_candidate, run_cycle, search_concepts_for_gap,
    select_objectives, strategy_priority_maturity, structural_inspection, validate_state
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
    def test_on_demand_hunter_trigger_is_isolated_and_rerunnable(self):
        root=Path(__file__).resolve().parents[1]
        workflow=(root/".github/workflows/hunter-autonomous-cycle.yml").read_text()
        runtime=(root/".github/workflows/runtime-event-observe.yml").read_text()
        trigger=(root/".github/triggers/hunter-autonomous-now.txt").read_text()
        self.assertIn('.github/triggers/hunter-autonomous-now.txt',workflow)
        self.assertGreater(workflow.index("concurrency:",workflow.index("hunt:")),workflow.index("hunt:"))
        self.assertIn('.github/triggers/hunter-autonomous-now.txt',runtime)
        self.assertIn('.github/workflows/hunter-autonomous-cycle.yml',runtime)
        self.assertIn("authority=OBSERVE",trigger)
        self.assertIn("model-calls=0",trigger)

    def test_structural_gaps_are_detected_without_claiming_missing_functionality(self):
        gaps=detect_gaps()
        self.assertGreaterEqual(len(gaps),1)
        self.assertTrue(all(g["need_type"]=="UNMAPPED_CAPABILITY_COVERAGE" for g in gaps))

    def test_objective_selection_reserves_exploration_budget(self):
        objectives=select_objectives(load_seed_state())
        self.assertTrue(any(x["exploration"] for x in objectives))
        self.assertTrue(all(x["authority_class"]=="OBSERVE" for x in objectives))

    def test_queries_use_reusable_concepts_instead_of_portfolio_brand_names(self):
        gaps=detect_gaps()
        capture=next(g for g in gaps if g["project_name"]=="CaptureBrief")
        strategy=next(x for x in load_strategies() if x["family"]=="EXACT_IMPLEMENTATION")
        queries=_queries(capture,strategy,load_seed_state())
        self.assertTrue(queries)
        self.assertTrue(all("capturebrief" not in q.casefold() for q in queries))
        self.assertTrue(any("government contract proposal" in q.casefold() or "rfp proposal" in q.casefold() for q in queries))
        self.assertIn("government contract proposal",search_concepts_for_gap(capture))

    def test_query_rotation_prefers_fresh_semantic_queries_after_dead_ends(self):
        state=load_seed_state()
        gap=next(g for g in detect_gaps() if g["project_name"]=="Freight Recovery")
        strategy=next(x for x in __import__("hunting.autonomous_hunter",fromlist=["load_strategies"]).load_strategies() if x["family"]=="EXACT_IMPLEMENTATION")
        first=_queries(gap,strategy,state)
        self.assertGreaterEqual(len(first),4)
        for q in first[:2]:
            state["negative_knowledge"].append({
              "gap_id":gap["gap_id"],"strategy_id":strategy["strategy_id"],
              "normalized_query":" ".join(q.casefold().split()),
              "query_fingerprint":"sha256:"+"0"*64,
              "reason_code":"NO_RETAINED_CANDIDATE","hits":2,
              "first_seen":"2026-09-25T18:00:00Z","last_seen":"2026-09-25T19:00:00Z"
            })
        state["sequence"]+=1
        second=_queries(gap,strategy,state)
        self.assertTrue(second)
        self.assertTrue(all(q not in first[:2] for q in second[:2]))

    def test_structural_ranking_uses_semantic_search_concepts_not_unique_slug(self):
        gap=next(g for g in detect_gaps() if g["project_name"]=="CaptureBrief")
        objective={
          "capability_key":gap["capability_key"],
          "search_concepts":search_concepts_for_gap(gap),
        }
        candidate={"id":1,"full_name":"public/proposal-engine"}
        inspection={
          "revision":"a"*40,"tree_sha":"b"*40,
          "paths":["src/proposal_engine.py","tests/test_proposal_engine.py","docs/government-contract-proposal.md"],
          "truncated":False,
        }
        structural=structural_inspection(candidate,inspection,objective)
        self.assertGreater(structural["source_keyword_hit_count"],0)
        self.assertGreater(structural["test_keyword_hit_count"],0)
        self.assertGreaterEqual(rank_candidate(structural)["score"],8)

    def test_public_exact_revision_candidate_can_be_retained_without_forcing_downstream_proposal(self):
        state,receipt=run_cycle(load_seed_state(),FakeProvider(),at="2026-09-25T18:00:00Z")
        retained=[x for x in receipt["findings"] if x["disposition"]=="RETAIN"]
        self.assertGreaterEqual(len(retained),1)
        self.assertLessEqual(len(receipt["experiment_proposals"]),len(retained))
        self.assertTrue(all(x["evidence_state"]=="OBSERVED" for x in retained))
        self.assertTrue(all(x["source"]["revision"]=="a"*40 for x in retained))
        self.assertTrue(all(x["proposal_eligibility"] in {"SELECTED","DEFER_LOW_RANK","DEFER_CYCLE_PROPOSAL_CAP"} for x in retained))

    def test_missing_tests_or_capability_signal_are_soft_ranking_signals_not_rejects(self):
        provider=FakeProvider(inspection={"revision":"a"*40,"tree_sha":"b"*40,"paths":["src/core.py","README.md"],"truncated":False})
        _,receipt=run_cycle(load_seed_state(),provider,at="2026-09-25T18:00:00Z")
        retained=[x for x in receipt["findings"] if x["disposition"]=="RETAIN"]
        self.assertTrue(retained)
        self.assertFalse(any(x["disposition"]=="REJECT" and x["negative_reason"]=="NO_TEST_OR_REGRESSION_PATHS" for x in receipt["findings"]))
        self.assertTrue(all("NO_TEST_OR_REGRESSION_PATHS" in x["ranking"]["soft_signal_codes"] for x in retained))
        self.assertTrue(any(x["ranking"]["band"]=="LOW" for x in retained))
        self.assertGreater(receipt["rejection_funnel"]["soft_signal_counts"].get("NO_TEST_OR_REGRESSION_PATHS",0),0)

    def test_no_implementation_paths_remains_a_hard_reject(self):
        provider=FakeProvider(inspection={"revision":"a"*40,"tree_sha":"b"*40,"paths":["README.md","docs/core.md","fixtures/core.json"],"truncated":False})
        _,receipt=run_cycle(load_seed_state(),provider,at="2026-09-25T18:00:00Z")
        self.assertTrue(receipt["findings"])
        self.assertTrue(all(x["disposition"]=="REJECT" for x in receipt["findings"]))
        self.assertTrue(all(x["negative_reason"]=="NO_IMPLEMENTATION_PATHS" for x in receipt["findings"]))
        self.assertTrue(all(x["decision_trace"]["hard_gate_status"]=="REJECT" for x in receipt["findings"]))

    def test_exact_revision_capability_deduplication(self):
        s=load_seed_state(); provider=FakeProvider()
        s,r1=run_cycle(s,provider,at="2026-09-25T18:00:00Z")
        s,r2=run_cycle(s,FakeProvider(),at="2026-09-25T19:00:00Z")
        self.assertTrue(any(x["disposition"]=="DUPLICATE" for x in r2["findings"]))

    def test_no_find_is_recorded_as_negative_knowledge(self):
        s,r=run_cycle(load_seed_state(),FakeProvider(results=[]),at="2026-09-25T18:00:00Z")
        self.assertEqual(r["findings"],[])
        self.assertGreater(len(s["negative_knowledge"]),0)

    def test_repeated_dead_end_is_suppressed_only_after_query_rotation_exhausts_fresh_options(self):
        s=load_seed_state()
        saw_suppressed=False
        for step in range(16):
            s,r=run_cycle(s,FakeProvider(results=[]),at=f"2026-09-25T{step:02d}:00:00Z")
            if r["rejection_funnel"]["queries_suppressed"]>0:
                saw_suppressed=True
                break
        self.assertTrue(saw_suppressed)
        self.assertTrue(any(x["reason_code"]=="REPEATED_DEAD_END_SUPPRESSED" for x in s["negative_knowledge"]))

    def test_candidate_inspection_unavailable_does_not_abort_cycle_or_train_dead_end(self):
        class UnavailableProvider(FakeProvider):
            def inspect(self,c):
                self.requests+=1
                raise CandidateInspectionError("synthetic 409")
        state,receipt=run_cycle(load_seed_state(),UnavailableProvider(),at="2026-09-25T18:00:00Z")
        funnel=receipt["rejection_funnel"]
        self.assertEqual(receipt["status"],"PASS")
        self.assertGreater(funnel["inspection_errors"],0)
        self.assertEqual(funnel["inspection_succeeded"],0)
        self.assertEqual(funnel["retained"],0)
        self.assertEqual(funnel["rejected"],0)
        self.assertTrue(funnel["candidate_accounting_reconciled"])
        self.assertTrue(funnel["disposition_accounting_reconciled"])
        self.assertIn("CANDIDATE_INSPECTION_UNAVAILABLE",funnel["inspection_error_reasons"])
        self.assertTrue(any(q["status"]=="EXECUTED_WITH_INSPECTION_ERRORS" for q in receipt["query_outcomes"]))
        self.assertFalse(any(x["reason_code"]=="NO_RETAINED_CANDIDATE" for x in state["negative_knowledge"]))

    def test_mixed_inspection_failure_and_success_remains_accounted(self):
        class MixedAvailabilityProvider(FakeProvider):
            def inspect(self,c):
                self.requests+=1
                if c["id"]==1:
                    raise CandidateInspectionError("synthetic unavailable")
                return copy.deepcopy(self.inspection)
        results=[
          {"id":1,"full_name":"public/unavailable","default_branch":"main","private":False},
          {"id":2,"full_name":"public/usable","default_branch":"main","private":False},
        ]
        _,receipt=run_cycle(load_seed_state(),MixedAvailabilityProvider(results=results),at="2026-09-25T18:00:00Z")
        funnel=receipt["rejection_funnel"]
        self.assertGreater(funnel["inspection_errors"],0)
        self.assertGreater(funnel["inspection_succeeded"],0)
        self.assertEqual(funnel["inspection_attempted"],funnel["inspection_succeeded"]+funnel["inspection_errors"])
        self.assertEqual(funnel["inspection_succeeded"],funnel["retained"]+funnel["duplicates"]+funnel["rejected"])

    def test_non_candidate_hunter_error_during_inspection_fails_closed(self):
        class ControlPlaneFailureProvider(FakeProvider):
            def inspect(self,c):
                self.requests+=1
                raise HunterError("Hunter API request budget exceeded")
        with self.assertRaises(HunterError):
            run_cycle(load_seed_state(),ControlPlaneFailureProvider(),at="2026-09-25T18:00:00Z")

    def test_repository_search_filters_empty_public_repositories_before_inspection(self):
        provider=GitHubPublicProvider(policy=load_policy())
        provider._get=lambda url:{
          "items":[
            {"id":1,"full_name":"public/empty","default_branch":"main","private":False,"size":0},
            {"id":2,"full_name":"public/code","default_branch":"main","private":False,"size":12},
            {"id":3,"full_name":"private/code","default_branch":"main","private":True,"size":12},
          ]
        }
        rows=provider.search("example")
        self.assertEqual([x["full_name"] for x in rows],["public/code"])

    def test_private_candidate_fails_closed(self):
        with self.assertRaises(HunterError):
            run_cycle(load_seed_state(),FakeProvider(results=[{"id":1,"full_name":"x/y","default_branch":"main","private":True}]),at="2026-09-25T18:00:00Z")

    def test_rejection_funnel_reconciles_every_inspected_candidate(self):
        _,receipt=run_cycle(load_seed_state(),FakeProvider(),at="2026-09-25T18:00:00Z")
        funnel=receipt["rejection_funnel"]
        self.assertTrue(funnel["candidate_accounting_reconciled"])
        self.assertTrue(funnel["disposition_accounting_reconciled"])
        self.assertEqual(
            funnel["inspection_attempted"],
            funnel["retained"]+funnel["duplicates"]+funnel["rejected"]+funnel["inspection_errors"]
        )
        self.assertEqual(
            funnel["inspection_succeeded"],
            funnel["retained"]+funnel["duplicates"]+funnel["rejected"]
        )
        self.assertEqual(
            funnel["normalized_candidates"],
            funnel["inspection_attempted"]+funnel["inspection_budget_deferred"]
        )
        self.assertEqual(len(receipt["query_outcomes"]),sum(len(x["queries"]) for x in receipt["objectives"]))

    def test_every_nonretained_finding_has_machine_readable_reason_and_trace(self):
        provider=FakeProvider(inspection={"revision":"a"*40,"tree_sha":"b"*40,"paths":["README.md","docs/core.md"],"truncated":False})
        _,receipt=run_cycle(load_seed_state(),provider,at="2026-09-25T18:00:00Z")
        nonretained=[x for x in receipt["findings"] if x["disposition"]!="RETAIN"]
        self.assertTrue(nonretained)
        self.assertTrue(all(x["negative_reason"] for x in nonretained))
        self.assertTrue(all(x["decision_trace"]["reason_code"]==x["negative_reason"] for x in nonretained))
        counted=sum(receipt["rejection_funnel"]["rejection_reasons"].values())
        self.assertEqual(counted,receipt["rejection_funnel"]["duplicates"]+receipt["rejection_funnel"]["rejected"]+receipt["rejection_funnel"]["queries_suppressed"])

    def test_zero_result_and_eventual_suppressed_queries_are_visible_in_funnel(self):
        s=load_seed_state()
        s,first=run_cycle(s,FakeProvider(results=[]),at="2026-09-25T00:00:00Z")
        self.assertGreater(first["rejection_funnel"]["queries_zero_results"],0)
        suppressed=None
        for step in range(1,16):
            s,receipt=run_cycle(s,FakeProvider(results=[]),at=f"2026-09-25T{step:02d}:00:00Z")
            if receipt["rejection_funnel"]["queries_suppressed"]>0:
                suppressed=receipt
                break
        self.assertIsNotNone(suppressed)
        self.assertTrue(any(x["status"]=="SUPPRESSED_REPEAT_DEAD_END" for x in suppressed["query_outcomes"]))
        self.assertIn("REPEATED_DEAD_END_SUPPRESSED",suppressed["rejection_funnel"]["rejection_reasons"])

    def test_inspection_budget_deferrals_are_counted_not_silently_dropped(self):
        results=[
          {"id":i,"full_name":f"public/example-{i}","default_branch":"main","private":False}
          for i in range(1,6)
        ]
        _,receipt=run_cycle(load_seed_state(),FakeProvider(results=results),at="2026-09-25T18:00:00Z")
        funnel=receipt["rejection_funnel"]
        self.assertGreater(funnel["inspection_budget_deferred"],0)
        self.assertTrue(funnel["candidate_accounting_reconciled"])
        self.assertEqual(
            funnel["normalized_candidates"],
            funnel["inspection_attempted"]+funnel["inspection_budget_deferred"]
        )

    def test_ranking_is_bounded_policy_driven_and_does_not_create_value_credit(self):
        policy=load_policy()
        high={
          "source_path_count":1,"test_path_count":1,"docs_path_count":1,"keyword_hit_count":3,
          "source_keyword_hit_count":1,"test_keyword_hit_count":1,"docs_keyword_hit_count":1,
          "tree_truncated":False
        }
        low={
          "source_path_count":1,"test_path_count":1,"docs_path_count":1,"keyword_hit_count":0,
          "source_keyword_hit_count":0,"test_keyword_hit_count":0,"docs_keyword_hit_count":0,
          "tree_truncated":False
        }
        high_rank=rank_candidate(high,policy); low_rank=rank_candidate(low,policy)
        self.assertEqual(high_rank["band"],"HIGH")
        self.assertEqual(high_rank["score"],policy["candidate_evaluation"]["ranking"]["max_score"])
        self.assertEqual(low_rank["band"],"LOW")
        self.assertLess(low_rank["score"],high_rank["score"])
        self.assertEqual(high_rank["value_credit_source"],"VERIFIED_OUTCOMES_ONLY")

    def test_low_rank_candidates_remain_observed_but_do_not_flood_experiment_proposals(self):
        objective=select_objectives(load_seed_state())[0]
        token=objective["capability_key"].replace("capability-coverage:","")
        class MixedProvider:
            def __init__(self):
                self.requests=0
            def search(self,q):
                self.requests+=1
                return [
                  {"id":1,"full_name":"public/high","default_branch":"main","private":False},
                  {"id":2,"full_name":"public/low","default_branch":"main","private":False},
                ]
            def inspect(self,c):
                self.requests+=1
                if c["id"]==1:
                    return {"revision":"a"*40,"tree_sha":"b"*40,"paths":[f"src/{token}.py",f"tests/test_{token}.py",f"docs/{token}.md"],"truncated":False}
                return {"revision":"c"*40,"tree_sha":"d"*40,"paths":["src/engine.py","tests/test_engine.py","README.md"],"truncated":False}
        _,receipt=run_cycle(load_seed_state(),MixedProvider(),at="2026-09-25T18:00:00Z")
        proposals=receipt["experiment_proposals"]
        self.assertTrue(proposals)
        self.assertTrue(all(p["candidate_rank_band"] in {"MEDIUM","HIGH"} for p in proposals))
        scores=[p["candidate_rank_score"] for p in proposals]
        self.assertEqual(scores,sorted(scores,reverse=True))
        self.assertEqual([p["candidate_rank_order"] for p in proposals],list(range(1,len(proposals)+1)))
        self.assertEqual(receipt["proposal_ordering"],"QUALITY_GATED_RANK_DESCENDING")
        lows=[x for x in receipt["findings"] if x["disposition"]=="RETAIN" and x["ranking"]["band"]=="LOW"]
        self.assertTrue(lows)
        self.assertTrue(all(x["experiment_proposal_id"] is None and x["proposal_eligibility"]=="DEFER_LOW_RANK" for x in lows))
        self.assertGreater(receipt["proposal_gate"]["deferred_low_rank"],0)

    def test_per_query_inspection_cap_prevents_early_objectives_from_starving_later_queries(self):
        results=[
          {"id":i,"full_name":f"public/example-{i}","default_branch":"main","private":False}
          for i in range(1,6)
        ]
        _,receipt=run_cycle(load_seed_state(),FakeProvider(results=results),at="2026-09-25T18:00:00Z")
        executed=[q for q in receipt["query_outcomes"] if q["status"]=="EXECUTED"]
        nonempty=[q for q in executed if q["raw_results"]>0]
        cap=load_policy()["budgets"]["max_candidates_inspected_per_query"]
        self.assertEqual(cap,2)
        self.assertTrue(nonempty)
        self.assertTrue(all(q["inspected"]==min(q["raw_results"],cap) for q in nonempty))
        self.assertTrue(all(q["inspected"]<=cap for q in executed))
        self.assertEqual(receipt["rejection_funnel"]["inspection_attempted"],min(
            load_policy()["budgets"]["max_candidates_inspected_per_cycle"],
            sum(min(q["raw_results"],cap) for q in executed)
        ))

    def test_proposal_cycle_cap_bounds_downstream_review_queue(self):
        token_path="src/government_contract_proposal_freight_audit_zoning_permits_claims_recovery_quiz_engine.py"
        test_path="tests/test_government_contract_proposal_freight_audit_zoning_permits_claims_recovery_quiz_engine.py"
        class BroadHighProvider:
            def __init__(self):
                self.requests=0
            def search(self,q):
                self.requests+=1
                return [
                  {"id":1,"full_name":"public/high-a","default_branch":"main","private":False},
                  {"id":2,"full_name":"public/high-b","default_branch":"main","private":False},
                  {"id":3,"full_name":"public/high-c","default_branch":"main","private":False},
                ]
            def inspect(self,c):
                self.requests+=1
                revision=chr(96+c["id"])*40
                return {"revision":revision,"tree_sha":"f"*40,"paths":[token_path,test_path,"docs/provenance-lineage.md"],"truncated":False}
        _,receipt=run_cycle(load_seed_state(),BroadHighProvider(),at="2026-09-25T18:00:00Z")
        gate=load_policy()["candidate_evaluation"]["proposal_gate"]
        self.assertEqual(len(receipt["experiment_proposals"]),gate["max_experiment_proposals_per_cycle"])
        self.assertEqual(receipt["proposal_gate"]["selected_proposals"],gate["max_experiment_proposals_per_cycle"])
        self.assertGreater(receipt["proposal_gate"]["deferred_cycle_cap"],0)
        self.assertTrue(all(p["candidate_rank_band"] in {"MEDIUM","HIGH"} for p in receipt["experiment_proposals"]))

    def test_ranking_band_accounting_covers_every_inspected_candidate(self):
        _,receipt=run_cycle(load_seed_state(),FakeProvider(),at="2026-09-25T18:00:00Z")
        bands=receipt["rejection_funnel"]["ranking_band_counts"]
        self.assertEqual(sum(bands.values()),receipt["rejection_funnel"]["inspection_attempted"])

    def test_single_verified_value_outcome_remains_warmup_and_does_not_reorder(self):
        state=load_seed_state()
        target="STRAT:fail-open-boundary-archaeology"
        cfg=load_policy()["learning"]
        state["strategy_stats"][target]["cycles"]=cfg["minimum_cycles_before_strategy_adjustment"]
        state["strategy_stats"][target]["inspected"]=cfg["minimum_inspections_before_strategy_adjustment"]
        state["strategy_stats"][target]["verified_value_outcomes"]=1
        maturity=strategy_priority_maturity(state,target)
        self.assertFalse(maturity["mature"])
        self.assertEqual(maturity["status"],"WARMUP")
        exploit=[x for x in select_objectives(state) if not x["exploration"]]
        self.assertNotEqual(exploit[0]["strategy_id"],target)

    def test_mature_verified_value_outcomes_reorder_exploit_strategy_priority(self):
        state=load_seed_state()
        target="STRAT:fail-open-boundary-archaeology"
        cfg=load_policy()["learning"]
        state["strategy_stats"][target]["cycles"]=cfg["minimum_cycles_before_strategy_adjustment"]
        state["strategy_stats"][target]["inspected"]=cfg["minimum_inspections_before_strategy_adjustment"]
        state["strategy_stats"][target]["verified_value_outcomes"]=cfg["minimum_verified_outcomes_before_strategy_priority"]
        maturity=strategy_priority_maturity(state,target)
        self.assertTrue(maturity["mature"])
        objectives=select_objectives(state)
        exploit=[x for x in objectives if not x["exploration"]]
        self.assertTrue(exploit)
        self.assertEqual(exploit[0]["strategy_id"],target)
        self.assertEqual(exploit[0]["strategy_verified_value_outcomes"],cfg["minimum_verified_outcomes_before_strategy_priority"])
        self.assertEqual(exploit[0]["strategy_selection_basis"],"MATURE_VERIFIED_OUTCOME_PRIORITY_THEN_CONFIGURED_ORDER")
        self.assertTrue(exploit[0]["strategy_priority_maturity"]["mature"])
        self.assertTrue(any(x["exploration"] for x in objectives))

    def test_repository_count_has_no_direct_reward(self):
        from hunting.autonomous_hunter import load_policy
        self.assertEqual(load_policy()["repository_count_reward"],0)

    def test_state_is_bounded_and_valid(self):
        s=load_seed_state(); validate_state(s)
        self.assertEqual(s["sequence"],0)

if __name__=="__main__":unittest.main()
