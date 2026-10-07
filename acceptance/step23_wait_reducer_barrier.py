"""Wait for an exact-main reducer freshness barrier before canonical reads.

Pre-arm runs wait for the orchestrator-dispatched correlated reducer. Normal
steady-state writer runs wait for the reducer automatically triggered by the
writer workflow entering in_progress. This module is read-only: it never
dispatches or mutates GitHub state. In both modes it requires exact-main
identity, reducer success, and pending_events == 0 before allowing canonical
reads to begin.
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
    deadline=time.monotonic()+240
    selected=None
    while time.monotonic()<deadline:
        rows=api.get(
            f"/actions/workflows/{encoded}/runs?branch=main&per_page=100"
        ).get("workflow_runs",[])
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
        time.sleep(3)
    req(selected is not None,"timed out locating reducer barrier run")

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
        "schema_version":"1.1.0",
        "status":"PASS",
        "target":args.target,
        "barrier_kind":barrier_kind,
        "exact_main_sha":args.exact_sha,
        "barrier_run_id":run_id,
        "barrier_correlation":expected,
        "pending_events_final":0,
        "acceptance_credit":False,
        "api_requests":api.requests,
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
