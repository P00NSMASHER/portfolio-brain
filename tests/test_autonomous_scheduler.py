import copy,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from scheduler.autonomous_scheduler import _candidate,build_context,generate_candidates,is_hunter_proposal_continuation,load_state,mark_work,schedule_cycle
from learning.continuous_learning import rebuild_from_ledger

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
      "updated_at":"2026-09-27T06:30:00Z","cycle_id":"hunt-latest","cycle_receipt_hash":"sha256:"+"2"*64,
      "authority_class":"OBSERVE","rights_state":"OPERATOR_ASSUMED",
      "proposals":[proposal],"findings":[finding],
      "origins":{
        "HEXP-TEST-INBOX":{
          "first_cycle_id":"hunt-origin-test",
          "first_cycle_receipt_hash":"sha256:"+"3"*64,
          "first_seen_at":"2026-09-27T04:30:00Z",
          "first_hunter_sequence":4,
          "last_cycle_id":"hunt-latest",
          "last_cycle_receipt_hash":"sha256:"+"2"*64,
          "last_seen_at":"2026-09-27T06:30:00Z",
          "last_hunter_sequence":8
        }
      }
    }

class SchedulerTests(unittest.TestCase):
    def test_scheduler_stays_out_of_push_fanout_and_keeps_rerunnable_job_concurrency(self):
        root=Path(__file__).resolve().parents[1]
        workflow=(root/".github/workflows/portfolio-autonomous-scheduler.yml").read_text()
        runtime=(root/".github/workflows/runtime-event-observe.yml").read_text()
        self.assertNotIn("\n  push:",workflow)
        self.assertGreater(workflow.index("concurrency:",workflow.index("  schedule:")),workflow.index("  schedule:"))
        self.assertIn('.github/workflows/portfolio-autonomous-scheduler.yml',runtime)

    def test_quality_gated_hunter_proposal_enters_read_only_research_queue(self):
        ctx=build_context(hunter_proposal_state=proposal_state())
        candidates,_=generate_candidates(ctx)
        review=next(c for c in candidates if c["source_ref"]=="HEXP-TEST-INBOX")
        self.assertEqual(review["work_type"],"RESEARCH")
        self.assertEqual(review["assigned_agent_id"],"AGT-RESEARCHER")
        self.assertEqual(review["agent_goal_type"],"RESEARCH_EVIDENCE")
        self.assertEqual(review["required_authority"],"OBSERVE")
        self.assertEqual(review["continuation_class"],"CONTINUATION")
        self.assertIn("rights-state:OPERATOR_ASSUMED",review["evidence_refs"])
        self.assertIn("github:public/freight-audit@"+"a"*40,review["evidence_refs"])
        self.assertIn("hunter-origin-cycle:hunt-origin-test",review["evidence_refs"])
        self.assertIn("hunter-origin-receipt:sha256:"+"3"*64,review["evidence_refs"])
        self.assertNotIn("hunter-origin-cycle:hunt-latest",review["evidence_refs"])


    def test_hunter_proposal_review_continuation_gets_researcher_slot_before_new_research(self):
        ctx=build_context(hunter_proposal_state=proposal_state())
        candidates,_=generate_candidates(ctx)
        proposal=next(x for x in candidates if x["source_ref"]=="HEXP-TEST-INBOX")
        _,receipt=schedule_cycle(load_state(),ctx,at="2026-09-27T09:20:00Z")
        self.assertFalse(any(w["source_ref"]=="HEXP-TEST-INBOX" for w in receipt["selected_work"]))
        self.assertIn(proposal["fingerprint"],receipt["suppressed_no_external_milestone"])
        self.assertTrue(all(w["external_milestone"] for w in receipt["selected_work"]))

    def test_filtered_continuation_scheduler_selects_only_hunter_proposal_review(self):
        ctx=build_context(hunter_proposal_state=proposal_state())
        candidates,_=generate_candidates(ctx)
        proposal=next(x for x in candidates if x["source_ref"]=="HEXP-TEST-INBOX")
        _,receipt=schedule_cycle(
            load_state(),ctx,at="2026-09-27T09:20:00Z",
            candidate_filter=is_hunter_proposal_continuation,
            max_new_items=1,
        )
        self.assertEqual(receipt["selected_work"],[])
        self.assertIn(proposal["fingerprint"],receipt["suppressed_no_external_milestone"])
    def test_filtered_continuation_scheduler_cannot_widen_cycle_limit(self):
        ctx=build_context(hunter_proposal_state=proposal_state())
        with self.assertRaises(Exception):
            schedule_cycle(
                load_state(),ctx,at="2026-09-27T09:20:00Z",
                candidate_filter=is_hunter_proposal_continuation,
                max_new_items=9,
            )

    def test_same_cycle_continuation_step_precedes_review_persistence(self):
        root=Path(__file__).resolve().parents[1]
        workflow=(root/".github/workflows/portfolio-autonomous-scheduler.yml").read_text()
        self.assertIn("scheduler.same_cycle_continuation",workflow)
        self.assertIn("--max-items 8",workflow)
        self.assertLess(
            workflow.index("scheduler.same_cycle_continuation"),
            workflow.index("python -m hunting.proposal_review_state"),
        )

    def test_proposal_backlog_priority_prefers_rank_then_first_seen_fifo(self):
        state=proposal_state()
        high=copy.deepcopy(state["proposals"][0])
        high["proposal_id"]="HEXP-HIGH-NEW"
        high["finding_id"]="HFD-HIGH-NEW"
        high["candidate_rank_score"]=9
        high["candidate_rank_order"]=1
        high_finding=copy.deepcopy(state["findings"][0])
        high_finding["proposal_id"]=high["proposal_id"]
        high_finding["finding_id"]=high["finding_id"]
        high_finding["rank_score"]=9
        high_finding["repository_id"]=124
        high_finding["repository_full_name"]="public/high-new"
        high_finding["revision"]="c"*40
        high_finding["provenance_refs"]=["github:public/high-new@"+"c"*40]
        same=copy.deepcopy(state["proposals"][0])
        same["proposal_id"]="HEXP-SAME-NEW"
        same["finding_id"]="HFD-SAME-NEW"
        same["candidate_rank_order"]=1
        same_finding=copy.deepcopy(state["findings"][0])
        same_finding["proposal_id"]=same["proposal_id"]
        same_finding["finding_id"]=same["finding_id"]
        same_finding["repository_id"]=125
        same_finding["repository_full_name"]="public/same-new"
        same_finding["revision"]="d"*40
        same_finding["provenance_refs"]=["github:public/same-new@"+"d"*40]
        state["proposals"].extend([high,same])
        state["findings"].extend([high_finding,same_finding])
        state["origins"][high["proposal_id"]]={
          "first_cycle_id":"hunt-high","first_cycle_receipt_hash":"sha256:"+"4"*64,
          "first_seen_at":"2026-09-27T06:00:00Z","first_hunter_sequence":7,
          "last_cycle_id":"hunt-high","last_cycle_receipt_hash":"sha256:"+"4"*64,
          "last_seen_at":"2026-09-27T06:00:00Z","last_hunter_sequence":7
        }
        state["origins"][same["proposal_id"]]={
          "first_cycle_id":"hunt-same","first_cycle_receipt_hash":"sha256:"+"5"*64,
          "first_seen_at":"2026-09-27T05:30:00Z","first_hunter_sequence":6,
          "last_cycle_id":"hunt-same","last_cycle_receipt_hash":"sha256:"+"5"*64,
          "last_seen_at":"2026-09-27T05:30:00Z","last_hunter_sequence":6
        }
        ctx=build_context(hunter_proposal_state=state)
        candidates,_=generate_candidates(ctx)
        reviews={c["source_ref"]:c for c in candidates if c["source_ref"].startswith("HEXP-")}
        self.assertLess(reviews["HEXP-HIGH-NEW"]["source_rank_order"],reviews["HEXP-TEST-INBOX"]["source_rank_order"])
        self.assertLess(reviews["HEXP-TEST-INBOX"]["source_rank_order"],reviews["HEXP-SAME-NEW"]["source_rank_order"])


    def test_subsequent_work_selection_consumes_fresh_learning_count(self):
        empty=rebuild_from_ledger()
        zero_ctx=build_context(learning_state=empty)
        self.assertIn(
            "UNC-LEARNING-PRJ-000",
            {row["uncertainty_id"] for row in zero_ctx["uncertainty"]["candidates"]},
        )
        learned=copy.deepcopy(empty)
        learned["source_observation_count"]=3
        learned_ctx=build_context(learning_state=learned)
        self.assertNotIn(
            "UNC-LEARNING-PRJ-000",
            {row["uncertainty_id"] for row in learned_ctx["uncertainty"]["candidates"]},
        )

    def test_current_cycle_includes_research_hunt_integration_with_bounded_parallelism(self):
        state,receipt=schedule_cycle(load_state(),build_context(),at="2026-09-25T20:40:00Z")
        types={w["work_type"] for w in receipt["selected_work"]}
        self.assertEqual(types,{"EXPERIMENT","TEST"})
        self.assertGreaterEqual(len(state["work_items"]),1)
        self.assertLessEqual(len(state["work_items"]),8)
        self.assertTrue(all(w["external_milestone"] in {"PUBLISH_PRODUCT","VALIDATE_DEMAND"} for w in receipt["selected_work"]))
        self.assertTrue(receipt["suppressed_no_external_milestone"])

    def test_adult_only_education_validation_is_not_blocked(self):
        _,receipt=schedule_cycle(load_state(),build_context(),at="2026-09-25T20:40:00Z")
        owner=[w for w in receipt["blocked_work"] if w["source_ref"].startswith("OACT-")]
        self.assertEqual(len(owner),1)
        self.assertEqual(owner[0]["external_milestone"],"PUBLISH_PRODUCT")
        self.assertTrue(any(
            w["work_type"]=="EXPERIMENT"
            and w["assigned_agent_id"]=="AGT-COMMERCIAL-ANALYST"
            and w["external_milestone"]=="VALIDATE_DEMAND"
            for w in receipt["selected_work"]
        ))
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
        raw,_=generate_candidates(ctx)
        verification=next(x for x in raw if x["work_type"]=="VERIFICATION")
        _,r=schedule_cycle(load_state(),ctx,at="2026-09-25T20:40:00Z")
        self.assertFalse(any(w["work_type"]=="VERIFICATION" for w in r["selected_work"]))
        self.assertIn(verification["fingerprint"],r["suppressed_no_external_milestone"])

    def test_bound_factory_verifier_is_not_substituted(self):
        ctx=build_context(factory_work_items=[{
          "work_id":"SFW-SYNTH-VERIFY","project_id":"PRJ-000","state":"VERIFYING","verifier_agent_id":"AGT-TESTER","commit_sha":"a"*40
        }])
        candidates,_=generate_candidates(ctx)
        v=next(w for w in candidates if w["work_type"]=="VERIFICATION")
        self.assertEqual((v["assigned_agent_id"],v["agent_goal_type"]),("AGT-TESTER","REGRESSION_VALIDATION"))
        _,r=schedule_cycle(load_state(),ctx,at="2026-09-25T20:40:00Z")
        self.assertIn(v["fingerprint"],r["suppressed_no_external_milestone"])

    def test_ready_repair_precedes_new_research(self):
        ctx=build_context()
        ctx["repair"]={"tasks":[{
          "state":"READY_FOR_REPAIR","repair_task_id":"RTASK-SYNTH","project_ids":["PRJ-000"],
          "evidence_refs":["repair:evidence","external-milestone:PUBLISH_PRODUCT"]
        }]}
        _,r=schedule_cycle(load_state(),ctx,at="2026-09-25T20:40:00Z")
        repair=next(w for w in r["selected_work"] if w["work_type"]=="REPAIR")
        self.assertEqual(repair["external_milestone"],"PUBLISH_PRODUCT")
        self.assertEqual(repair["value_lane"],"INTERNAL_BLOCKER")
        self.assertNotEqual(r["selected_work"][0]["work_type"],"REPAIR")
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
