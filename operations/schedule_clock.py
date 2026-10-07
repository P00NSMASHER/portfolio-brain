#!/usr/bin/env python3
"""Redundant schedule clock that turns any trusted native schedule tick into bounded core dispatches.

The clock grants no portfolio authority. It only invokes existing workflow_dispatch
entrypoints, whose normal workload/cost/kill-switch/concurrency gates remain authoritative.
"""
from __future__ import annotations
import argparse,json,os,re,time,urllib.parse,urllib.request
from datetime import datetime,timedelta,timezone
from pathlib import Path
from typing import Any

from state_journal.contracts import WORKFLOW_PRODUCERS

ROOT=Path(__file__).resolve().parents[1]
REPO="P00NSMASHER/portfolio-brain"
POLICY_PATH=ROOT/"operations/SCHEDULE_CLOCK_POLICY.json"
REDUCER_WORKFLOW_FILE="portfolio-state-reducer.yml"
TERMINAL_CONCLUSIONS={"success","failure","cancelled","timed_out"}
ACTIVE_RUN_STATUSES={"queued","in_progress","pending","waiting","requested"}

class ClockError(RuntimeError): pass
def req(ok:bool,msg:str)->None:
    if not ok: raise ClockError(msg)
def load_policy()->dict[str,Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))
def parse_time(value:str)->datetime:
    req(isinstance(value,str) and value.endswith("Z"),"clock timestamp invalid")
    try: result=datetime.fromisoformat(value[:-1]+"+00:00")
    except ValueError as exc: raise ClockError("clock timestamp invalid") from exc
    return result.astimezone(timezone.utc)

class API:
    def __init__(self,token:str,max_requests:int):
        self.token=token;self.max_requests=max_requests;self.requests=0
    def call(self,path:str,method:str="GET",payload:dict|None=None)->dict:
        req(path.startswith("/") and ".." not in path and "://" not in path,"unsafe API path")
        req(method in {"GET","POST"},"unsupported API method")
        req(self.requests<self.max_requests,"clock API budget exhausted")
        if method=="POST":
            req(re.fullmatch(r"/actions/workflows/[A-Za-z0-9._-]+/dispatches",path) is not None,
                "clock write destination not allowed")
        self.requests+=1
        data=None if payload is None else json.dumps(payload,separators=(",",":")).encode()
        request=urllib.request.Request(
            "https://api.github.com/repos/"+REPO+path,data=data,method=method,
            headers={"Accept":"application/vnd.github+json","Authorization":"Bearer "+self.token,
                     "X-GitHub-Api-Version":"2022-11-28","User-Agent":"portfolio-schedule-clock/1.0",
                     **({"Content-Type":"application/json"} if data is not None else {})})
        with urllib.request.urlopen(request,timeout=20) as response:
            body=response.read(2_000_001)
        req(len(body)<=2_000_000,"clock provider response too large")
        return json.loads(body) if body else {}


def _exact_main_runs(doc:dict,main_sha:str,label:str)->list[dict]:
    rows=doc.get("workflow_runs",[])
    req(isinstance(rows,list),f"{label} run listing malformed")
    return [row for row in rows
            if row.get("head_branch")=="main" and row.get("head_sha")==main_sha]

