#!/usr/bin/env python3
"""Bounded self-healing liveness recovery for core autonomous workflows.

This watchdog never performs portfolio work itself. It only requests a normal
workflow_dispatch for an overdue core workflow; the target workflow must still
pass its own cost, authority, kill-switch, and concurrency gates.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agents.heartbeat_state import registry as heartbeat_registry, validate_state as validate_heartbeat_state
from cost_governor.cost_governor import (
    hard_stop_reason,
    load_state,
    make_github_job_request,
    policy as cost_policy,
    preflight,
    validate_state as validate_cost_state,
)
from runtime.state import validate_cycle_receipt
from workload_control.workload_gate import evaluate as evaluate_workload, load_policy as workload_policy

ROOT=Path(__file__).resolve().parents[1]
POLICY_PATH=ROOT/"operations"/"WORKFLOW_LIVENESS_POLICY.json"
ACTIVE_STATUSES={"queued","in_progress","waiting","requested","pending"}
FAILURE_CONCLUSIONS={"failure","cancelled","timed_out","action_required","startup_failure","stale"}
TRUSTED_RUN_EVENTS={"schedule","workflow_dispatch","repository_dispatch","push"}
PROOF_KINDS={"SCHEDULER_EXECUTION","RUNTIME_SYNC","HEARTBEAT_SWEEP","HUNTER_CYCLE","NOTIFICATION_CYCLE"}

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
      "unverified_work_retry_after_minutes","authority_class","dispatch_authority_effect","hard_stop_behavior","targets","invariants"
    }
    req(isinstance(p,dict) and set(p)==required,"workflow liveness policy fields changed")
    req(p["schema_version"]=="1.0.0" and p["liveness_id"]=="portfolio-core-workflow-liveness-v1","workflow liveness policy identity mismatch")
    req(p["enabled"] is True,"workflow liveness recovery disabled")
    req(p["default_branch"]=="main","workflow liveness default branch changed")
    req(type(p["max_api_requests_per_cycle"]) is int and 3<=p["max_api_requests_per_cycle"]<=20,"workflow liveness API budget invalid")
    req(type(p["max_history_pages"]) is int and 1<=p["max_history_pages"]<=5,"workflow liveness history-page bound invalid")
    req(type(p["max_dispatches_per_cycle"]) is int and 1<=p["max_dispatches_per_cycle"]<=2,"workflow liveness dispatch bound invalid")
    req(type(p["recent_failure_retry_after_minutes"]) is int and 20<=p["recent_failure_retry_after_minutes"]<=120,"workflow liveness failure retry window invalid")
    req(type(p["unverified_work_retry_after_minutes"]) is int and 10<=p["unverified_work_retry_after_minutes"]<=120,"workflow liveness unverified-work retry window invalid")
    req(p["authority_class"]=="NONE" and p["dispatch_authority_effect"]=="NONE","workflow liveness authority widened")
    req(p["hard_stop_behavior"]=="NONPAID_RECOVERY_CONTINUES","workflow liveness hard-stop separation changed")
    req(isinstance(p["targets"],list) and 1<=len(p["targets"])<=8,"workflow liveness target set invalid")

    names=set();files=set();prior_priority=0
    paid_jobs=cost_policy()["workflow_job_ceilings"]
    workload_jobs=workload_policy()["services"]

    for target in p["targets"]:
        req(set(target)=={
          "workflow_name","workflow_file","admission_domain","admission_workflow_id","admission_job_id",
          "project_ids","estimated_minutes","authority_class","max_start_age_minutes","priority",
          "proof_artifact_name","proof_member","proof_kind"
        },"workflow liveness target fields changed")
        req(isinstance(target["workflow_name"],str) and target["workflow_name"],"workflow liveness target name invalid")
        req(isinstance(target["workflow_file"],str) and target["workflow_file"].endswith(".yml"),"workflow liveness target file invalid")
        req(target["workflow_name"] not in names and target["workflow_file"] not in files,"duplicate workflow liveness target")
        names.add(target["workflow_name"]);files.add(target["workflow_file"])
        req(type(target["max_start_age_minutes"]) is int and 60<=target["max_start_age_minutes"]<=480,"workflow liveness target age invalid")
        req(type(target["priority"]) is int and target["priority"]>prior_priority,"workflow liveness priorities must be strictly increasing")
        req(target["admission_domain"] in {"WORKLOAD","COST_WRAPPER"},"workflow liveness admission domain invalid")
        scope=f'{target["admission_workflow_id"]}::{target["admission_job_id"]}'
        controls=workload_jobs if target["admission_domain"]=="WORKLOAD" else paid_jobs
        req(scope in controls,f"workflow liveness target admission scope is not configured: {scope}")
        req(type(target["project_ids"]) is list and target["project_ids"] and len(target["project_ids"])==len(set(target["project_ids"])),"workflow liveness target project scope invalid")
        req(all(isinstance(x,str) and x.startswith("PRJ-") for x in target["project_ids"]),"workflow liveness target project id invalid")
        req(type(target["estimated_minutes"]) is int and 1<=target["estimated_minutes"]<=controls[scope]["max_minutes_per_job"],"workflow liveness target estimate invalid")
        req(target["authority_class"] in {"NONE","OBSERVE","EXPERIMENT","MODIFY"},"workflow liveness target authority invalid")
        req(isinstance(target["proof_artifact_name"],str) and target["proof_artifact_name"].startswith("portfolio-"),"workflow liveness proof artifact invalid")
        req(isinstance(target["proof_member"],str) and target["proof_member"].endswith(".json") and "/" not in target["proof_member"],"workflow liveness proof member invalid")
        req(target["proof_kind"] in PROOF_KINDS,"workflow liveness proof kind invalid")

        workflow_path=ROOT/".github"/"workflows"/target["workflow_file"]
        req(workflow_path.exists(),"workflow liveness target file missing")
        workflow_body=workflow_path.read_text(encoding="utf-8")
        reusable_marker="uses: ./.github/workflows/runtime-worker.yml"
        if reusable_marker in workflow_body:
            workflow_body+="\n"+(ROOT/".github"/"workflows"/"runtime-worker.yml").read_text(encoding="utf-8")
        req(f'name: {target["proof_artifact_name"]}' in workflow_body,"workflow liveness proof artifact is not produced by target")

        if target["admission_domain"]=="WORKLOAD":
            cfg=workload_jobs[scope]
            fragments=[
              "workload_control.workload_gate preflight",
              f'--workflow-id {target["admission_workflow_id"]}',
              f'--estimated-minutes {target["estimated_minutes"]}',
            ]
            if target["admission_workflow_id"]=="runtime-worker":
                mode=target["admission_job_id"].removeprefix("runtime-")
                req(cfg["concurrency_group"]==f"portfolio-runtime-{mode}","runtime workload concurrency policy drifted")
                fragments.extend([
                  '--job-id "runtime-${RUNTIME_MODE}"',
                  "format('portfolio-runtime-{0}', inputs.mode)",
                ])
            else:
                fragments.extend([
                  f'--job-id {target["admission_job_id"]}',
                  f'group: {cfg["concurrency_group"]}',
                ])
            for fragment in fragments:
                req(fragment in workflow_body,"workflow liveness workload admission drifted from target")
        else:
            job_marker = ('--job-id "runtime-${RUNTIME_MODE}"'
                          if target["admission_workflow_id"]=="runtime-worker"
                          else f'--job-id {target["admission_job_id"]}')
            for fragment in (
              "cost_governor.workflow_gate preflight",
              f'--workflow-id {target["admission_workflow_id"]}',
              job_marker,
              f'--estimated-minutes {target["estimated_minutes"]}',
              f'--authority {target["authority_class"]}',
              *(f'--project-id {project_id}' for project_id in target["project_ids"]),
            ):
                req(fragment in workflow_body,"workflow liveness cost-wrapper admission drifted from target")
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

def _canon(value:Any)->str:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)

def _hash_value(value:Any)->str:
    return "sha256:"+hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()

def _valid_receipt_hash(document:dict[str,Any])->bool:
    expected=document.get("receipt_hash")
    if not isinstance(expected,str) or not expected.startswith("sha256:"):
        return False
    body={key:value for key,value in document.items() if key!="receipt_hash"}
    return expected==_hash_value(body)

def _proof(status:str,reason:str,metrics:dict[str,Any]|None=None)->dict[str,Any]:
    return {"status":status,"reason":reason,"metrics":metrics or {},"authority_granted":False}

def verify_work_proof(target:dict[str,Any],document:Any,*,run_id:int)->dict[str,Any]:
    if not isinstance(document,dict):
        return _proof("INVALID_WORK_PROOF","PROOF_DOCUMENT_NOT_OBJECT")
    kind=target["proof_kind"]
    if kind=="SCHEDULER_EXECUTION":
        fields=("attempted_count","completed_count","deferred_count","remaining_queued_count")
        if document.get("schema_version")!="1.0.0" or not str(document.get("cycle_id","")).startswith("wexec-"):
            return _proof("INVALID_WORK_PROOF","SCHEDULER_RECEIPT_IDENTITY_INVALID")
        if document.get("authority_granted") is not False or not _valid_receipt_hash(document):
            return _proof("INVALID_WORK_PROOF","SCHEDULER_RECEIPT_INTEGRITY_INVALID")
        if not all(type(document.get(key)) is int and document[key]>=0 for key in fields):
            return _proof("INVALID_WORK_PROOF","SCHEDULER_RECEIPT_COUNTS_INVALID")
        if document["completed_count"]+document["deferred_count"]!=document["attempted_count"]:
            return _proof("INVALID_WORK_PROOF","SCHEDULER_EXECUTION_ACCOUNTING_INVALID")
        if document["attempted_count"]==0 and document["remaining_queued_count"]!=0:
            return _proof("INVALID_WORK_PROOF","SCHEDULER_IDLE_WITH_QUEUED_WORK")
        return _proof("VERIFIED_WORK","SCHEDULER_EXECUTION_RECEIPT",{
          "attempted":document["attempted_count"],"completed":document["completed_count"],
          "deferred":document["deferred_count"],"remaining_queued":document["remaining_queued_count"],
        })

    if kind=="RUNTIME_SYNC":
        observations=document.get("observations")
        if document.get("schema_version")!="1.0.0" or document.get("mode")!="sync" or document.get("status")!="PASS":
            return _proof("INVALID_WORK_PROOF","RUNTIME_SYNC_RECEIPT_IDENTITY_INVALID")
        try:
            validate_cycle_receipt(document)
        except ValueError:
            return _proof("INVALID_WORK_PROOF","RUNTIME_SYNC_RECEIPT_INTEGRITY_INVALID")
        if not isinstance(observations,list) or len(observations)<1 or type(document.get("api_requests")) is not int or document["api_requests"]<1:
            return _proof("INVALID_WORK_PROOF","RUNTIME_SYNC_NO_SUBSTANTIVE_OBSERVATION")
        return _proof("VERIFIED_WORK","RUNTIME_SYNC_RECEIPT",{
          "observations":len(observations),"api_requests":document["api_requests"],
          "cycle_id":document["cycle_id"], "finished_at":document["finished_at"],
          "receipt_hash":document["receipt_hash"],
        })

    if kind=="HUNTER_CYCLE":
        funnel=document.get("rejection_funnel")
        outcomes=document.get("query_outcomes")
        if document.get("schema_version")!="1.0.0" or document.get("status")!="PASS":
            return _proof("INVALID_WORK_PROOF","HUNTER_RECEIPT_IDENTITY_INVALID")
        if not _valid_receipt_hash(document):
            return _proof("INVALID_WORK_PROOF","HUNTER_RECEIPT_INTEGRITY_INVALID")
        if not isinstance(funnel,dict) or not isinstance(outcomes,list):
            return _proof("INVALID_WORK_PROOF","HUNTER_QUERY_ACCOUNTING_INVALID")
        executed=funnel.get("queries_executed")
        suppressed=funnel.get("queries_suppressed")
        if type(executed) is not int or type(suppressed) is not int or executed<0 or suppressed<0:
            return _proof("INVALID_WORK_PROOF","HUNTER_QUERY_COUNTS_INVALID")
        if executed+suppressed<1 or len(outcomes)<1:
            return _proof("INVALID_WORK_PROOF","HUNTER_NO_BOUNDED_QUERY_EVALUATION")
        return _proof("VERIFIED_WORK","HUNTER_CYCLE_RECEIPT",{
          "queries_executed":executed,"queries_suppressed":suppressed,"findings":len(document.get("findings",[])),
          "retained":funnel.get("retained",0),"proposals":len(document.get("experiment_proposals",[])),
        })

    if kind=="NOTIFICATION_CYCLE":
        emitted=document.get("emitted_alerts")
        if document.get("schema_version")!="1.0.0" or document.get("status")!="PASS":
            return _proof("INVALID_WORK_PROOF","NOTIFICATION_RECEIPT_IDENTITY_INVALID")
        if document.get("authority_granted") is not False or not _valid_receipt_hash(document):
            return _proof("INVALID_WORK_PROOF","NOTIFICATION_RECEIPT_INTEGRITY_INVALID")
        if type(document.get("signal_count")) is not int or document["signal_count"]<0 or not isinstance(emitted,list):
            return _proof("INVALID_WORK_PROOF","NOTIFICATION_RECEIPT_COUNTS_INVALID")
        return _proof("VERIFIED_WORK","NOTIFICATION_CYCLE_RECEIPT",{
          "signals":document["signal_count"],"emitted":len(emitted),
          "active_alerts":document.get("active_alert_count"),
        })

    if kind=="HEARTBEAT_SWEEP":
        try:
            validate_heartbeat_state(document)
        except Exception:
            return _proof("INVALID_WORK_PROOF","HEARTBEAT_STATE_INTEGRITY_INVALID")
        matching=[
          event for event in document.get("recent_events",[])
          if event.get("source_workflow")=="agent-heartbeat-sweep"
          and event.get("source_run_id")==str(run_id)
          and event.get("activity_kind")=="HEALTH_CHECK"
        ]
        registered=set(heartbeat_registry())
        observed={event.get("agent_id") for event in matching}
        if observed!=registered:
            return _proof("INVALID_WORK_PROOF","HEARTBEAT_SWEEP_INCOMPLETE")
        return _proof("VERIFIED_WORK","HEARTBEAT_SWEEP_EVENT_PROOF",{
          "agents_heartbeated":len(observed),
        })

    return _proof("INVALID_WORK_PROOF","UNKNOWN_PROOF_KIND")

def evaluate_target(
    target:dict[str,Any],
    runs:list[dict[str,Any]],
    *,
    at:str,
    failure_retry_minutes:int,
    default_branch:str="main",
    run_proofs:dict[int,dict[str,Any]]|None=None,
    unverified_retry_minutes:int|None=None,
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
    proof=(run_proofs or {}).get(newest.get("id"))
    if conclusion in FAILURE_CONCLUSIONS and age>=failure_retry_minutes:
        status="OVERDUE_RECENT_FAILURE";required=True;reason="FAILED_RUN_RETRY_WINDOW_ELAPSED"
    elif age>target["max_start_age_minutes"]:
        status="OVERDUE_MISSED_SCHEDULE";required=True;reason="LATEST_RUN_TOO_OLD"
    elif conclusion=="success" and proof is not None and proof.get("status")=="VERIFIED_WORK":
        status="HEALTHY_VERIFIED_WORK";required=False;reason="EXACT_RUN_SUBSTANTIVE_WORK_PROVEN"
    elif conclusion=="success" and unverified_retry_minutes is not None and age>=unverified_retry_minutes:
        status="OVERDUE_UNVERIFIED_WORK";required=True;reason="WORK_PROOF_RETRY_WINDOW_ELAPSED"
    else:
        # Actions conclusion proves a run occurred, not that its governed work
        # was admitted or that the intended output was produced.
        status="RECENT_RUN_UNVERIFIED_WORK";required=False;reason="RECENT_RUN_EXISTS_WORK_UNVERIFIED"
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
      "work_proof_status":None if proof is None else proof.get("status"),
      "work_proof_reason":None if proof is None else proof.get("reason"),
      "work_proof_metrics":{} if proof is None else proof.get("metrics",{}),
    }

def recover_overdue(
    state:dict[str,Any]|None,
    runs:list[dict[str,Any]],
    *,
    dispatch:Callable[[str,str],None],
    at:str|None=None,
    policy_data:dict[str,Any]|None=None,
    run_proofs:dict[int,dict[str,Any]]|None=None,
    persistence_incident_open:bool=False,
)->dict[str,Any]:
    p=policy_data or load_policy();validate_policy(p)
    at=at or now_iso()
    paid_stop="COST_STATE_UNAVAILABLE" if state is None else hard_stop_reason(state,at=at)

    evaluations=[
      evaluate_target(
        target,runs,at=at,
        failure_retry_minutes=p["recent_failure_retry_after_minutes"],
        default_branch=p["default_branch"],
        run_proofs=run_proofs,
        unverified_retry_minutes=p["unverified_work_retry_after_minutes"],
      )
      for target in p["targets"]
    ]
    targets_by_name={row["workflow_name"]:row for row in p["targets"]}
    if persistence_incident_open:
        for row in evaluations:
            if row["dispatch_required"]:
                row["status"]="BLOCKED_PERSISTENCE_RECOVERY"
                row["dispatch_required"]=False
                row["reason"]="CHECKPOINT_RECOVERY_IN_PROGRESS"
                row["admission_status"]="PERSISTENCE_RECOVERY_IN_PROGRESS"
                row["admission_reason_codes"]=["CHECKPOINT_RECOVERY_IN_PROGRESS"]
        return {
          "schema_version":"1.0.0",
          "status":"PERSISTENCE_RECOVERY_IN_PROGRESS",
          "checked_at":at,
          "hard_stop_reason":paid_stop,
          "persistence_incident_open":True,
          "dispatches":[],
          "targets":evaluations,
          "authority_granted":False,
        }
    overdue=[row for row in evaluations if row["dispatch_required"]]
    overdue.sort(key=lambda row:targets_by_name[row["workflow_name"]]["priority"])
    dispatches=[]
    simulated_state=state

    for row in overdue:
        if len(dispatches)>=p["max_dispatches_per_cycle"]:
            break
        target=targets_by_name[row["workflow_name"]]

        if target["admission_domain"]=="WORKLOAD":
            preview=evaluate_workload(
              workflow_id=target["admission_workflow_id"],
              job_id=target["admission_job_id"],
              estimated_minutes=target["estimated_minutes"],
            )
            row["admission_status"]=preview["status"]
            row["admission_reason_codes"]=[preview["reason"]]
            allowed=preview["allowed"]
        else:
            if simulated_state is None:
                row["admission_status"]="COST_STATE_UNAVAILABLE"
                row["admission_reason_codes"]=["TRUSTED_COST_STATE_REQUIRED"]
                allowed=False
            else:
                preview_request=make_github_job_request(
                  workflow_id=target["admission_workflow_id"],
                  job_id=target["admission_job_id"],
                  run_id=f'liveness-preview-{row["workflow_name"]}-{at}',
                  attempt=1,
                  project_ids=target["project_ids"],
                  estimated_minutes=target["estimated_minutes"],
                  authority_class=target["authority_class"],
                  at=at,
                )
                simulated_state,preview=preflight(simulated_state,preview_request,at=at)
                row["admission_status"]=preview["status"]
                row["admission_reason_codes"]=preview["reason_codes"]
                allowed=preview["status"]=="RESERVED"

        if not allowed:
            row["status"]="BLOCKED_ADMISSION_PREFLIGHT"
            row["dispatch_required"]=False
            row["reason"]="TARGET_ADMISSION_BLOCKED"
            continue

        dispatch(row["workflow_file"],p["default_branch"])
        dispatches.append({
          "workflow_name":row["workflow_name"],
          "workflow_file":row["workflow_file"],
          "reason":row["reason"],
          "prior_run_id":row["latest_run_id"],
          "admission_status":row["admission_status"],
          "admission_domain":target["admission_domain"],
        })

    return {
      "schema_version":"1.0.0",
      "status":("RECOVERY_DISPATCHED" if dispatches else
                "BLOCKED_ADMISSION_PREFLIGHT" if any(row["status"]=="BLOCKED_ADMISSION_PREFLIGHT" for row in evaluations) else
                "RECENT_RUNS_WORK_UNVERIFIED" if any(row["status"]=="RECENT_RUN_UNVERIFIED_WORK" for row in evaluations) else
                "HEALTHY_VERIFIED_WORK"),
      "checked_at":at,
      "hard_stop_reason":paid_stop,
      "persistence_incident_open":False,
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

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, reqq, fp, code, msg, headers, newurl):
        return None

def _download_artifact_archive(url:str,token:str)->bytes:
    reqq=urllib.request.Request(
      url,
      headers={
        "Accept":"application/vnd.github+json",
        "Authorization":f"Bearer {token}",
        "X-GitHub-Api-Version":"2022-11-28",
        "User-Agent":"portfolio-brain-workflow-liveness/1.0",
      },
      method="GET",
    )
    opener=urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(reqq,timeout=20) as response:
            req(getattr(response,"status",200)==200,"artifact archive API response invalid")
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code not in {301,302,303,307,308}:
            raise
        location=exc.headers.get("Location")
        req(isinstance(location,str) and location.startswith("https://"),"artifact archive redirect missing")
    storage_request=urllib.request.Request(
      location,
      headers={"User-Agent":"portfolio-brain-workflow-liveness/1.0"},
      method="GET",
    )
    with urllib.request.urlopen(storage_request,timeout=20) as response:
        req(getattr(response,"status",200)==200,"artifact storage response invalid")
        return response.read()

def fetch_run_work_proof(
    repo:str,
    token:str,
    target:dict[str,Any],
    run_id:int,
    *,
    request:Callable[...,bytes]=_request,
    download_archive:Callable[[str,str],bytes]=_download_artifact_archive,
)->dict[str,Any]:
    try:
        artifact_name=target["proof_artifact_name"]
        encoded_name=urllib.parse.quote(artifact_name,safe="")
        raw=request(
          f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100&name={encoded_name}",
          token,
        )
        artifacts=json.loads(raw.decode("utf-8")).get("artifacts",[])
        exact=[row for row in artifacts if row.get("name")==artifact_name and not row.get("expired",False)]
        if len(exact)!=1:
            return _proof(
              "MISSING_WORK_PROOF" if not exact else "INVALID_WORK_PROOF",
              "PROOF_ARTIFACT_MISSING_OR_EXPIRED" if not exact else "PROOF_ARTIFACT_AMBIGUOUS",
            )
        artifact=exact[0]
        archive_url=artifact.get("archive_download_url")
        if not isinstance(archive_url,str) or not archive_url:
            return _proof("INVALID_WORK_PROOF","PROOF_ARCHIVE_URL_MISSING")
        archive=download_archive(archive_url,token)
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            member=target["proof_member"]
            matches=[name for name in zf.namelist() if name==member or name.endswith("/"+member)]
            if len(matches)!=1:
                return _proof("INVALID_WORK_PROOF","PROOF_MEMBER_MISSING_OR_AMBIGUOUS")
            document=json.loads(zf.read(matches[0]).decode("utf-8"))
        result=verify_work_proof(target,document,run_id=run_id)
        result["artifact_name"]=artifact_name
        result["artifact_id"]=artifact.get("id")
        result["proof_member"]=target["proof_member"]
        return result
    except WorkflowLivenessError:
        raise
    except (OSError,ValueError,KeyError,json.JSONDecodeError,zipfile.BadZipFile,urllib.error.URLError) as exc:
        return _proof("INVALID_WORK_PROOF",f"PROOF_FETCH_OR_PARSE_ERROR:{type(exc).__name__}")

def cost_state_observation(state:dict[str,Any], metadata:dict[str,Any], *, at:str)->dict[str,Any]|None:
    """Attest an actual validated restore, not a seed or a new financial event."""
    validate_cost_state(state)
    if not (isinstance(metadata,dict)
            and str(metadata.get("restore_status", "")).startswith("RESTORED")
            and metadata.get("artifact_name")=="portfolio-cost-governor-state"
            and type(metadata.get("artifact_id")) is int and metadata["artifact_id"]>0
            and type(metadata.get("source_run_id")) is int and metadata["source_run_id"]>0
            and metadata.get("source_sequence")==state["sequence"]
            and metadata.get("source_state_hash")==_hash_value(state)):
        return None
    if state["updated_at"] is not None and _time(state["updated_at"])>_time(at):
        return None
    return {
        "status":"VERIFIED_UNCHANGED_STATE", "checked_at":at,
        "state_sequence":state["sequence"], "state_hash":_hash_value(state),
        "state_updated_at":state["updated_at"],
        "source_artifact_id":metadata["artifact_id"],
        "source_run_id":metadata["source_run_id"],
        "state_mutated":False,
    }

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--state",default="cost_governor/live/cost_state.json")
    ap.add_argument("--output",default=None)
    ap.add_argument("--state-metadata",default=None)
    ap.add_argument("--without-cost-state",action="store_true")
    ap.add_argument("--persistence-incident-open",action="store_true")
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
    def api_request(url:str,token_value:str,*,method:str="GET",payload:dict[str,Any]|None=None)->bytes:
        nonlocal requests
        if requests>=p["max_api_requests_per_cycle"]:
            raise WorkflowLivenessError("workflow liveness API request budget exceeded")
        raw=_request(url,token_value,method=method,payload=payload)
        requests+=1
        return raw

    def api_download_archive(url:str,token_value:str)->bytes:
        nonlocal requests
        if requests>=p["max_api_requests_per_cycle"]:
            raise WorkflowLivenessError("workflow liveness API request budget exceeded")
        raw=_download_artifact_archive(url,token_value)
        requests+=1
        return raw

    runs=[]
    found=set()
    target_names={row["workflow_name"] for row in p["targets"]}
    for page in range(1,p["max_history_pages"]+1):
        raw=api_request(f"https://api.github.com/repos/{repo}/actions/runs?per_page=100&page={page}",token)
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

    checked_at=now_iso()
    preliminary=[
      evaluate_target(
        target,runs,at=checked_at,
        failure_retry_minutes=p["recent_failure_retry_after_minutes"],
        default_branch=p["default_branch"],
      )
      for target in p["targets"]
    ]
    targets_by_name={row["workflow_name"]:row for row in p["targets"]}
    run_proofs={}
    for row in preliminary:
        run_id=row.get("latest_run_id")
        if row["status"]!="RECENT_RUN_UNVERIFIED_WORK" or row.get("latest_conclusion")!="success" or not isinstance(run_id,int):
            continue
        target=targets_by_name[row["workflow_name"]]
        run_proofs[run_id]=fetch_run_work_proof(
          repo,token,target,run_id,
          request=api_request,
          download_archive=api_download_archive,
        )

    def dispatch(workflow_file:str,branch:str)->None:
        encoded=urllib.parse.quote(workflow_file,safe="")
        api_request(
          f"https://api.github.com/repos/{repo}/actions/workflows/{encoded}/dispatches",
          token,
          method="POST",
          payload={"ref":branch},
        )
    state=None if args.without_cost_state else load_state(args.state)
    result=recover_overdue(
      state,runs,dispatch=dispatch,at=checked_at,run_proofs=run_proofs,
      persistence_incident_open=args.persistence_incident_open,
    )
    meta_path=None if args.state_metadata is None else Path(args.state_metadata)
    metadata=json.loads(meta_path.read_text()) if meta_path is not None and meta_path.exists() else {}
    result["cost_state_proof"]=None if state is None else cost_state_observation(state,metadata,at=checked_at)
    result["api_requests"]=requests
    result["verified_work_target_count"]=sum(1 for row in result["targets"] if row["status"]=="HEALTHY_VERIFIED_WORK")
    if args.output:
        output=Path(args.output)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
