"""Native scheduled-delivery qualification for Step 23.

A new soak is not armed until every required workflow has completed at least one
native event=schedule run successfully on the same exact main SHA after that
revision had time to register. The resulting start is deterministic from those
first successes, so later observer runs cannot move the clock.
"""
from __future__ import annotations
import argparse, json, os, re, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
CONTROL=ROOT/"operations"/"STEP23_CONTROL.json"
REQUIRED={
 "portfolio-state-reducer":".github/workflows/portfolio-state-reducer.yml",
 "runtime-hourly-sync":".github/workflows/runtime-hourly-sync.yml",
 "portfolio-cost-watchdog":".github/workflows/portfolio-cost-watchdog.yml",
 "portfolio-autonomous-scheduler":".github/workflows/portfolio-autonomous-scheduler.yml",
 "hunter-autonomous-cycle":".github/workflows/hunter-autonomous-cycle.yml",
 "agent-heartbeat-sweep":".github/workflows/agent-heartbeat-sweep.yml",
 "portfolio-notification-cycle":".github/workflows/portfolio-notification-cycle.yml",
 "command-center-pages":".github/workflows/command-center-pages.yml",
}

def req(ok:bool,msg:str)->None:
    if not ok: raise RuntimeError(msg)

def parse_time(value:str)->datetime:
    req(isinstance(value,str),"TIMESTAMP_MALFORMED")
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    req(dt.tzinfo is not None,"TIMESTAMP_NAIVE")
    return dt.astimezone(timezone.utc)

def ceil_quarter(value:datetime)->datetime:
    value=value.astimezone(timezone.utc).replace(second=0,microsecond=0)
    rem=value.minute%15
    if rem: value += timedelta(minutes=15-rem)
    return value

def derive_qualification(runs:list[dict[str,Any]], exact_sha:str, baseline:datetime,
                         horizon_end:datetime, *, start_delay_minutes:int=30,
                         soak_duration_seconds:int=7200)->dict[str,Any]:
    req(re.fullmatch(r"[0-9a-f]{40}",exact_sha) is not None,"INVALID_EXACT_SHA")
    selected={}
    for name,path in REQUIRED.items():
        matches=[]
        for row in runs:
            if not isinstance(row,dict): continue
            if (row.get("name")==name and row.get("path")==path
                and row.get("head_branch")=="main" and row.get("head_sha")==exact_sha
                and row.get("event")=="schedule" and row.get("status")=="completed"
                and row.get("conclusion")=="success"):
                created=parse_time(row.get("created_at"))
                updated=parse_time(row.get("updated_at"))
                if created>=baseline and updated>=created and type(row.get("id")) is int:
                    matches.append((created,row["id"],row,updated))
        if matches:
            matches.sort(key=lambda x:(x[0],x[1]))
            _,_,row,updated=matches[0]
            selected[name]={"run_id":row["id"],"created_at":row["created_at"],"completed_at":row["updated_at"]}
    missing=sorted(set(REQUIRED)-set(selected))
    if missing:
        return {"status":"PREQUALIFYING","qualified":False,"missing_workflows":missing,
                "exact_main_sha":exact_sha,"baseline":baseline.isoformat().replace("+00:00","Z"),
                "selected":selected}
    completed=max(parse_time(v["completed_at"]) for v in selected.values())
    start=ceil_quarter(completed+timedelta(minutes=start_delay_minutes))
    duration=timedelta(seconds=soak_duration_seconds)
    req(soak_duration_seconds == 7200,"STEP23_DURATION_CONTRACT_DRIFT")
    if start+duration>horizon_end:
        return {"status":"QUALIFICATION_TOO_LATE","qualified":False,"missing_workflows":[],
                "exact_main_sha":exact_sha,"baseline":baseline.isoformat().replace("+00:00","Z"),
                "selected":selected,"candidate_start":start.isoformat().replace("+00:00","Z")}
    return {"status":"QUALIFIED","qualified":True,"missing_workflows":[],
            "exact_main_sha":exact_sha,"baseline":baseline.isoformat().replace("+00:00","Z"),
            "qualification_completed_at":completed.isoformat().replace("+00:00","Z"),
            "soak_start":start.isoformat().replace("+00:00","Z"),
            "soak_deadline":(start+duration).isoformat().replace("+00:00","Z"),
            "selected":selected}