def reducer_liveness_wake(api:API,main_sha:str)->dict:
    """Explicitly wake the reducer when token-dispatched producers outpace canonical state.

    workflow_dispatch is intentionally allowed for GITHUB_TOKEN-created work, but
    relying on a second-hop workflow_run after that dispatched work is not a
    durable wake path. The clock therefore performs one bounded, idempotent
    reducer wake whenever exact-main producer completion is newer than the latest
    successful exact-main reducer completion. Production readers still fail closed and
    independently verify that the resulting snapshot covers every pending event.
    """
    reducer_doc=api.call(f"/actions/workflows/{REDUCER_WORKFLOW_FILE}/runs?branch=main&per_page=20")
    reducers=_exact_main_runs(reducer_doc,main_sha,"reducer")
    active=[row for row in reducers if row.get("status") in ACTIVE_RUN_STATUSES and type(row.get("id")) is int]
    if active:
        return {"action":"REDUCER_ACTIVE","evidence_run_ids":sorted(row["id"] for row in active)}

    successes=[row for row in reducers
               if row.get("status")=="completed"
               and row.get("conclusion")=="success"
               and type(row.get("id")) is int]
    if successes:
        for row in successes:
            req(isinstance(row.get("updated_at"),str),"reducer completion timestamp invalid")
        latest=max(successes,key=lambda row:parse_time(row["updated_at"]))
        boundary=parse_time(latest["updated_at"])
        latest_reducer_run_id=latest["id"]
    else:
        boundary=None
        latest_reducer_run_id=None

    stale=[]
    for workflow in sorted(WORKFLOW_PRODUCERS):
        doc=api.call(f"/actions/workflows/{workflow}.yml/runs?branch=main&per_page=5")
        rows=_exact_main_runs(doc,main_sha,f"{workflow} producer")
        for row in rows:
            if row.get("status")!="completed" or row.get("conclusion") not in TERMINAL_CONCLUSIONS:
                continue
            updated=row.get("updated_at")
            req(isinstance(updated,str),"producer completion timestamp invalid")
            if boundary is None or parse_time(updated)>boundary:
                req(type(row.get("id")) is int,"producer run identity invalid")
                stale.append(row["id"])
                break

    if not stale and latest_reducer_run_id is not None:
        return {"action":"REDUCER_CURRENT","latest_reducer_run_id":latest_reducer_run_id}

    api.call(f"/actions/workflows/{REDUCER_WORKFLOW_FILE}/dispatches","POST",{"ref":"main"})
    return {
        "action":"REDUCER_WAKE_REQUESTED",
        "reason":"NO_SUCCESSFUL_EXACT_MAIN_REDUCER" if latest_reducer_run_id is None else "PRODUCER_NEWER_THAN_LATEST_REDUCER",
        "latest_reducer_run_id":latest_reducer_run_id,
        "producer_run_ids":sorted(stale),
    }

def due(cadence:str,at:datetime)->bool:
    if cadence=="HOURLY": return True
    if cadence=="EVERY_2_HOURS": return at.hour%2==0
    if cadence=="EVERY_6_HOURS": return at.hour%6==0
    if cadence=="DAILY_04_UTC": return at.hour==4
    raise ClockError("unknown cadence")

def source_identity(policy:dict,run:dict,main_sha:str,current_run_id:int|None=None)->dict:
    matches=[row for row in policy["source_workflows"]
             if row["name"]==run.get("name") and row["path"]==run.get("path")]
    req(len(matches)==1,"untrusted schedule clock source")
    req(run.get("event") in matches[0]["events"],"clock source is not native schedule")
    req(run.get("head_branch")=="main","clock source not on main")
    req(run.get("head_sha")==main_sha,"clock source is not exact current main")
    req(type(run.get("id")) is int,"clock source id invalid")
    inflight_self=(
        current_run_id is not None
        and run["id"]==current_run_id
        and run.get("name")=="portfolio-schedule-delivery"
        and run.get("event")=="schedule"
        and run.get("status") in {"queued","in_progress","pending","waiting","requested"}
    )
    req(run.get("status")=="completed" or inflight_self,
        "clock source is neither completed carrier nor authenticated in-flight self schedule")
    return matches[0]

def recent_runs(api:API,target:dict,at:datetime,main_sha:str,minutes:int)->list[dict]:
    encoded=urllib.parse.quote(target["file"],safe="")
    cutoff=at-timedelta(minutes=minutes)
    rows=[]
    for event in ("schedule","workflow_dispatch"):
        doc=api.call(f"/actions/workflows/{encoded}/runs?event={event}&branch=main&per_page=20")
        batch=doc.get("workflow_runs",[])
        req(isinstance(batch,list),"clock target run listing malformed")
        rows.extend(row for row in batch
                    if row.get("head_branch")=="main"
                    and row.get("head_sha")==main_sha
                    and isinstance(row.get("created_at"),str)
                    and parse_time(row["created_at"])>=cutoff)
    return rows

def daemon_identity(api:API,run_id:int,attempt:int,main_sha:str,tick_epoch:int)->dict:
    run=api.call(f"/actions/runs/{run_id}")
    req(run.get("name")=="portfolio-schedule-clock-daemon"
        and run.get("path")==".github/workflows/portfolio-schedule-clock-daemon.yml",
        "untrusted clock daemon source")
    req(run.get("event") in {"push","workflow_dispatch"} and run.get("head_branch")=="main",
        "clock daemon source event/ref invalid")
    req(run.get("head_sha")==main_sha,"clock daemon is not exact current main")
    req(run.get("run_attempt")==attempt,"clock daemon attempt mismatch")
    req(run.get("status") in {"queued","in_progress","pending","waiting","requested"},
        "clock daemon is not an active parent generation")
    now=int(time.time())
    req(tick_epoch%600==0 and tick_epoch<=now+120 and now-tick_epoch<=1200,
        "clock daemon tick is not a recent aligned ten-minute boundary")
    return run

