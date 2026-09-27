#!/usr/bin/env python3
"""Bounded self-healing liveness recovery for core autonomous workflows.

This watchdog never performs portfolio work itself. It only requests a normal
workflow_dispatch for an overdue core workflow; the target workflow must still
pass its own cost, authority, kill-switch, and concurrency gates.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from cost_governor.cost_governor import (
    hard_stop_reason,
    load_state,
    make_github_job_request,
    policy as cost_policy,
    preflight,
)

ROOT=Path(__file__).resolve().parents[1]
POLICY_PATH=ROOT/"operations"/"WORKFLOW_LIVENESS_POLICY.json"
ACTIVE_STATUSES={"queued","in_progress","waiting","requested","pending"}
FAILURE_CONCLUSIONS={"failure","cancelled","timed_out","action_required","startup_failure","stale"}
TRUSTED_RUN_EVENTS={"schedule","workflow_dispatch","repository_dispatch","push"}

class WorkflowLivenessError(RuntimeError):
    pass

def req(ok:bool,msg:str)->None:
    if not ok:
        raise WorkflowLivenessError(msg)

def load_policy()->dict[str,Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))

def now_iso()->str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

def _time(value:str)->datetime:
    req(isinstance(value,str) and value.endswith("Z"),"workflow run timestamp must be UTC ISO-8601")
    try:
        parsed=datetime.fromisoformat(value[:-1]+"+00:00")
    except ValueError as exc:
        raise WorkflowLivenessError("workflow run timestamp invalid") from exc
    return parsed.astimezone(timezone.utc)

def validate_policy(p:dict[str,Any])->None:
    required={
      "schema_version","liveness_id","enabled","default_branch","max_api_requests_per_cycle",
      "max_history_pages","max_dispatches_per_cycle","recent_failure_retry_after_minutes",
      "authority_class","dispatch_authority_effect","hard_stop_behavior","targets","invariants"
    }
    req(isinstance(p,dict) and set(p)==required,"workflow liveness policy fields changed")
    req(p["schema_version"]=="1.0.0" and p["liveness_id"]=="portfolio-core-workflow-liveness-v1","workflow liveness policy identity mismatch")
    req(p["enabled"] is True,"workflow liveness recovery disabled")
    req(p["default_branch"]=="main","workflow liveness default branch changed")
    req(type(p["max_api_requests_per_cycle"]) is int and 3<=p["max_api_requests_per_cycle"]<=20,"workflow liveness API budget invalid")
    req(type(p["max_history_pages"]) is int and 1<=p["max_history_pages"]<=5,"workflow liveness history-page bound invalid")
    req(type(p["max_dispatches_per_cycle"]) is int and 1<=p["max_dispatches_per_cycle"]<=2,"workflow liveness dispatch bound invalid")
    req(type(p["recent_failure_retry_after_minutes"]) is int and 20<=p["recent_failure_retry_after_minutes"]<=120,"workflow liveness failure retry window invalid")
    req(p["authority_class"]=="NONE" and p["dispatch_authority_effect"]=="NONE","workflow liveness authority widened")
    req(p["hard_stop_behavior"]=="NO_RECOVERY_DISPATCH","workflow liveness hard-stop behavior weakened")
    req(isinstance(p["targets"],list) and 1<=len(p["targets"])<=8,"workflow liveness target set invalid")
    names=set();files=set();prior_priority=0
    governed_jobs=cost_policy()["workflow_job_ceilings"]
    for target in p["targets"]:
        req(set(target)=={
          "workflow_name","workflow_file","cost_workflow_id","cost_job_id",
          "project_ids","estimated_minutes","authority_class",
          "max_start_age_minutes","priority"
        },"workflow liveness target fields changed")
        req(isinstance(target["workflow_name"],str) and target["workflow_name"],"workflow liveness target name invalid")
        req(isinstance(target["workflow_file"],str) and target["workflow_file"].endswith(".yml"),"workflow liveness target file invalid")
        req(target["workflow_name"] not in names and target["workflow_file"] not in files,"duplicate workflow liveness target")
        names.add(target["workflow_name"]);files.add(target["workflow_file"])
        req(type(target["max_start_age_minutes"]) is int and 60<=target["max_start_age_minutes"]<=480,"workflow liveness target age invalid")
        req(type(target["priority"]) is int and target["priority"]>prior_priority,"workflow liveness priorities must be strictly increasing")
        scope=f'{target["cost_workflow_id"]}::{target["cost_job_id"]}'
        req(scope in governed_jobs,"workflow liveness target cost scope is not governed")
        req(type(target["project_ids"]) is list and target["project_ids"] and len(target["project_ids"])==len(set(target["project_ids"])),"workflow liveness target project scope invalid")
        req(all(isinstance(x,str) and x.startswith("PRJ-") for x in target["project_ids"]),"workflow liveness target project id invalid")
        req(type(target["estimated_minutes"]) is int and 1<=target["estimated_minutes"]<=governed_jobs[scope]["max_minutes_per_job"],"workflow liveness target estimate invalid")
        req(target["authority_class"] in {"NONE","OBSERVE","EXPERIMENT","MODIFY"},"workflow liveness target authority invalid")
        workflow_path=ROOT/".github"/"workflows"/target["workflow_file"]
        req(workflow_path.exists(),"workflow liveness target file missing")
        workflow_body=workflow_path.read_text(encoding="utf-8")
        reusable_marker="uses: ./.github/workflows/runtime-worker.yml"
        if reusable_marker in workflow_body:
            workflow_body+="\n"+(ROOT/".github"/"workflows"/"runtime-worker.yml").read_text(encoding="utf-8")
        for fragment in (
          f'--workflow-id {target["cost_workflow_id"]}',
          f'--job-id {target["cost_job_id"]}',
          f'--estimated-minutes {target["estimated_minutes"]}',
          f'--authority {target["authority_class"]}',
          *(f'--project-id {project_id}' for project_id in target["project_ids"]),
        ):
            req(fragment in workflow_body,"workflow liveness cost preview drifted from target preflight")
        prior_priority=target["priority"]
    req(isinstance(p["invariants"],list) and len(p["invariants"])>=5,"workflow liveness invariants missing")

def _matches_target_run(target:dict[str,Any],row:dict[str,Any],*,default_branch:str)->bool:
    """Bind liveness evidence to the governed workflow file on the governed branch.

    Workflow display names are mutable and are not unique across files or branches.
    Treating a name-only match as proof of health lets an unrelated run suppress
    recovery of the actual production workflow.
    """
    return (
      row.get("name")==target["workflow_name"]
      and row.get("path")==f".github/workflows/{target['workflow_file']}"
      and row.get("head_branch")==default_branch
      and row.get("event") in TRUSTED_RUN_EVENTS
    )

def evaluate_target(
    target:dict[str,Any],
    runs:list[dict[str,Any]],
    *,
    at:str,
    failure_retry_minutes:int,
    default_branch:str="main",
)->dict[str,Any]:
    now=_time(at)
    matching=[
      row for row in runs
      if _matches_target_run(target,row,default_branch=default_branch)
    ]
    active=[
      row for row in matching
      if row.get("status") in ACTIVE_STATUSES
    ]
    if active:
        newest=max(active,key=lambda row:row.get("created_at") or "")
        return {
          "workflow_name":target["workflow_name"],
          "workflow_file":target["workflow_file"],
          "status":"HEALTHY_ACTIVE",
          "dispatch_required":False,
          "latest_run_id":newest.get("id"),
          "latest_status":newest.get("status"),
          "latest_conclusion":newest.get("conclusion"),
          "age_minutes":max(0,round((now-_time(newest["created_at"])).total_seconds()/60,1)),
          "reason":"ACTIVE_RUN_EXISTS",
        }
    completed=[row for row in matching if row.get("status")=="completed" and isinstance(row.get("created_at"),str)]
    if not completed:
        return {
          "workflow_name":target["workflow_name"],
          "workflow_file":target["workflow_file"],
          "status":"OVERDUE_NO_HISTORY",
          "dispatch_required":True,
          "latest_run_id":None,
          "latest_status":None,
          "latest_conclusion":None,
          "age_minutes":None,
          "reason":"NO_RUN_IN_BOUNDED_HISTORY",
        }
    newest=max(completed,key=lambda row:row["created_at"])
    age=max(0,(now-_time(newest["created_at"])).total_seconds()/60)
    conclusion=newest.get("conclusion")
    if conclusion in FAILURE_CONCLUSIONS and age>=failure_retry_minutes:
        status="OVERDUE_RECENT_FAILURE";required=True;reason="FAILED_RUN_RETRY_WINDOW_ELAPSED"
    elif age>target["max_start_age_minutes"]:
        status="OVERDUE_MISSED_SCHEDULE";required=True;reason="LATEST_RUN_TOO_OLD"
    else:
        status="HEALTHY_RECENT_RUN";required=False;reason="RECENT_RUN_EXISTS"
    return {
      "workflow_name":target["workflow_name"],
      "workflow_file":target["workflow_file"],
      "status":status,
      "dispatch_required":required,
      "latest_run_id":newest.get("id"),
      "latest_status":newest.get("status"),
      "latest_conclusion":conclusion,
      "age_minutes":round(age,1),
      "reason":reason,
    }

def recover_overdue(
    state:dict[str,Any],
    runs:list[dict[str,Any]],
    *,
    dispatch:Callable[[str,str],None],
    at:str|None=None,
    policy_data:dict[str,Any]|None=None,
)->dict[str,Any]:
    p=policy_data or load_policy();validate_policy(p)
    at=at or now_iso()
    if os.environ.get("PORTFOLIO_SPEND_DISABLED","").strip().lower()=="true":
        return {
          "schema_version":"1.0.0","status":"BLOCKED_SPEND_KILL_SWITCH","checked_at":at,
          "hard_stop_reason":"PORTFOLIO_SPEND_DISABLED","dispatches":[],"targets":[],
          "authority_granted":False,
        }
    stop=hard_stop_reason(state,at=at)
    if stop is not None:
        return {
          "schema_version":"1.0.0","status":"BLOCKED_COST_HARD_STOP","checked_at":at,
          "hard_stop_reason":stop,"dispatches":[],"targets":[],
          "authority_granted":False,
        }
    evaluations=[
      evaluate_target(
        target,runs,at=at,
        failure_retry_minutes=p["recent_failure_retry_after_minutes"],
        default_branch=p["default_branch"],
      )
      for target in p["targets"]
    ]
    targets_by_name={row["workflow_name"]:row for row in p["targets"]}
    overdue=[row for row in evaluations if row["dispatch_required"]]
    overdue.sort(key=lambda row:targets_by_name[row["workflow_name"]]["priority"])
    dispatches=[]
    simulated_state=state
    for row in overdue:
        if len(dispatches)>=p["max_dispatches_per_cycle"]:
            break
        target=targets_by_name[row["workflow_name"]]
        preview_request=make_github_job_request(
          workflow_id=target["cost_workflow_id"],
          job_id=target["cost_job_id"],
          run_id=f'liveness-preview-{row["workflow_name"]}-{at}',
          attempt=1,
          project_ids=target["project_ids"],
          estimated_minutes=target["estimated_minutes"],
          authority_class=target["authority_class"],
          at=at,
        )
        simulated_state,preview=preflight(simulated_state,preview_request,at=at)
        row["cost_gate_status"]=preview["status"]
        row["cost_gate_reason_codes"]=preview["reason_codes"]
        if preview["status"]!="RESERVED":
            row["status"]="BLOCKED_COST_PREFLIGHT"
            row["dispatch_required"]=False
            row["reason"]="TARGET_COST_GATE_BLOCKED"
            continue
        dispatch(row["workflow_file"],p["default_branch"])
        dispatches.append({
          "workflow_name":row["workflow_name"],
          "workflow_file":row["workflow_file"],
          "reason":row["reason"],
          "prior_run_id":row["latest_run_id"],
          "cost_gate_status":preview["status"],
        })
    return {
      "schema_version":"1.0.0",
      "status":"RECOVERY_DISPATCHED" if dispatches else "HEALTHY",
      "checked_at":at,
      "hard_stop_reason":None,
      "dispatches":dispatches,
      "targets":evaluations,
      "authority_granted":False,
    }

def _request(url:str,token:str,*,method:str="GET",payload:dict[str,Any]|None=None)->bytes:
    data=None if payload is None else json.dumps(payload,separators=(",",":")).encode("utf-8")
    reqq=urllib.request.Request(
      url,
      data=data,
      headers={
        "Accept":"application/vnd.github+json",
        "Authorization":f"Bearer {token}",
        "X-GitHub-Api-Version":"2022-11-28",
        "User-Agent":"portfolio-brain-workflow-liveness/1.0",
        **({"Content-Type":"application/json"} if data is not None else {}),
      },
      method=method,
    )
    with urllib.request.urlopen(reqq,timeout=20) as response:
        return response.read()

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--state",default="cost_governor/live/cost_state.json")
    ap.add_argument("--output",default=None)
    args=ap.parse_args()
    p=load_policy();validate_policy(p)
    token=os.environ.get("GITHUB_TOKEN")
    repo=os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print(json.dumps({
          "schema_version":"1.0.0","status":"NO_ACTIONS_CONTEXT","dispatches":[],
          "targets":[],"authority_granted":False
        },sort_keys=True))
        return 0
    requests=0
    runs=[]
    found=set()
    target_names={row["workflow_name"] for row in p["targets"]}
    for page in range(1,p["max_history_pages"]+1):
        if requests>=p["max_api_requests_per_cycle"]:
            raise WorkflowLivenessError("workflow liveness API request budget exceeded")
        raw=_request(f"https://api.github.com/repos/{repo}/actions/runs?per_page=100&page={page}",token)
        requests+=1
        page_runs=json.loads(raw.decode()).get("workflow_runs",[])
        runs.extend(page_runs)
        found.update(
          target["workflow_name"]
          for target in p["targets"]
          if any(
            _matches_target_run(target,row,default_branch=p["default_branch"])
            for row in page_runs
          )
        )
        if target_names<=found or len(page_runs)<100:
            break
    def dispatch(workflow_file:str,branch:str)->None:
        nonlocal requests
        if requests>=p["max_api_requests_per_cycle"]:
            raise WorkflowLivenessError("workflow liveness API request budget exceeded")
        encoded=urllib.parse.quote(workflow_file,safe="")
        _request(
          f"https://api.github.com/repos/{repo}/actions/workflows/{encoded}/dispatches",
          token,
          method="POST",
          payload={"ref":branch},
        )
        requests+=1
    result=recover_overdue(load_state(args.state),runs,dispatch=dispatch)
    result["api_requests"]=requests
    if args.output:
        output=Path(args.output)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
