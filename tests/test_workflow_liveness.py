import hashlib
import io
import json
import os
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import patch

from cost_governor.cost_governor import commit_reservation, load_state, reserve_model_execution, zero_usage
from operations.workflow_liveness import (
    WorkflowLivenessError,
    _download_artifact_archive,
    evaluate_target,
    fetch_run_work_proof,
    load_policy,
    recover_overdue,
    validate_policy,
    verify_work_proof,
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


def receipt(body):
    value=dict(body)
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    value["receipt_hash"]="sha256:"+hashlib.sha256(raw).hexdigest()
    return value


def scheduler_proof_doc():
    return receipt({
      "schema_version":"1.0.0",
      "cycle_id":"wexec-1234567890abcdef12345678",
      "finished_at":"2026-09-27T08:50:00Z",
      "attempted_count":3,
      "completed_count":2,
      "deferred_count":1,
      "remaining_queued_count":0,
      "authority_granted":False,
    })


class WorkflowLivenessTests(unittest.TestCase):

    def test_policy_is_bounded_and_targets_dispatchable_core_workflows(self):
        p=load_policy();validate_policy(p)
        self.assertLessEqual(p["max_dispatches_per_cycle"],2)
        self.assertLessEqual(p["max_history_pages"],5)
        self.assertEqual(p["authority_class"],"NONE")
        self.assertEqual(p["dispatch_authority_effect"],"NONE")
        self.assertEqual(p["hard_stop_behavior"],"NONPAID_RECOVERY_CONTINUES")
        self.assertGreaterEqual(p["unverified_work_retry_after_minutes"],10)
        self.assertLessEqual(p["unverified_work_retry_after_minutes"],120)
        self.assertTrue(all(t["admission_domain"]=="WORKLOAD" for t in p["targets"]))
        runtime_sync=next(t for t in p["targets"] if t["workflow_name"]=="runtime-hourly-sync")
        self.assertEqual(runtime_sync["admission_workflow_id"],"runtime-worker")
        self.assertEqual(runtime_sync["admission_job_id"],"runtime-sync")
        for target in p["targets"]:
            workflow=(ROOT/".github/workflows"/target["workflow_file"]).read_text()
            if "uses: ./.github/workflows/runtime-worker.yml" in workflow:
                workflow+="\n"+(ROOT/".github/workflows/runtime-worker.yml").read_text()
            self.assertIn("workflow_dispatch:",(ROOT/".github/workflows"/target["workflow_file"]).read_text())
            self.assertIn("proof_artifact_name",target)
            self.assertIn("proof_member",target)
            self.assertIn("proof_kind",target)
            self.assertIn(f'name: {target["proof_artifact_name"]}',workflow)


    def test_liveness_admission_preview_must_match_target_controls(self):
        p=load_policy()
        p["targets"][0]["admission_job_id"]="unrelated-job"
        with self.assertRaisesRegex(WorkflowLivenessError,"admission scope is not configured"):
            validate_policy(p)

        p=load_policy()
        p["targets"][0]["estimated_minutes"]=6
        with self.assertRaisesRegex(WorkflowLivenessError,"target estimate invalid"):
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
        proofs={
          12:{"status":"VERIFIED_WORK","reason":"TEST_PROOF","metrics":{},"authority_granted":False},
          13:{"status":"VERIFIED_WORK","reason":"TEST_PROOF","metrics":{},"authority_granted":False},
          14:{"status":"VERIFIED_WORK","reason":"TEST_PROOF","metrics":{},"authority_granted":False},
          15:{"status":"VERIFIED_WORK","reason":"TEST_PROOF","metrics":{},"authority_granted":False},
        }
        result=recover_overdue(
          load_state(),runs,
          dispatch=lambda workflow,branch:dispatched.append((workflow,branch)),
          at=AT,policy_data=p,run_proofs=proofs,
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

    def test_successful_run_does_not_prove_governed_work(self):
        target=load_policy()["targets"][0]
        row=evaluate_target(target,[run(target["workflow_name"],"2026-09-27T08:50:00Z")],at=AT,failure_retry_minutes=35)
        self.assertEqual(row["status"],"RECENT_RUN_UNVERIFIED_WORK")
        self.assertFalse(row["dispatch_required"])

    def test_stale_success_without_work_proof_becomes_recoverable(self):
        target=load_policy()["targets"][0]
        row=evaluate_target(
          target,[run(target["workflow_name"],"2026-09-27T08:10:00Z",run_id=76)],
          at=AT,failure_retry_minutes=35,unverified_retry_minutes=30,
        )
        self.assertEqual(row["status"],"OVERDUE_UNVERIFIED_WORK")
        self.assertTrue(row["dispatch_required"])
        self.assertEqual(row["reason"],"WORK_PROOF_RETRY_WINDOW_ELAPSED")

    def test_valid_work_proof_beats_unverified_retry_window(self):
        target=load_policy()["targets"][0]
        proof=verify_work_proof(target,scheduler_proof_doc(),run_id=75)
        row=evaluate_target(
          target,[run(target["workflow_name"],"2026-09-27T08:10:00Z",run_id=75)],
          at=AT,failure_retry_minutes=35,unverified_retry_minutes=30,run_proofs={75:proof},
        )
        self.assertEqual(row["status"],"HEALTHY_VERIFIED_WORK")
        self.assertFalse(row["dispatch_required"])

    def test_exact_run_scheduler_receipt_upgrades_recent_run_to_verified_health(self):
        target=load_policy()["targets"][0]
        proof=verify_work_proof(target,scheduler_proof_doc(),run_id=77)
        self.assertEqual(proof["status"],"VERIFIED_WORK")
        row=evaluate_target(
          target,[run(target["workflow_name"],"2026-09-27T08:50:00Z",run_id=77)],
          at=AT,failure_retry_minutes=35,run_proofs={77:proof},
        )
        self.assertEqual(row["status"],"HEALTHY_VERIFIED_WORK")
        self.assertEqual(row["reason"],"EXACT_RUN_SUBSTANTIVE_WORK_PROVEN")
        self.assertEqual(row["work_proof_metrics"]["attempted"],3)

    def test_scheduler_idle_receipt_is_verified_only_when_queue_is_empty(self):
        target=load_policy()["targets"][0]
        idle=receipt({
          "schema_version":"1.0.0",
          "cycle_id":"wexec-idle00000000000000000000",
          "finished_at":"2026-09-27T08:50:00Z",
          "attempted_count":0,
          "completed_count":0,
          "deferred_count":0,
          "remaining_queued_count":0,
          "authority_granted":False,
        })
        self.assertEqual(verify_work_proof(target,idle,run_id=80)["status"],"VERIFIED_WORK")
        blocked=dict(idle)
        blocked["remaining_queued_count"]=1
        blocked.pop("receipt_hash")
        blocked=receipt(blocked)
        proof=verify_work_proof(target,blocked,run_id=81)
        self.assertEqual(proof["status"],"INVALID_WORK_PROOF")
        self.assertEqual(proof["reason"],"SCHEDULER_IDLE_WITH_QUEUED_WORK")

    def test_tampered_receipt_never_paints_liveness_green(self):
        target=load_policy()["targets"][0]
        doc=scheduler_proof_doc()
        doc["completed_count"]=3
        proof=verify_work_proof(target,doc,run_id=78)
        self.assertEqual(proof["status"],"INVALID_WORK_PROOF")
        row=evaluate_target(
          target,[run(target["workflow_name"],"2026-09-27T08:50:00Z",run_id=78)],
          at=AT,failure_retry_minutes=35,run_proofs={78:proof},
        )
        self.assertEqual(row["status"],"RECENT_RUN_UNVERIFIED_WORK")
        self.assertEqual(row["work_proof_status"],"INVALID_WORK_PROOF")

    def test_artifact_fetch_is_exact_run_bound_and_validates_inside_zip(self):
        target=load_policy()["targets"][0]
        payload=io.BytesIO()
        with zipfile.ZipFile(payload,"w") as zf:
            zf.writestr(target["proof_member"],json.dumps(scheduler_proof_doc()))
        artifact_json=json.dumps({"artifacts":[{
          "id":123,"name":target["proof_artifact_name"],"expired":False,
          "archive_download_url":"https://api.github.com/fake/archive"
        }]}).encode()
        calls=[]
        downloads=[]
        def request(url,token,**kwargs):
            calls.append(url)
            return artifact_json
        def download(url,token):
            downloads.append(url)
            return payload.getvalue()
        proof=fetch_run_work_proof(
          "P00NSMASHER/portfolio-brain","token",target,79,
          request=request,download_archive=download,
        )
        self.assertEqual(proof["status"],"VERIFIED_WORK")
        self.assertEqual(proof["artifact_id"],123)
        self.assertEqual(len(calls),1)
        self.assertEqual(len(downloads),1)
        self.assertIn("/actions/runs/79/artifacts?",calls[0])
        self.assertEqual(downloads[0],"https://api.github.com/fake/archive")

    def test_artifact_redirect_does_not_leak_github_authorization_to_storage(self):
        captured={}
        class FakeOpener:
            def open(self,req,timeout=20):
                captured["api_authorization"]=req.get_header("Authorization")
                raise urllib.error.HTTPError(
                  req.full_url,302,"Found",
                  {"Location":"https://signed-storage.example/artifact.zip"},None,
                )
        class FakeResponse:
            status=200
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self): return b"zip-bytes"
        def storage_open(req,timeout=20):
            captured["storage_url"]=req.full_url
            captured["storage_authorization"]=req.get_header("Authorization")
            return FakeResponse()
        with patch("urllib.request.build_opener",return_value=FakeOpener()), patch("urllib.request.urlopen",side_effect=storage_open):
            body=_download_artifact_archive("https://api.github.com/fake/archive","secret-token")
        self.assertEqual(body,b"zip-bytes")
        self.assertEqual(captured["api_authorization"],"Bearer secret-token")
        self.assertEqual(captured["storage_url"],"https://signed-storage.example/artifact.zip")
        self.assertIsNone(captured["storage_authorization"])

    def test_all_recent_exact_run_proofs_produce_healthy_watchdog_status(self):
        p=load_policy()
        runs=[]
        proofs={}
        for i,target in enumerate(p["targets"],start=1):
            runs.append(run(target["workflow_name"],"2026-09-27T08:50:00Z",run_id=i,workflow_file=target["workflow_file"]))
            proofs[i]={"status":"VERIFIED_WORK","reason":"TEST_PROOF","metrics":{},"authority_granted":False}
        result=recover_overdue(
          load_state(),runs,dispatch=lambda workflow,branch:None,
          at=AT,policy_data=p,run_proofs=proofs,
        )
        self.assertEqual(result["status"],"HEALTHY_VERIFIED_WORK")
        self.assertTrue(all(row["status"]=="HEALTHY_VERIFIED_WORK" for row in result["targets"]))

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


    def test_nonpaid_recovery_does_not_require_canonical_cost_state(self):
        dispatched=[]
        result=recover_overdue(
          None,[],
          dispatch=lambda workflow,branch:dispatched.append((workflow,branch)),
          at=AT,
        )
        self.assertEqual(result["status"],"RECOVERY_DISPATCHED")
        self.assertEqual(result["hard_stop_reason"],"COST_STATE_UNAVAILABLE")
        self.assertEqual(dispatched[0][0],"portfolio-autonomous-scheduler.yml")
        self.assertEqual(dispatched[1][0],"runtime-hourly-sync.yml")
        self.assertTrue(all(
          row.get("admission_domain")=="WORKLOAD"
          for row in result["dispatches"]
        ))
        self.assertFalse(result["authority_granted"])

    def test_paid_hard_stop_is_visible_but_does_not_suppress_core_recovery(self):
        route = {
            "status":"ROUTED","tier":2,"route_id":"MRT-LIVENESS-OVERAGE",
            "provider_id":"openai","model_id":"gpt-5.6-luna",
            "max_estimated_cost_usd":0.01,"route_hash":"sha256:liveness-overage",
        }
        request = {
            "request_id":"MRQ-LIVENESS-OVERAGE","project_ids":["PRJ-000"],
            "max_input_tokens":100,"max_output_tokens":100,
            "authority_class":"OBSERVE","data_classification":"SANITIZED",
        }
        state,decision=reserve_model_execution(load_state(),route,request,at=AT)
        actual=zero_usage()
        actual.update({"cost_usd":0.02,"input_tokens":100,"output_tokens":100,"model_calls":1,"api_calls":1})
        state,_=commit_reservation(state,decision["reservation_id"],actual,at=AT)

        dispatched=[]
        result=recover_overdue(
          state,[],
          dispatch=lambda workflow,branch:dispatched.append((workflow,branch)),
          at=AT,
        )
        self.assertEqual(result["status"],"RECOVERY_DISPATCHED")
        self.assertEqual(result["hard_stop_reason"],"CURRENT_DAY_PAID_RESERVATION_OVERAGE")
        self.assertEqual(dispatched[0][0],"portfolio-autonomous-scheduler.yml")
        self.assertEqual(dispatched[1][0],"runtime-hourly-sync.yml")
        scheduler=next(x for x in result["targets"] if x["workflow_name"]=="portfolio-autonomous-scheduler")
        self.assertEqual(scheduler["admission_status"],"WORKLOAD_ALLOWED")


    def test_spend_kill_switch_does_not_block_nonpaid_liveness_recovery(self):
        dispatched=[]
        with patch.dict(os.environ,{"PORTFOLIO_SPEND_DISABLED":"true"}):
            result=recover_overdue(
              load_state(),[],
              dispatch=lambda workflow,branch:dispatched.append((workflow,branch)),
              at=AT,
            )
        self.assertEqual(result["status"],"RECOVERY_DISPATCHED")
        self.assertTrue(str(result["hard_stop_reason"]).startswith("KILL_SWITCH:"))
        self.assertEqual(dispatched[0][0],"portfolio-autonomous-scheduler.yml")
        self.assertEqual(dispatched[1][0],"runtime-hourly-sync.yml")
        self.assertFalse(result["authority_granted"])

    def test_watchdog_workflow_persists_liveness_receipt_and_keeps_actions_write_only(self):
        workflow=(ROOT/".github/workflows/portfolio-cost-watchdog.yml").read_text()
        self.assertIn("python -m operations.workflow_liveness",workflow)
        self.assertIn("--without-cost-state",workflow)
        self.assertIn("Recover non-paid core workflows without canonical cost state",workflow)
        self.assertIn("portfolio-workflow-liveness-pre-restore",workflow)
        self.assertLess(
          workflow.index("Recover non-paid core workflows without canonical cost state"),
          workflow.index("Restore canonical cost-governor state"),
        )
        self.assertIn("portfolio-workflow-liveness",workflow)
        self.assertIn("actions: write",workflow)
        self.assertIn("contents: read",workflow)
        self.assertNotIn("contents: write",workflow)
        self.assertIn("workflow_run:",workflow)
        for producer in ("portfolio-autonomous-scheduler","runtime-hourly-sync","agent-heartbeat-sweep","hunter-autonomous-cycle","portfolio-notification-cycle"):
            self.assertIn(f'      - "{producer}"',workflow)
        self.assertIn("types: [completed]",workflow)
        self.assertIn('branches: ["main"]',workflow)
        self.assertIn('operations/TRIGGER_WORKFLOW_LIVENESS',workflow)
        self.assertIn("\n  push:",workflow)


    def test_runtime_sync_wakes_immediately_after_runtime_repairs_land_on_main(self):
        workflow=(ROOT/".github/workflows/runtime-hourly-sync.yml").read_text()
        self.assertIn("\n  push:\n",workflow)
        self.assertIn('branches: ["main"]',workflow)
        for path in ("adapters/**","runtime/**",".github/workflows/runtime-hourly-sync.yml",".github/workflows/runtime-worker.yml"):
            self.assertIn(f'      - "{path}"',workflow)



if __name__=="__main__":
    unittest.main()
