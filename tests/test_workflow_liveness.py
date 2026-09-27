import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from cost_governor.cost_governor import load_state
from operations.workflow_liveness import (
    WorkflowLivenessError,
    evaluate_target,
    load_policy,
    recover_overdue,
    validate_policy,
)

ROOT=Path(__file__).resolve().parents[1]
AT="2026-09-27T08:53:00Z"


def run(
    name,
    created_at,
    *,
    status="completed",
    conclusion="success",
    run_id=1,
    workflow_file=None,
    head_branch="main",
    event="schedule",
):
    return {
      "id":run_id,
      "name":name,
      "path":f".github/workflows/{workflow_file or name + '.yml'}",
      "head_branch":head_branch,
      "event":event,
      "created_at":created_at,
      "status":status,
      "conclusion":conclusion,
    }


class WorkflowLivenessTests(unittest.TestCase):
    def test_policy_is_bounded_and_targets_dispatchable_core_workflows(self):
        p=load_policy();validate_policy(p)
        self.assertLessEqual(p["max_dispatches_per_cycle"],2)
        self.assertLessEqual(p["max_history_pages"],5)
        self.assertEqual(p["authority_class"],"NONE")
        self.assertEqual(p["dispatch_authority_effect"],"NONE")
        self.assertEqual(p["hard_stop_behavior"],"NO_RECOVERY_DISPATCH")
        for target in p["targets"]:
            workflow=(ROOT/".github/workflows"/target["workflow_file"]).read_text()
            self.assertIn("workflow_dispatch:",workflow)

    def test_liveness_cost_preview_must_match_target_preflight(self):
        p=load_policy()
        p["targets"][0]["cost_job_id"]="unrelated-cheap-job"
        with self.assertRaisesRegex(WorkflowLivenessError,"cost scope is not governed"):
            validate_policy(p)

        p=load_policy()
        p["targets"][0]["estimated_minutes"]=1
        with self.assertRaisesRegex(WorkflowLivenessError,"cost preview drifted"):
            validate_policy(p)

    def test_overdue_scheduler_is_recovered_without_touching_recent_targets(self):
        p=load_policy()
        runs=[
          run("portfolio-autonomous-scheduler","2026-09-27T06:39:43Z",run_id=11),
          run("runtime-hourly-sync","2026-09-27T08:17:00Z",run_id=12),
          run("agent-heartbeat-sweep","2026-09-27T08:24:30Z",run_id=13),
          run("hunter-autonomous-cycle","2026-09-27T06:59:25Z",run_id=14),
          run("portfolio-notification-cycle","2026-09-27T06:07:00Z",run_id=15),
        ]
        dispatched=[]
        result=recover_overdue(
          load_state(),runs,
          dispatch=lambda workflow,branch:dispatched.append((workflow,branch)),
          at=AT,policy_data=p,
        )
        self.assertEqual(result["status"],"RECOVERY_DISPATCHED")
        self.assertEqual(dispatched,[("portfolio-autonomous-scheduler.yml","main")])
        scheduler=next(x for x in result["targets"] if x["workflow_name"]=="portfolio-autonomous-scheduler")
        self.assertEqual(scheduler["status"],"OVERDUE_MISSED_SCHEDULE")
        self.assertGreater(scheduler["age_minutes"],100)

    def test_queued_or_in_progress_target_is_never_duplicated(self):
        target=load_policy()["targets"][0]
        for status in ("queued","in_progress"):
            row=evaluate_target(
              target,
              [run(target["workflow_name"],"2026-09-27T08:50:00Z",status=status,conclusion=None)],
              at=AT,
              failure_retry_minutes=35,
            )
            self.assertEqual(row["status"],"HEALTHY_ACTIVE")
            self.assertFalse(row["dispatch_required"])

    def test_same_name_run_from_another_branch_cannot_mask_overdue_main(self):
        target=load_policy()["targets"][0]
        row=evaluate_target(
          target,
          [run(
            target["workflow_name"],"2026-09-27T08:50:00Z",
            status="in_progress",conclusion=None,head_branch="feature/spoof-liveness",
          )],
          at=AT,
          failure_retry_minutes=35,
        )
        self.assertEqual(row["status"],"OVERDUE_NO_HISTORY")
        self.assertTrue(row["dispatch_required"])

    def test_same_name_run_from_another_workflow_file_cannot_mask_target(self):
        target=load_policy()["targets"][0]
        row=evaluate_target(
          target,
          [run(
            target["workflow_name"],"2026-09-27T08:50:00Z",
            workflow_file="unrelated-spoof.yml",event="workflow_dispatch",
          )],
          at=AT,
          failure_retry_minutes=35,
        )
        self.assertEqual(row["status"],"OVERDUE_NO_HISTORY")
        self.assertTrue(row["dispatch_required"])

    def test_untrusted_event_cannot_mask_target(self):
        target=load_policy()["targets"][0]
        row=evaluate_target(
          target,
          [run(target["workflow_name"],"2026-09-27T08:50:00Z",event="pull_request")],
          at=AT,
          failure_retry_minutes=35,
        )
        self.assertEqual(row["status"],"OVERDUE_NO_HISTORY")
        self.assertTrue(row["dispatch_required"])

    def test_recent_failure_retries_only_after_failure_window(self):
        target=next(x for x in load_policy()["targets"] if x["workflow_name"]=="runtime-hourly-sync")
        recent=evaluate_target(
          target,[run("runtime-hourly-sync","2026-09-27T08:30:00Z",conclusion="failure")],
          at=AT,failure_retry_minutes=35,
        )
        old=evaluate_target(
          target,[run("runtime-hourly-sync","2026-09-27T08:10:00Z",conclusion="failure")],
          at=AT,failure_retry_minutes=35,
        )
        self.assertFalse(recent["dispatch_required"])
        self.assertEqual(old["status"],"OVERDUE_RECENT_FAILURE")
        self.assertTrue(old["dispatch_required"])

    def test_recovery_is_priority_ordered_and_bounded_to_two_dispatches(self):
        p=load_policy()
        dispatched=[]
        result=recover_overdue(
          load_state(),[],
          dispatch=lambda workflow,branch:dispatched.append((workflow,branch)),
          at=AT,policy_data=p,
        )
        self.assertEqual(len(dispatched),2)
        self.assertEqual(dispatched[0][0],"portfolio-autonomous-scheduler.yml")
        self.assertEqual(dispatched[1][0],"runtime-hourly-sync.yml")
        self.assertEqual(len(result["dispatches"]),2)

    def test_recovery_does_not_dispatch_target_already_blocked_by_its_cost_scope(self):
        p=load_policy()
        state=load_state()
        runtime_target=next(x for x in p["targets"] if x["workflow_name"]=="runtime-hourly-sync")
        # Fill only the runtime-worker job-start allocation. Other workflows retain
        # capacity, proving this is a target-specific block rather than a hard stop.
        for i in range(60):
            state["reservations"].append({
              "reservation_id":f"CRES-{i:020X}",
              "request_id":f"CGR-TEST-{i:04d}",
              "request_hash":"sha256:"+f"{i:064x}",
              "idempotency_key":f"github-job:prior-{i}:runtime:attempt:1",
              "retry_group":f"github-job:prior-{i}:runtime",
              "attempt":1,"resource_kind":"GITHUB_JOB","project_ids":["PRJ-000"],
              "provider_id":None,"model_id":None,"workflow_id":"runtime-worker","job_id":"runtime",
              "estimated_usage":{"cost_usd":0.0,"input_tokens":0,"output_tokens":0,"model_calls":0,"api_calls":0,"github_job_starts":1,"github_runner_minutes":5},
              "actual_usage":{"cost_usd":0.0,"input_tokens":0,"output_tokens":0,"model_calls":0,"api_calls":0,"github_job_starts":1,"github_runner_minutes":1},
              "status":"COMMITTED","created_at":"2026-09-27T01:00:00Z","expires_at":"2026-09-27T07:00:00Z","committed_at":"2026-09-27T01:01:00Z",
              "evidence_refs":[f"github-run:prior-{i}"]
            })
        runs=[
          run(target["workflow_name"],"2026-09-27T08:30:00Z",run_id=100+idx)
          for idx,target in enumerate(p["targets"])
          if target["workflow_name"]!="runtime-hourly-sync"
        ]
        dispatched=[]
        result=recover_overdue(
          state,runs,
          dispatch=lambda workflow,branch:dispatched.append((workflow,branch)),
          at=AT,policy_data=p,
        )
        runtime=next(x for x in result["targets"] if x["workflow_name"]==runtime_target["workflow_name"])
        self.assertEqual(result["status"],"HEALTHY")
        self.assertEqual(dispatched,[])
        self.assertEqual(runtime["status"],"BLOCKED_COST_PREFLIGHT")
        self.assertEqual(runtime["cost_gate_status"],"BLOCKED_BUDGET")
        self.assertFalse(runtime["dispatch_required"])

    def test_spend_kill_switch_blocks_all_recovery_dispatches(self):
        dispatched=[]
        with patch.dict(os.environ,{"PORTFOLIO_SPEND_DISABLED":"true"}):
            result=recover_overdue(
              load_state(),[],
              dispatch=lambda workflow,branch:dispatched.append((workflow,branch)),
              at=AT,
            )
        self.assertEqual(result["status"],"BLOCKED_SPEND_KILL_SWITCH")
        self.assertEqual(dispatched,[])
        self.assertFalse(result["authority_granted"])

    def test_watchdog_workflow_persists_liveness_receipt_and_keeps_actions_write_only(self):
        workflow=(ROOT/".github/workflows/portfolio-cost-watchdog.yml").read_text()
        self.assertIn("python -m operations.workflow_liveness",workflow)
        self.assertIn("portfolio-workflow-liveness",workflow)
        self.assertIn("actions: write",workflow)
        self.assertIn("contents: read",workflow)
        self.assertNotIn("contents: write",workflow)
        self.assertIn("workflow_run:",workflow)
        self.assertIn('workflows: ["agent-heartbeat-sweep"]',workflow)
        self.assertIn("types: [completed]",workflow)
        self.assertIn('branches: ["main"]',workflow)
        self.assertIn('operations/TRIGGER_WORKFLOW_LIVENESS',workflow)
        self.assertIn("\n  push:",workflow)


if __name__=="__main__":
    unittest.main()
