#!/usr/bin/env python3
"""Redundant schedule clock that turns any trusted native schedule tick into bounded core dispatches.

The clock grants no portfolio authority. It only invokes existing workflow_dispatch
entrypoints, whose normal workload/cost/kill-switch/concurrency gates remain authoritative.
"""
from __future__ import annotations
import argparse,json,os,re,urllib.parse,urllib.request
from datetime import datetime,timedelta,timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
REPO="P00NSMASHER/portfolio-brain"
POLICY_PATH=ROOT/"operations/SCHEDULE_CLOCK_POLICY.json"

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

def due(cadence:str,at:datetime)->bool:
    if cadence=="HOURLY": return True
    if cadence=="EVERY_2_HOURS": return at.hour%2==0
    if cadence=="EVERY_6_HOURS": return at.hour%6==0
    if cadence=="DAILY_04_UTC": return at.hour==4
    raise ClockError("unknown cadence")

def source_identity(policy:dict,run:dict)->dict:
    matches=[row for row in policy["source_workflows"]
             if row["name"]==run.get("name") and row["path"]==run.get("path")]
    req(len(matches)==1,"untrusted schedule clock source")
    req(run.get("event") in matches[0]["events"],"clock source is not native schedule")
    req(run.get("head_branch")=="main","clock source not on main")
    req(run.get("status")=="completed","clock source not terminal")
    req(type(run.get("id")) is int,"clock source id invalid")
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

def execute(api:API,policy:dict,source_run:dict,main_sha:str)->dict:
    source=source_identity(policy,source_run)
    at=parse_time(source_run["created_at"])
    actions=[]
    for target in policy["target_workflows"]:
        if not due(target["cadence"],at):
            actions.append({"workflow":target["name"],"action":"NOT_DUE","cadence":target["cadence"]})
            continue
        recent=recent_runs(api,target,at,main_sha,policy["dedupe_window_minutes"])
        if recent:
            actions.append({"workflow":target["name"],"action":"ALREADY_RAN_IN_SLOT",
                            "evidence_run_ids":sorted({row["id"] for row in recent})})
            continue
        api.call(f"/actions/workflows/{target['file']}/dispatches","POST",{"ref":"main"})
        actions.append({"workflow":target["name"],"action":"DISPATCH_REQUESTED"})
        if sum(1 for row in actions if row["action"]=="DISPATCH_REQUESTED")>=policy["max_dispatches_per_tick"]:
            break
    return {
        "schema_version":"1.0.0","clock_id":policy["clock_id"],"status":"PASS",
        "authority_granted":False,"dispatch_authority_effect":"NONE",
        "source_run_id":source_run["id"],"source_workflow":source["name"],
        "source_event":source_run["event"],"source_head_sha":source_run.get("head_sha"),
        "source_created_at":source_run["created_at"],"main_sha":main_sha,
        "actions":actions,"api_requests":api.requests,
    }

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--source-run-id",required=True,type=int)
    ap.add_argument("--output",type=Path,default=Path("operations/out/schedule_clock_receipt.json"))
    args=ap.parse_args()
    policy=load_policy()
    req(policy["authority_class"]=="NONE" and policy["dispatch_authority_effect"]=="NONE",
        "clock authority widened")
    api=API(os.environ["GITHUB_TOKEN"],policy["max_api_requests"])
    main_sha=api.call("/branches/main")["commit"]["sha"]
    source=api.call(f"/actions/runs/{args.source_run_id}")
    result=execute(api,policy,source,main_sha)
    req(api.call("/branches/main")["commit"]["sha"]==main_sha,"main moved during clock tick")
    result["api_requests"]=api.requests
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,sort_keys=True))
    return 0

if __name__=="__main__": raise SystemExit(main())
