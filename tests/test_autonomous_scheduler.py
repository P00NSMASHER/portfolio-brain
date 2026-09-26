import copy,os,tempfile,unittest
from unittest.mock import patch
from scheduler.autonomous_scheduler import _candidate,build_context,load_state,mark_work,schedule_cycle

class SchedulerTests(unittest.TestCase):
    def test_current_cycle_includes_research_hunt_integration_with_bounded_parallelism(self):
        state,receipt=schedule_cycle(load_state(),build_context(),at="2026-09-25T20:40:00Z")
        types={w["work_type"] for w in receipt["selected_work"]}
        self.assertTrue({"RESEARCH","HUNT","INTEGRATION"}<=types)
        self.assertGreaterEqual(len(state["work_items"]),3)
        self.assertLessEqual(len(state["work_items"]),8)

    def test_child_facing_external_validation_remains_blocked_while_commercial_is_queued(self):
        _,receipt=schedule_cycle(load_state(),build_context(),at="2026-09-25T20:40:00Z")
        self.assertEqual(len(receipt["blocked_work"]),2)
        self.assertTrue(all(w["state"]=="BLOCKED_APPROVAL" for w in receipt["blocked_work"]))
        self.assertTrue(all("CONSEQUENTIAL_CHILD_FACING_CHANGE" in w["approval_requirements"] for w in receipt["blocked_work"]))
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

    def test_kill_switch_environment_disables_cycle(self):
        with patch.dict(os.environ,{"PORTFOLIO_SCHEDULER_DISABLED":"true"}):
            state,r=schedule_cycle(load_state(),build_context(),at="2026-09-25T20:40:00Z")
        self.assertEqual(r["status"],"DISABLED")
        self.assertEqual(state["sequence"],0)

    def test_no_candidate_uses_act_authority(self):
        _,r=schedule_cycle(load_state(),build_context(),at="2026-09-25T20:40:00Z")
        self.assertTrue(all(w["required_authority"]!="ACT" for w in [*r["selected_work"],*r["blocked_work"]]))

if __name__=="__main__":unittest.main()
