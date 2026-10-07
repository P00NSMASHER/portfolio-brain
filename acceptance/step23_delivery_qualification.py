"""Redundant-clock qualification for Portfolio Brain Step 23.

Step 23 no longer waits for eight independent GitHub cron deliveries. One
genuine portfolio-schedule-delivery event=schedule run on the exact protected
main must prove the native scheduler path. Its cryptographically traceable
clock receipt then anchors a soak whose target workflow_dispatch runs must be
bound to exact redundant-clock receipts.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
CONTROL=ROOT/"operations"/"STEP23_CONTROL.json"
CANARY_NAME="portfolio-schedule-delivery"
CANARY_PATH=".github/workflows/portfolio-schedule-delivery.yml"


def req(ok:bool,msg:str)->None:
    if not ok:
        raise RuntimeError(msg)


def parse_time(value:str)->datetime:
    req(isinstance(value,str),"TIMESTAMP_MALFORMED")
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    req(dt.tzinfo is not None,"TIMESTAMP_NAIVE")
    return dt.astimezone(timezone.utc)


def ceil_quarter(value:datetime)->datetime:
    value=value.astimezone(timezone.utc).replace(second=0,microsecond=0)
    rem=value.minute%15
    if rem:
        value += timedelta(minutes=15-rem)
    return value


def derive_qualification(
    runs:list[dict[str,Any]],
    exact_sha:str,
    baseline:datetime,
    horizon_end:datetime,
    *,
    start_delay_minutes:int=30,
    soak_duration_seconds:int=25200,
)->dict[str,Any]:
    """Select the first genuine exact-main native clock canary.

    Independent target crons are deliberately not part of qualification. Their
    accepted evidence is produced later by the redundant clock or by genuine
    native target schedules during the soak.
    """
    req(re.fullmatch(r"[0-9a-f]{40}",exact_sha) is not None,"INVALID_EXACT_SHA")
    matches=[]
    for row in runs:
        if not isinstance(row,dict):
            continue
        if (row.get("name")==CANARY_NAME and row.get("path")==CANARY_PATH
            and row.get("head_branch")=="main" and row.get("head_sha")==exact_sha
            and row.get("event")=="schedule" and row.get("status")=="completed"
            and row.get("conclusion")=="success"):
            created=parse_time(row.get("created_at"))
            updated=parse_time(row.get("updated_at"))
            if created>=baseline and updated>=created and type(row.get("id")) is int:
                matches.append((created,row["id"],row,updated))
    if not matches:
        return {
            "status":"PREQUALIFYING",
            "qualified":False,
            "missing_workflows":[CANARY_NAME],
            "exact_main_sha":exact_sha,
            "baseline":baseline.isoformat().replace("+00:00","Z"),
            "selected":{},
        }

    matches.sort(key=lambda x:(x[0],x[1]))
    _,_,row,completed=matches[0]
    start=ceil_quarter(completed+timedelta(minutes=start_delay_minutes))
    if start+timedelta(seconds=soak_duration_seconds)>horizon_end:
        return {
            "status":"QUALIFICATION_TOO_LATE",
            "qualified":False,
            "missing_workflows":[],
            "exact_main_sha":exact_sha,
            "baseline":baseline.isoformat().replace("+00:00","Z"),
            "selected":{CANARY_NAME:{
                "run_id":row["id"],"created_at":row["created_at"],"completed_at":row["updated_at"],
            }},
            "candidate_start":start.isoformat().replace("+00:00","Z"),
        }
    return {
        "status":"QUALIFIED",
        "qualified":True,
        "missing_workflows":[],
        "exact_main_sha":exact_sha,
        "baseline":baseline.isoformat().replace("+00:00","Z"),
        "qualification_completed_at":completed.isoformat().replace("+00:00","Z"),
        "soak_start":start.isoformat().replace("+00:00","Z"),
        "soak_deadline":(start+timedelta(seconds=soak_duration_seconds)).isoformat().replace("+00:00","Z"),
        "selected":{CANARY_NAME:{
            "run_id":row["id"],"created_at":row["created_at"],"completed_at":row["updated_at"],
        }},
    }


def derive_fixed_arm(exact_sha:str,baseline:datetime,start:datetime,horizon_end:datetime)->dict[str,Any]:
    """Legacy helper retained for tests/tools that inspect historical fixed arms."""
    req(re.fullmatch(r"[0-9a-f]{40}",exact_sha) is not None,"INVALID_EXACT_SHA")
    start=start.astimezone(timezone.utc)
    req(start>=baseline,"FIXED_START_BEFORE_REGISTRATION")
    req(start.second==0 and start.microsecond==0 and start.minute%15==0,"FIXED_START_NOT_QUARTER_HOUR")
    req(start+timedelta(hours=1)<=horizon_end,"FIXED_START_OUTSIDE_HORIZON")
    return {
        "status":"QUALIFIED_FIXED","qualified":True,"missing_workflows":[],
        "exact_main_sha":exact_sha,"baseline":baseline.isoformat().replace("+00:00","Z"),
        "soak_start":start.isoformat().replace("+00:00","Z"),
        "soak_deadline":(start+timedelta(hours=1)).isoformat().replace("+00:00","Z"),
        "selected":{},
    }


class API:
    def __init__(self,repo:str,token:str):
        self.repo=repo
        self.token=token
        self.requests=0

    def _request(self,path:str)->bytes:
        req(path.startswith("/") and ".." not in path and "://" not in path,"UNSAFE_API_PATH")
        self.requests+=1
        req(self.requests<=30,"QUALIFICATION_API_BUDGET_EXHAUSTED")
        request=urllib.request.Request(
            "https://api.github.com/repos/"+self.repo+path,
            headers={
                "Authorization":"Bearer "+self.token,
                "Accept":"application/vnd.github+json",
                "X-GitHub-Api-Version":"2022-11-28",
                "User-Agent":"portfolio-step23-qualification/2.0",
            },
        )
        with urllib.request.urlopen(request,timeout=20) as response:
            data=response.read(10_000_001)
        req(len(data)<=10_000_000,"PROVIDER_RESPONSE_TOO_LARGE")
        return data

    def get(self,path:str)->Any:
        return json.loads(self._request(path))

    def bytes(self,path:str)->bytes:
        return self._request(path)


def collect_runs(api:API,baseline:datetime)->list[dict[str,Any]]:
    rows=[]
    seen=set()
    for page in range(1,6):
        doc=api.get(f"/actions/runs?branch=main&event=schedule&per_page=100&page={page}")
        batch=doc.get("workflow_runs")
        req(isinstance(batch,list),"RUN_LIST_MALFORMED")
        for row in batch:
            rid=row.get("id")
            req(type(rid) is int and rid not in seen,"RUN_PAGINATION_DRIFT")
            seen.add(rid)
            rows.append(row)
        if len(batch)<100:
            break
        if batch and parse_time(batch[-1]["created_at"])<baseline:
            break
    else:
        raise RuntimeError("RUN_LIST_INCOMPLETE")
    return rows


def sha256_bytes(raw:bytes)->str:
    return "sha256:"+hashlib.sha256(raw).hexdigest()


def zip_json(raw:bytes,basename:str)->Any:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        matches=[n for n in z.namelist() if n.rsplit("/",1)[-1]==basename]
        req(len(matches)==1,f"{basename} missing/ambiguous in artifact ZIP")
        return json.loads(z.read(matches[0]))


def validate_native_clock_canary(api:API,run:dict[str,Any],exact_sha:str)->dict[str,Any]:
    """Validate the clock artifact emitted by the genuine native schedule run."""
    run_id=run.get("id")
    req(type(run_id) is int and run_id>0,"CANARY_RUN_ID_INVALID")
    attempt=run.get("run_attempt",1)
    req(type(attempt) is int and attempt>=1,"CANARY_RUN_ATTEMPT_INVALID")
    doc=api.get(f"/actions/runs/{run_id}/artifacts?per_page=100")
    total=doc.get("total_count",0)
    req(type(total) is int and total<100,"CANARY_ARTIFACT_LIST_INCOMPLETE")
    expected=f"portfolio-schedule-clock-{run_id}-{attempt}"
    matches=[a for a in doc.get("artifacts",[]) if a.get("expired") is False and a.get("name")==expected]
    req(len(matches)==1,"CANARY_CLOCK_ARTIFACT_MISSING_OR_AMBIGUOUS")
    meta=matches[0]
    source=meta.get("workflow_run") or {}
    req(source.get("id")==run_id and source.get("head_sha")==exact_sha and source.get("head_branch")=="main",
        "CANARY_ARTIFACT_SOURCE_IDENTITY_MISMATCH")
    digest=meta.get("digest")
    req(isinstance(digest,str) and digest.startswith("sha256:") and len(digest)==71,
        "CANARY_PROVIDER_DIGEST_INVALID")
    raw=api.bytes(f"/actions/artifacts/{meta['id']}/zip")
    req(sha256_bytes(raw)==digest,"CANARY_ARTIFACT_DIGEST_MISMATCH")
    receipt=zip_json(raw,"schedule_clock_receipt.json")
    req(receipt.get("status")=="PASS","CANARY_CLOCK_STATUS_NOT_PASS")
    req(receipt.get("authority_granted") is False,"CANARY_CLOCK_AUTHORITY_WIDENED")
    req(receipt.get("dispatch_authority_effect")=="NONE","CANARY_CLOCK_EFFECT_WIDENED")
    req(receipt.get("main_sha")==exact_sha and receipt.get("source_head_sha")==exact_sha,
        "CANARY_CLOCK_MAIN_MISMATCH")
    req(receipt.get("source_run_id")==run_id,"CANARY_CLOCK_SOURCE_RUN_MISMATCH")
    req(receipt.get("source_workflow")==CANARY_NAME and receipt.get("source_event")=="schedule",
        "CANARY_CLOCK_SOURCE_NOT_NATIVE_SCHEDULE")
    wake=(receipt.get("reducer_wake") or {}).get("action")
    req(wake in {"REDUCER_CURRENT","REDUCER_ACTIVE","REDUCER_WAKE_REQUESTED"},
        "CANARY_REDUCER_LIVENESS_MISSING")
    return {
        "run_id":run_id,
        "workflow":CANARY_NAME,
        "event":"schedule",
        "head_sha":exact_sha,
        "created_at":run.get("created_at"),
        "completed_at":run.get("updated_at"),
        "artifact_id":meta.get("id"),
        "artifact_hash":digest,
        "clock_status":"PASS",
        "authority_granted":False,
        "dispatch_authority_effect":"NONE",
        "reducer_wake_action":wake,
    }


def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--exact-sha",required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()

    control=json.loads(CONTROL.read_text())
    req(control.get("status")=="REDUNDANT_CLOCK_PREQUALIFYING","STEP23_NOT_ARMABLE")
    repo=os.environ["GITHUB_REPOSITORY"]
    token=os.environ["GITHUB_TOKEN"]
    api=API(repo,token)

    main=api.get("/branches/main")
    req(main.get("commit",{}).get("sha")==args.exact_sha,"MAIN_MOVED")
    commit=api.get("/commits/"+args.exact_sha)
    commit_time=parse_time(commit["commit"]["committer"]["date"])
    baseline=commit_time+timedelta(minutes=int(control["registration_delay_minutes"]))
    horizon_end=commit_time+timedelta(hours=int(control["qualification_horizon_hours"]))
    soak_duration=int(control["soak_duration_seconds"])
    runs=collect_runs(api,baseline)
    result=derive_qualification(
        runs,args.exact_sha,baseline,horizon_end,
        start_delay_minutes=int(control["start_delay_minutes"]),
        soak_duration_seconds=soak_duration,
    )
    if result["qualified"]:
        canary_id=result["selected"][CANARY_NAME]["run_id"]
        canary=next((row for row in runs if row.get("id")==canary_id),None)
        req(isinstance(canary,dict),"CANARY_RUN_DISAPPEARED")
        result["native_scheduler_canary"]=validate_native_clock_canary(api,canary,args.exact_sha)
        result["qualification_method"]=control["qualification_method"]
        result["soak_duration_seconds"]=soak_duration

    req(api.get("/branches/main").get("commit",{}).get("sha")==args.exact_sha,"MAIN_MOVED")
    result.update(schema_version="2.0.0",api_requests=api.requests,acceptance_complete=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")

    gh=os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh,"a",encoding="utf-8") as fh:
            fh.write("qualified="+("true" if result["qualified"] else "false")+"\n")
            fh.write("status="+result["status"]+"\n")
            fh.write("soak_start="+str(result.get("soak_start",""))+"\n")
            fh.write("canary_run_id="+str((result.get("native_scheduler_canary") or {}).get("run_id",""))+"\n")
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