def execute(api:API,policy:dict,source_run:dict,main_sha:str,current_run_id:int|None=None,
            at_override:datetime|None=None,source_label:str|None=None)->dict:
    source=source_identity(policy,source_run,main_sha,current_run_id=current_run_id)
    at=at_override or parse_time(source_run["created_at"])
    reducer_wake=reducer_liveness_wake(api,main_sha)
    dispatch_count=1 if reducer_wake["action"]=="REDUCER_WAKE_REQUESTED" else 0
    actions=[]
    for target in policy["target_workflows"]:
        if target["file"]==REDUCER_WORKFLOW_FILE and reducer_wake["action"] in {"REDUCER_WAKE_REQUESTED","REDUCER_ACTIVE"}:
            actions.append({"workflow":target["name"],"action":"REDUCER_ALREADY_WOKEN_OR_ACTIVE",
                            "wake_action":reducer_wake["action"]})
            continue
        if not due(target["cadence"],at):
            actions.append({"workflow":target["name"],"action":"NOT_DUE","cadence":target["cadence"]})
            continue
        recent=recent_runs(api,target,at,main_sha,policy["dedupe_window_minutes"])
        if recent:
            actions.append({"workflow":target["name"],"action":"ALREADY_RAN_IN_SLOT",
                            "evidence_run_ids":sorted({row["id"] for row in recent})})
            continue
        if dispatch_count>=policy["max_dispatches_per_tick"]:
            actions.append({"workflow":target["name"],"action":"DISPATCH_BUDGET_EXHAUSTED"})
            break
        api.call(f"/actions/workflows/{target['file']}/dispatches","POST",{"ref":"main"})
        dispatch_count+=1
        actions.append({"workflow":target["name"],"action":"DISPATCH_REQUESTED"})
    return {
        "schema_version":"1.0.0","clock_id":policy["clock_id"],"status":"PASS",
        "authority_granted":False,"dispatch_authority_effect":"NONE",
        "source_run_id":source_run["id"],"source_workflow":source_label or source["name"],
        "source_event":source_run["event"],"source_head_sha":source_run.get("head_sha"),
        "source_created_at":source_run["created_at"],"tick_at":at.isoformat().replace("+00:00","Z"),
        "main_sha":main_sha,
        "reducer_wake":reducer_wake,
        "actions":actions,"api_requests":api.requests,
    }

def main()->int:
    ap=argparse.ArgumentParser()
    source=ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-run-id",type=int)
    source.add_argument("--daemon-run-id",type=int)
    ap.add_argument("--daemon-run-attempt",type=int)
    ap.add_argument("--tick-epoch",type=int)
    ap.add_argument("--output",type=Path,default=Path("operations/out/schedule_clock_receipt.json"))
    args=ap.parse_args()
    policy=load_policy()
    req(policy["authority_class"]=="NONE" and policy["dispatch_authority_effect"]=="NONE",
        "clock authority widened")
    api=API(os.environ["GITHUB_TOKEN"],policy["max_api_requests"])
    main_sha=api.call("/branches/main")["commit"]["sha"]
    current_run_id=int(os.environ["GITHUB_RUN_ID"])
    if args.daemon_run_id is not None:
        req(type(args.daemon_run_attempt) is int and type(args.tick_epoch) is int,
            "daemon clock inputs incomplete")
        daemon=daemon_identity(api,args.daemon_run_id,args.daemon_run_attempt,main_sha,args.tick_epoch)
        synthetic={
            "id":daemon["id"],"name":"portfolio-schedule-delivery",
            "path":".github/workflows/portfolio-schedule-delivery.yml",
            "event":"schedule","head_branch":"main","head_sha":main_sha,
            "status":"completed","created_at":datetime.fromtimestamp(args.tick_epoch,timezone.utc).isoformat().replace("+00:00","Z"),
        }
        result=execute(
            api,policy,synthetic,main_sha,
            at_override=datetime.fromtimestamp(args.tick_epoch,timezone.utc),
            source_label="portfolio-schedule-clock-daemon",
        )
        result["daemon_run_id"]=args.daemon_run_id
        result["daemon_run_attempt"]=args.daemon_run_attempt
    else:
        source_run=api.call(f"/actions/runs/{args.source_run_id}")
        req(current_run_id==args.source_run_id or source_run.get("status")=="completed",
            "non-current carrier source must already be completed")
        result=execute(api,policy,source_run,main_sha,current_run_id=current_run_id)
    req(api.call("/branches/main")["commit"]["sha"]==main_sha,"main moved during clock tick")
    result["api_requests"]=api.requests
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,sort_keys=True))
    return 0

if __name__=="__main__": raise SystemExit(main())
