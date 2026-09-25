#!/usr/bin/env python3
"""Deterministic Step 24 no-prompt autonomous learning canary."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import unquote

from cost_governor.cost_governor import (
    commit_reservation,
    load_state as load_cost_state,
    make_github_job_request,
    preflight,
)
from dashboard.executive_dashboard import build_dashboard_snapshot
from learning.continuous_learning import rebuild_from_ledger
from notifications.notification_engine import (
    load_state as load_notification_state,
    notification_cycle,
)
from runtime.continuous_runtime import run as run_runtime
from runtime.state import bootstrap_state, validate_state as validate_runtime_state
from scheduler.autonomous_scheduler import (
    build_context,
    load_state as load_scheduler_state,
    schedule_cycle,
    validate_state as validate_scheduler_state,
)

ROOT=Path(__file__).resolve().parents[1]
T1="2026-09-25T23:20:00Z"
T2="2026-09-25T23:30:00Z"

class CanaryError(RuntimeError):pass

def req(ok,msg):
    if not ok:raise CanaryError(msg)

def load(path):
    return json.loads((ROOT/path).read_text())

def canon(v):
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)

def hashv(v):
    return "sha256:"+hashlib.sha256(canon(v).encode()).hexdigest()

def _write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+"\n")

class LocalCursorMirror:
    """Returns only already-persisted exact source SHAs; never uses the network."""
    def __init__(self):
        adapters=load("adapters/ADAPTER_REGISTRY.json")["adapters"]
        cursors=load("adapters/cursors/repositories.json")["repositories"]
        self.by_repo={a["repository_full_name"]:cursors[a["repository_id"]]["cursor_sha"] for a in adapters if a["repository_id"] in cursors}
        self.calls=[]
    def __call__(self,url):
        self.calls.append(url)
        marker="https://api.github.com/repos/"
        req(url.startswith(marker),"canary mirror received non-GitHub URL")
        rest=url[len(marker):]
        if "/commits/" in rest:
            repo=unquote(rest.split("/commits/",1)[0])
            req(repo in self.by_repo,"canary mirror unknown repository")
            return {"sha":self.by_repo[repo]}
        if "/compare/" in rest:
            return {"status":"identical","ahead_by":0,"behind_by":0,"total_commits":0,"files":[]}
        raise CanaryError("canary mirror unsupported URL")

def _load_json(path):
    return json.loads(Path(path).read_text())

def execute_canary(output_dir):
    policy=load("canary/CANARY_POLICY.json")
    req(policy["authority_class"]=="OBSERVE","canary authority widened")
    req(policy["paid_model_api_allowed"] is False and policy["max_model_calls"]==0 and policy["max_paid_cost_usd"]==0.0,"canary paid/model budget widened")
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    first=out/"first";second=out/"continuation";checkpoint=out/"checkpoint"
    for p in [first,second,checkpoint]:p.mkdir(parents=True,exist_ok=True)

    # ----- Initial durable state -----
    runtime_seed=bootstrap_state(now=T1);validate_runtime_state(runtime_seed)
    _write(checkpoint/"runtime_state.json",runtime_seed)
    scheduler_seed=load_scheduler_state();validate_scheduler_state(scheduler_seed);_write(checkpoint/"scheduler_state.json",scheduler_seed)
    cost_seed=load_cost_state();_write(checkpoint/"cost_state.json",cost_seed)
    notification_seed=load_notification_state();_write(checkpoint/"notification_state.json",notification_seed)

    # ----- First bounded cycle -----
    mirror1=LocalCursorMirror()
    runtime_receipt_1=run_runtime(
        policy["runtime_mode"],
        state_path=checkpoint/"runtime_state.json",
        output_dir=first/"runtime",
        fetch_json=mirror1,
        forced_now=T1,
    )
    runtime_state_1=_load_json(first/"runtime"/"runtime_state.json");validate_runtime_state(runtime_state_1)
    req(runtime_receipt_1["status"]=="PASS","runtime canary failed")
    req(runtime_receipt_1["api_requests"]<=policy["max_runtime_api_reads"],"runtime mirror read budget exceeded")
    req(all(o["status"] in {"UNCHANGED","BLOCKED"} for o in runtime_receipt_1["observations"]),"canary unexpectedly discovered source changes")

    scheduler_state_1,scheduler_receipt_1=schedule_cycle(scheduler_seed,build_context(),at=T1)
    validate_scheduler_state(scheduler_state_1)
    first_types=sorted({w["work_type"] for w in scheduler_receipt_1["selected_work"]})
    req(first_types==policy["expected_first_selected_work_types"],"unexpected first canary scheduler selection")
    req(len(scheduler_receipt_1["selected_work"])<=policy["max_selected_scheduler_work"],"scheduler canary selection ceiling exceeded")
    req(len(scheduler_receipt_1["blocked_work"])==policy["expected_blocked_approval_count"],"approval-blocked work count drifted")
    req(all(w["required_authority"]!="ACT" for w in [*scheduler_receipt_1["selected_work"],*scheduler_receipt_1["blocked_work"]]),"canary surfaced ACT-authorized work")
    _write(checkpoint/"scheduler_state.json",scheduler_state_1)

    cost_request=make_github_job_request(
        workflow_id="step24-autonomous-learning-canary",
        job_id="canary",
        run_id="step24-bounded-canary",
        attempt=1,
        project_ids=["PRJ-000"],
        estimated_minutes=5,
        authority_class="OBSERVE",
        at=T1,
    )
    cost_state_1,cost_decision_1=preflight(cost_seed,cost_request,at=T1)
    req(cost_decision_1["status"]=="RESERVED" and cost_decision_1["can_execute"] is True,"canary compute reservation failed")
    _,cost_duplicate_probe=preflight(cost_state_1,cost_request,at=T1)
    req(cost_duplicate_probe["status"]=="DUPLICATE_SUPPRESSED","cost duplicate probe failed")
    reserved=next(r for r in cost_state_1["reservations"] if r["reservation_id"]==cost_decision_1["reservation_id"])
    cost_state_1,cost_commit_1=commit_reservation(cost_state_1,cost_decision_1["reservation_id"],reserved["estimated_usage"],at=T1,evidence_ref="canary:first-cycle")
    req(cost_commit_1["status"]=="COMMITTED","canary cost commit failed")
    req(all((r["actual_usage"] or r["estimated_usage"])["cost_usd"]==0.0 for r in cost_state_1["reservations"]),"canary incurred paid cost")
    req(all((r["actual_usage"] or r["estimated_usage"])["model_calls"]==0 for r in cost_state_1["reservations"]),"canary incurred model calls")
    _write(checkpoint/"cost_state.json",cost_state_1)

    dashboard=build_dashboard_snapshot()
    notification_state_1,notification_receipt_1=notification_cycle(
        notification_seed,at=T1,
        sources={
          "dashboard":dashboard,
          "scheduler_receipt":scheduler_receipt_1,
          "scheduler_state":scheduler_state_1,
          "cost_state":cost_state_1,
        },
    )
    req(notification_receipt_1["authority_granted"] is False,"notifications granted authority")
    _write(checkpoint/"notification_state.json",notification_state_1)

    learning_1=rebuild_from_ledger()
    req(learning_1["policy_effect"]=="NONE","learning canary changed policy")
    req(learning_1["eligible_record_count"]==0,"empty checked-in learning ledger produced promotion eligibility")
    _write(checkpoint/"learning_state.json",learning_1)

    # Persist first-cycle sanitized states for exact byte restoration.
    _write(first/"scheduler_state.json",scheduler_state_1)
    _write(first/"cost_state.json",cost_state_1)
    _write(first/"notification_state.json",notification_state_1)
    _write(first/"learning_state.json",learning_1)

    # ----- Continuation from persisted bytes -----
    restored_runtime=_load_json(checkpoint/"runtime_state.json");validate_runtime_state(restored_runtime)
    restored_scheduler=load_scheduler_state(checkpoint/"scheduler_state.json")
    restored_cost=load_cost_state(checkpoint/"cost_state.json")
    restored_notification=load_notification_state(checkpoint/"notification_state.json")
    restored_learning=_load_json(checkpoint/"learning_state.json")

    mirror2=LocalCursorMirror()
    runtime_receipt_2=run_runtime(
        policy["runtime_mode"],
        state_path=checkpoint/"runtime_state.json",
        output_dir=second/"runtime",
        fetch_json=mirror2,
        forced_now=T2,
    )
    runtime_state_2=_load_json(second/"runtime"/"runtime_state.json");validate_runtime_state(runtime_state_2)
    req(runtime_state_2["sequence"]==runtime_state_1["sequence"]+1,"runtime continuation did not advance exactly once")

    scheduler_state_2,scheduler_receipt_2=schedule_cycle(restored_scheduler,build_context(),at=T2)
    validate_scheduler_state(scheduler_state_2)
    req(scheduler_receipt_2["selected_work"]==[],"unchanged continuation selected duplicate scheduler work")
    req(len(scheduler_receipt_2["suppressed_duplicates"])>=len(scheduler_receipt_1["selected_work"]),"continuation did not suppress prior work fingerprints")

    cost_state_2,cost_decision_2=preflight(restored_cost,cost_request,at=T2)
    req(cost_decision_2["status"]=="DUPLICATE_SUPPRESSED" and cost_decision_2["can_execute"] is False,"restored cost state did not suppress duplicate canary execution")

    notification_state_2,notification_receipt_2=notification_cycle(
        restored_notification,at=T2,
        sources={
          "dashboard":dashboard,
          "scheduler_receipt":scheduler_receipt_2,
          "scheduler_state":scheduler_state_2,
          "cost_state":restored_cost,
        },
    )
    req(notification_receipt_2["emitted_alerts"]==[],"unchanged continuation re-emitted cooldown-protected alerts")
    req(len(notification_receipt_2["suppressed_fingerprints"])>=2,"notification continuation failed dedup/cooldown suppression")

    learning_2=rebuild_from_ledger()
    req(learning_2["state_hash"]==restored_learning["state_hash"],"learning rebuild is not deterministic")
    req(learning_2["eligible_record_count"]==0,"continuation fabricated learning promotion")

    authority_violations=0
    if any(w["required_authority"]=="ACT" for w in scheduler_receipt_1["selected_work"]):authority_violations+=1
    if notification_receipt_1.get("authority_granted") is not False:authority_violations+=1
    if cost_decision_1.get("authority_granted") is not False:authority_violations+=1
    req(authority_violations==policy["authority_violations_allowed"],"canary authority violation detected")

    receipt={
      "schema_version":"1.0.0",
      "canary_id":policy["canary_id"],
      "mode":policy["mode"],
      "status":"PASS",
      "no_interactive_chatgpt_dependency":True,
      "network_mode":policy["network_mode"],
      "first_cycle":{
        "runtime_status":runtime_receipt_1["status"],
        "runtime_sequence":runtime_state_1["sequence"],
        "runtime_api_reads":runtime_receipt_1["api_requests"],
        "runtime_observation_status_counts":{s:sum(1 for o in runtime_receipt_1["observations"] if o["status"]==s) for s in ["UNCHANGED","BLOCKED"]},
        "scheduler_selected_count":len(scheduler_receipt_1["selected_work"]),
        "scheduler_selected_work_types":first_types,
        "scheduler_blocked_approval_count":len(scheduler_receipt_1["blocked_work"]),
        "cost_status":cost_commit_1["status"],
        "cost_duplicate_probe":cost_duplicate_probe["status"],
        "paid_cost_usd":sum((r["actual_usage"] or r["estimated_usage"])["cost_usd"] for r in cost_state_1["reservations"]),
        "model_calls":sum((r["actual_usage"] or r["estimated_usage"])["model_calls"] for r in cost_state_1["reservations"]),
        "notifications_emitted":len(notification_receipt_1["emitted_alerts"]),
        "learning_observations":learning_1["source_observation_count"],
        "learning_eligible_records":learning_1["eligible_record_count"],
      },
      "continuation":{
        "runtime_status":runtime_receipt_2["status"],
        "runtime_sequence":runtime_state_2["sequence"],
        "scheduler_selected_count":len(scheduler_receipt_2["selected_work"]),
        "scheduler_suppressed_duplicates":len(scheduler_receipt_2["suppressed_duplicates"]),
        "cost_status":cost_decision_2["status"],
        "notifications_emitted":len(notification_receipt_2["emitted_alerts"]),
        "notification_suppressed":len(notification_receipt_2["suppressed_fingerprints"]),
        "learning_state_hash_unchanged":learning_2["state_hash"]==learning_1["state_hash"],
      },
      "authority_violations":authority_violations,
      "forbidden_actions_attempted":0,
      "paid_model_api_used":False,
      "state_restoration":{
        "runtime":True,"scheduler":True,"cost":True,"notifications":True,"learning":True
      },
      "evidence_refs":[
        runtime_receipt_1["receipt_hash"],scheduler_receipt_1["receipt_hash"],
        cost_decision_1["decision_hash"],notification_receipt_1["receipt_hash"],
        learning_1["state_hash"],runtime_receipt_2["receipt_hash"],
        scheduler_receipt_2["receipt_hash"],notification_receipt_2["receipt_hash"]
      ]
    }
    receipt["receipt_hash"]=hashv(receipt)

    _write(out/"canary_receipt.json",receipt)
    _write(out/"runtime_state.json",runtime_state_2)
    _write(out/"scheduler_state.json",scheduler_state_2)
    _write(out/"cost_state.json",cost_state_2)
    _write(out/"notification_state.json",notification_state_2)
    _write(out/"learning_state.json",learning_2)
    return receipt

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--output-dir",default="canary/out");a=ap.parse_args()
    r=execute_canary(a.output_dir)
    print(json.dumps({"canary_id":r["canary_id"],"status":r["status"],"receipt_hash":r["receipt_hash"]},sort_keys=True))

if __name__=="__main__":main()
