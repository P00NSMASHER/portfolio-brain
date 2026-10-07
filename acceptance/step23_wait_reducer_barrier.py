"""Wait for an exact-main reducer freshness barrier before canonical reads.

Pre-arm runs wait for the orchestrator-dispatched correlated reducer. Normal
steady-state writer runs prefer the reducer automatically triggered by the
writer workflow entering in_progress. If GitHub does not deliver that specific
workflow_run event, steady-state writers may accept another reducer completion
that became successful after the waiter started. This module is read-only: it
never dispatches or mutates GitHub state. In both modes it requires exact-main
identity, reducer success, and pending_events == 0 before allowing canonical
reads to begin. Pre-arm never uses the fallback.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from acceptance.step23_live_collect import pending_event_count

ALLOWED_TARGETS={
    "runtime-hourly-sync",
    "portfolio-autonomous-scheduler",
    "hunter-autonomous-cycle",
    "agent-heartbeat-sweep",
    "portfolio-cost-watchdog",
    "portfolio-notification-cycle",
    "command-center-pages",
}
PREARM_ID=re.compile(r"^prearm-[0-9]+-[a-z0-9-]+$")
REDUCER_FILE="portfolio-state-reducer.yml"


def req(ok: bool, message: str)->None:
    if not ok:
        raise RuntimeError(message)


class API:
    def __init__(self,repo: str,token: str):
        self.repo=repo
        self.token=token
        self.requests=0

    def get(self,path: str)->Any:
        req(path.startswith("/") and "://" not in path and ".." not in path,"unsafe GitHub API path")
        self.requests+=1
        req(self.requests<=220,"reducer barrier wait API budget exhausted")
        request=urllib.request.Request(
            "https://api.github.com/repos/"+self.repo+path,
            headers={
                "Authorization":"Bearer "+self.token,
                "Accept":"application/vnd.github+json",
                "X-GitHub-Api-Version":"2022-11-28",
                "User-Agent":"portfolio-reducer-barrier-wait/1.0",
            },
        )
        with urllib.request.urlopen(request,timeout=30) as response:
            raw=response.read(5_000_001)
        req(len(raw)<=5_000_000,"provider response too large")
        return json.loads(raw)


def assert_main(api: API,exact_sha: str)->None:
    observed=api.get("/branches/main").get("commit",{}).get("sha")
    req(observed==exact_sha,f"BARRIER_MAIN_MOVED expected={exact_sha} observed={observed}")


def reducer_success_key(row: dict[str,Any],exact_sha: str)->tuple[int,int,str]|None:
    """Return immutable completion identity for a valid exact-main success."""
    if row.get("status")!="completed" or row.get("conclusion")!="success":
        return None
    req(row.get("head_branch")=="main" and row.get("head_sha")==exact_sha,
        "fresh reducer success identity drifted")
    run_id=row.get("id")
    attempt=row.get("run_attempt",1)
    updated=row.get("updated_at")
    req(type(run_id) is int and run_id>0,"fresh reducer run identity malformed")
    req(type(attempt) is int and attempt>=1,"fresh reducer attempt malformed")
    req(isinstance(updated,str) and bool(updated),"fresh reducer completion time malformed")
    return (run_id,attempt,updated)


def reducer_success_keys(rows: list[dict[str,Any]],exact_sha: str)->set[tuple[int,int,str]]:
    keys=set()
    for row in rows:
        req(isinstance(row,dict),"reducer run row malformed")
        key=reducer_success_key(row,exact_sha)
        if key is not None:
            keys.add(key)
    return keys


def fresh_reducer_success(
    rows: list[dict[str,Any]],
    exact_sha: str,
    baseline: set[tuple[int,int,str]],
)->dict[str,Any]|None:
    """Newest exact-main reducer success not already complete at barrier entry."""
    fresh=[]
    for row in rows:
        req(isinstance(row,dict),"reducer run row malformed")
        key=reducer_success_key(row,exact_sha)
        if key is not None and key not in baseline:
            fresh.append((key,row))
    if not fresh:
        return None
    fresh.sort(key=lambda item:(item[0][0],item[0][1],item[0][2]),reverse=True)
    return fresh[0][1]


def main()->None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target",required=True,choices=sorted(ALLOWED_TARGETS))
    parser.add_argument("--exact-sha",required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()

    repo=os.environ.get("GITHUB_REPOSITORY","")
    token=os.environ.get("GITHUB_TOKEN","")
    prearm_id=os.environ.get("STEP23_PREARM_ID","")
    source_run_id=os.environ.get("GITHUB_RUN_ID","")
    source_attempt=os.environ.get("GITHUB_RUN_ATTEMPT","1")
    req(repo and token,"GitHub context required for reducer barrier wait")
    req(len(args.exact_sha)==40,"exact main SHA malformed")

    if prearm_id:
        req(PREARM_ID.fullmatch(prearm_id) is not None,"pre-arm reducer barrier id malformed")
        expected=prearm_id+"-livebarrier"
        expected_event="workflow_dispatch"
        barrier_kind="PREARM"
    else:
        req(source_run_id.isdigit() and source_attempt.isdigit(),"steady-state source run identity malformed")
        expected=f"writerbarrier-{source_run_id}-{source_attempt}-{args.target}"
        expected_event="workflow_run"
        barrier_kind="STEADY_STATE"

    api=API(repo,token)
    assert_main(api,args.exact_sha)
    encoded=urllib.parse.quote(REDUCER_FILE,safe="")
    listing_path=f"/actions/workflows/{encoded}/runs?branch=main&per_page=100"
    initial_rows=api.get(listing_path).get("workflow_runs",[])
    req(isinstance(initial_rows,list),"reducer barrier run listing malformed")
    baseline_successes=(
        reducer_success_keys(initial_rows,args.exact_sha)
        if barrier_kind=="STEADY_STATE"
        else set()
    )

    deadline=time.monotonic()+240
    selected=None
    fallback_used=False
    while time.monotonic()<deadline:
        rows=api.get(listing_path).get("workflow_runs",[])
        req(isinstance(rows,list),"reducer barrier run listing malformed")
        matches=[
            row for row in rows
            if row.get("event")==expected_event
            and row.get("head_branch")=="main"
            and row.get("head_sha")==args.exact_sha
            and row.get("display_title")==expected
            and type(row.get("id")) is int
        ]
        if matches:
            matches.sort(key=lambda row:int(row["id"]),reverse=True)
            selected=matches[0]
            break
        if barrier_kind=="STEADY_STATE":
            fresh=fresh_reducer_success(rows,args.exact_sha,baseline_successes)
            if fresh is not None and pending_event_count(token)==0:
                selected=fresh
                expected_event=str(fresh.get("event") or "")
                fallback_used=True
                break
        time.sleep(3)
    req(selected is not None,"timed out locating reducer barrier run or fresh reducer completion")

    run_id=int(selected["id"])
    deadline=time.monotonic()+420
    while time.monotonic()<deadline:
        row=api.get(f"/actions/runs/{run_id}")
        if row.get("status")=="completed":
            req(row.get("conclusion")=="success",
                f"reducer barrier run {run_id} concluded {row.get('conclusion')}")
            req(row.get("head_sha")==args.exact_sha and row.get("event")==expected_event,
                "reducer barrier identity drifted")
            break
        time.sleep(5)
    else:
        raise RuntimeError(f"timed out waiting for reducer barrier run {run_id}")

    pending=pending_event_count(token)
    req(pending==0,f"reducer barrier left {pending} pending events")
    assert_main(api,args.exact_sha)

    result={
        "schema_version":"1.2.0",
        "status":"PASS",
        "target":args.target,
        "barrier_kind":barrier_kind,
        "barrier_source":"FRESH_REDUCER_FALLBACK" if fallback_used else "CORRELATED",
        "exact_main_sha":args.exact_sha,
        "barrier_run_id":run_id,
        "barrier_correlation":selected.get("display_title"),
        "pending_events_final":0,
        "acceptance_credit":False,
        "api_requests":api.requests,
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
