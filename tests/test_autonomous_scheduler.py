import copy,os,tempfile,unittest
from unittest.mock import patch
from scheduler.autonomous_scheduler import _candidate,build_context,generate_candidates,load_state,mark_work,schedule_cycle

def proposal_state():
    proposal={
      "schema_version":"1.0.0","proposal_id":"HEXP-TEST-INBOX","finding_id":"HFD-TEST-INBOX",
      "gap_id":"HGAP-TEST","project_ids":["PRJ-002"],"candidate_rank_score":8,
      "candidate_rank_band":"HIGH","candidate_soft_signals":[],
      "hypothesis":"bounded","baseline":"none","success_condition":"verify","failure_condition":"reject",
      "evidence_requirements":["Exact source revision","License/rights verification"],
      "cost_boundary":"read only","rollback":"none","candidate_rank_order":1
    }
    finding={
      "finding_id":"HFD-TEST-INBOX","proposal_id":"HEXP-TEST-INBOX","gap_id":"HGAP-TEST",
      "capability_key":"capability-coverage:freight-audit","project_ids":["PRJ-002"],
      "strategy_id":"STRAT:capability-conjunction-search-claim-tracing",
      "candidate_fingerprint":"sha256:"+"1"*64,
      "repository_full_name":"public/freight-audit","repository_id":123,"revision":"a"*40,
      "public":True,"rank_score":8,"rank_band":"HIGH","soft_signals":[],
      "inspection":{"tree_sha":"b"*40,"tree_truncated":False,"path_count":3,"source_path_count":1,"test_path_count":1,"docs_path_count":1,"keyword_hit_count":2,"source_keyword_hit_count":1,"test_keyword_hit_count":1,"docs_keyword_hit_count":0,"sample_paths":["src/freight_audit.py","tests/test_freight_audit.py"]},
      "provenance_refs":["github:public/freight-audit@"+"a"*40]
    }
    return {
      "schema_version":"1.0.0","state_id":"portfolio-hunter-proposal-state","sequence":8,
      "updated_at":"2026-09-27T06:30:00Z","cycle_id":"hunt-test","cycle_receipt_hash":"sha256:"+"2"*64,
      "authority_class":"OBSERVE","rights_state":"NOT_GRANTED_BY_DISCOVERY",
      "proposals":[proposal],"findings":[finding]
    }