def derive_fixed_arm(exact_sha:str, baseline:datetime, start:datetime, horizon_end:datetime,
                     *, soak_duration_seconds:int=7200)->dict[str,Any]:
    req(re.fullmatch(r"[0-9a-f]{40}",exact_sha) is not None,"INVALID_EXACT_SHA")
    start=start.astimezone(timezone.utc)
    req(start>=baseline,"FIXED_START_BEFORE_REGISTRATION")
    req(start.second==0 and start.microsecond==0 and start.minute%15==0,"FIXED_START_NOT_QUARTER_HOUR")
    req(soak_duration_seconds == 7200,"STEP23_DURATION_CONTRACT_DRIFT")
    duration=timedelta(seconds=soak_duration_seconds)
    req(start+duration<=horizon_end,"FIXED_START_OUTSIDE_HORIZON")
    return {"status":"QUALIFIED_FIXED","qualified":True,"missing_workflows":[],
            "exact_main_sha":exact_sha,"baseline":baseline.isoformat().replace("+00:00","Z"),
            "soak_start":start.isoformat().replace("+00:00","Z"),
            "soak_deadline":(start+duration).isoformat().replace("+00:00","Z"),
            "selected":{}}

class API:
    def __init__(self,repo:str,token:str): self.repo=repo; self.token=token; self.requests=0
    def get(self,path:str)->Any:
        req(path.startswith("/") and ".." not in path and "://" not in path,"UNSAFE_API_PATH")
        self.requests+=1; req(self.requests<=20,"QUALIFICATION_API_BUDGET_EXHAUSTED")
        request=urllib.request.Request("https://api.github.com/repos/"+self.repo+path,headers={
            "Authorization":"Bearer "+self.token,"Accept":"application/vnd.github+json",
            "X-GitHub-Api-Version":"2022-11-28","User-Agent":"portfolio-step23-qualification/1.0"})
        with urllib.request.urlopen(request,timeout=20) as response:
            data=response.read(5_000_001)
        req(len(data)<=5_000_000,"PROVIDER_RESPONSE_TOO_LARGE")
        return json.loads(data)

def collect_runs(api:API, baseline:datetime)->list[dict[str,Any]]:
    rows=[]; seen=set()
    for page in range(1,6):
        doc=api.get(f"/actions/runs?branch=main&event=schedule&per_page=100&page={page}")
        batch=doc.get("workflow_runs")
        req(isinstance(batch,list),"RUN_LIST_MALFORMED")
        for row in batch:
            rid=row.get("id"); req(type(rid) is int and rid not in seen,"RUN_PAGINATION_DRIFT")
            seen.add(rid); rows.append(row)
        if len(batch)<100: break
        if batch and parse_time(batch[-1]["created_at"])<baseline: break
    else: raise RuntimeError("RUN_LIST_INCOMPLETE")
    return rows

def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--exact-sha",required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    control=json.loads(CONTROL.read_text())
    req(control.get("status") in {"PREQUALIFYING","ARMED_FIXED"},"STEP23_NOT_ARMABLE")
    repo=os.environ["GITHUB_REPOSITORY"]; token=os.environ["GITHUB_TOKEN"]
    api=API(repo,token)
    main=api.get("/branches/main")
    req(main.get("commit",{}).get("sha")==args.exact_sha,"MAIN_MOVED")
    commit=api.get("/commits/"+args.exact_sha)
    commit_time=parse_time(commit["commit"]["committer"]["date"])
    baseline=max(commit_time+timedelta(minutes=int(control["registration_delay_minutes"])),
                 parse_time(control["qualification_horizon_start"]))
    horizon_end=parse_time(control["qualification_horizon_end"])
    if control["status"]=="ARMED_FIXED":
        result=derive_fixed_arm(
            args.exact_sha,baseline,parse_time(control["next_soak_start"]),horizon_end,
            soak_duration_seconds=int(control["max_soak_duration_seconds"]),
        )
        result["qualification_method"]=control["qualification_method"]
    else:
        result=derive_qualification(
            collect_runs(api,baseline),args.exact_sha,baseline,horizon_end,
            start_delay_minutes=int(control["start_delay_minutes"]),
            soak_duration_seconds=int(control["max_soak_duration_seconds"]))
    req(api.get("/branches/main").get("commit",{}).get("sha")==args.exact_sha,"MAIN_MOVED")
    result.update(schema_version="1.0.0",api_requests=api.requests,acceptance_complete=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    gh=os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh,"a",encoding="utf-8") as fh:
            fh.write("qualified="+("true" if result["qualified"] else "false")+"\n")
            fh.write("status="+result["status"]+"\n")
            fh.write("soak_start="+str(result.get("soak_start",""))+"\n")
    print(json.dumps(result,sort_keys=True))

if __name__=="__main__": main()