class SchedulerTests(unittest.TestCase):
    def test_quality_gated_hunter_proposal_enters_read_only_research_queue(self):
        ctx=build_context(hunter_proposal_state=proposal_state())
        candidates,_=generate_candidates(ctx)
        review=next(c for c in candidates if c["source_ref"]=="HEXP-TEST-INBOX")
        self.assertEqual(review["work_type"],"RESEARCH")
        self.assertEqual(review["assigned_agent_id"],"AGT-RESEARCHER")
        self.assertEqual(review["agent_goal_type"],"RESEARCH_EVIDENCE")
        self.assertEqual(review["required_authority"],"OBSERVE")
        self.assertIn("rights-state:NOT_GRANTED_BY_DISCOVERY",review["evidence_refs"])
        self.assertIn("github:public/freight-audit@"+"a"*40,review["evidence_refs"])

    def test_current_cycle_includes_research_hunt_integration_with_bounded_parallelism(self):
        state,receipt=schedule_cycle(load_state(),build_context(),at="2026-09-25T20:40:00Z")
        types={w["work_type"] for w in receipt["selected_work"]}
        self.assertTrue({"RESEARCH","HUNT","INTEGRATION"}<=types)
        self.assertGreaterEqual(len(state["work_items"]),3)
        self.assertLessEqual(len(state["work_items"]),8)

    def test_adult_only_education_validation_is_not_blocked(self):
        _,receipt=schedule_cycle(load_state(),build_context(),at="2026-09-25T20:40:00Z")
        self.assertEqual(receipt["blocked_work"],[])
        self.assertTrue(any(w["work_type"]=="EXPERIMENT" and w["assigned_agent_id"]=="AGT-COMMERCIAL-ANALYST" for w in receipt["selected_work"]))

    def test_second_cycle_suppresses_duplicates(self):
        state,r1=schedule_cycle(load_state(),build_context(),at="2026-09-25T20:40:00Z")
        state,r2=schedule_cycle(state,build_context(),at="2026-09-25T21:40:00Z")
        self.assertEqual(r2["selected_work"],[])
        self.assertGreater(len(r2["suppressed_duplicates"]),0)

    def test_per_agent_open_work_limit_is_two(self):
        _,r=schedule_cycle(load_state(),build_context(),at="2026-09-25T20:40:00Z")
        self.assertLessEqual(sum(1 for w in r["selected_work"] if w["assigned_agent_id"]=="AGT-PRODUCT-ANALYST"),2)

    def test_verification_precedes_discovery_when_factory_work_exists(self):
        ctx=build_context(factory_work_items=[{
          "work_id":"SFW-SYNTH-VERIFY","project_id":"PRJ-000","state":"VERIFYING","verifier_agent_id":"AGT-AUDITOR","commit_sha":"a"*40
        }])
        _,r=schedule_cycle(load_state(),ctx,at="2026-09-25T20:40:00Z")
        self.assertEqual(r["selected_work"][0]["work_type"],"VERIFICATION")
        self.assertEqual(r["selected_work"][0]["assigned_agent_id"],"AGT-AUDITOR")

    def test_bound_factory_verifier_is_not_substituted(self):
        ctx=build_context(factory_work_items=[{
          "work_id":"SFW-SYNTH-VERIFY","project_id":"PRJ-000","state":"VERIFYING","verifier_agent_id":"AGT-TESTER","commit_sha":"a"*40
        }])
        _,r=schedule_cycle(load_state(),ctx,at="2026-09-25T20:40:00Z")
        v=next(w for w in r["selected_work"] if w["work_type"]=="VERIFICATION")
        self.assertEqual((v["assigned_agent_id"],v["agent_goal_type"]),("AGT-TESTER","REGRESSION_VALIDATION"))

    def test_ready_repair_precedes_new_research(self):
        ctx=build_context()
        ctx["repair"]={"tasks":[{
          "state":"READY_FOR_REPAIR","repair_task_id":"RTASK-SYNTH","project_ids":["PRJ-000"],"evidence_refs":["repair:evidence"]
        }]}
        _,r=schedule_cycle(load_state(),ctx,at="2026-09-25T20:40:00Z")
        self.assertEqual(r["selected_work"][0]["work_type"],"REPAIR")

    def test_active_work_suppresses_duplicate(self):
        state=load_state()
        state,r=schedule_cycle(state,build_context(),at="2026-09-25T20:40:00Z")
        fp=r["selected_work"][0]["fingerprint"]
        state=mark_work(state,fp,"ACTIVE")
        _,r2=schedule_cycle(state,build_context(),at="2026-09-25T20:50:00Z")
        self.assertIn(fp,r2["suppressed_duplicates"])

    def test_expired_external_lease_is_hold_not_duplicate(self):
        state=load_state();state,r=schedule_cycle(state,build_context(),at="2026-09-25T20:40:00Z")
        w=state["work_items"][0];w["state"]="ACTIVE";w["lease_owner"]="worker-1";w["lease_generation"]=2;w["lease_expires_at"]=1.0
        _,r2=schedule_cycle(state,build_context(),at="2026-09-25T20:50:00Z")
        self.assertIn(w["fingerprint"],r2["stale_lease_holds"])
        self.assertNotIn(w["fingerprint"],[x["fingerprint"] for x in r2["selected_work"]])

    def test_completed_fingerprint_does_not_requeue_without_source_change(self):
        state=load_state();state,r=schedule_cycle(state,build_context(),at="2026-09-25T20:40:00Z")
        fp=r["selected_work"][0]["fingerprint"];state=mark_work(state,fp,"ACTIVE");state=mark_work(state,fp,"COMPLETE")
        _,r2=schedule_cycle(state,build_context(),at="2026-09-25T21:40:00Z")
        self.assertIn(fp,r2["suppressed_duplicates"])

    def test_cancelled_fingerprint_does_not_churn_back_into_queue(self):
        state=load_state();state,r=schedule_cycle(state,build_context(),at="2026-09-25T20:40:00Z")
        fp=r["selected_work"][0]["fingerprint"];state=mark_work(state,fp,"CANCELLED")
        self.assertIn(fp,state["completed_fingerprints"])
        _,r2=schedule_cycle(state,build_context(),at="2026-09-25T20:41:00Z")
        self.assertIn(fp,r2["suppressed_duplicates"])
        self.assertNotIn(fp,[w["fingerprint"] for w in r2["selected_work"]])

    def test_terminal_history_is_compacted_before_new_work_is_added(self):
        state=load_state();state,receipt=schedule_cycle(state,build_context(),at="2026-09-25T20:40:00Z")
        template=copy.deepcopy(receipt["selected_work"][0])
        state["work_items"]=[]
        for index in range(64):
            work=copy.deepcopy(template);work["fingerprint"]=f"sha256:terminal-{index:02d}";work["state"]="CANCELLED"
            state["work_items"].append(work)
        updated,next_receipt=schedule_cycle(state,build_context(),at="2026-09-25T21:40:00Z")
        self.assertGreater(len(next_receipt["selected_work"]),0)
        self.assertEqual(len(next_receipt["compacted_terminal_work"]),len(next_receipt["selected_work"]))
        self.assertEqual(len(updated["work_items"]),64)
        self.assertTrue(all(w["fingerprint"] not in next_receipt["compacted_terminal_work"] for w in updated["work_items"]))

    def test_selection_respects_remaining_open_queue_capacity(self):
        state=load_state();state,receipt=schedule_cycle(state,build_context(),at="2026-09-25T20:40:00Z")
        template=copy.deepcopy(receipt["selected_work"][0])
        state["work_items"]=[]
        for index in range(63):
            work=copy.deepcopy(template);work["fingerprint"]=f"sha256:active-{index:02d}";work["state"]="ACTIVE";work["assigned_agent_id"]="AGT-ENGINEER"
            state["work_items"].append(work)
        updated,next_receipt=schedule_cycle(state,build_context(),at="2026-09-25T21:40:00Z")
        self.assertEqual(len(next_receipt["selected_work"]),1)
        self.assertEqual(len(updated["work_items"]),64)
        self.assertEqual(next_receipt["compacted_terminal_work"],[])

    def test_kill_switch_environment_disables_cycle(self):
        with patch.dict(os.environ,{"PORTFOLIO_SCHEDULER_DISABLED":"true"}):
            state,r=schedule_cycle(load_state(),build_context(),at="2026-09-25T20:40:00Z")
        self.assertEqual(r["status"],"DISABLED")
        self.assertEqual(state["sequence"],0)

    def test_no_candidate_uses_act_authority(self):
        _,r=schedule_cycle(load_state(),build_context(),at="2026-09-25T20:40:00Z")
        self.assertTrue(all(w["required_authority"]!="ACT" for w in [*r["selected_work"],*r["blocked_work"]]))

if __name__=="__main__":unittest.main()
