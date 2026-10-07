"""Wait for the orchestrator's exact pre-arm reducer barrier.

The caller already owns the serialized writer lane. It does not dispatch or
mutate GitHub state; it waits for the reducer barrier correlated to this target,
requires exact-main success, and independently verifies pending_events == 0
before canonical reads begin.
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

ALLOWED_TARGETS={"runtime-hourly-sync","portfolio-autonomous-scheduler","hunter-autonomous-cycle","agent-heartbeat-sweep","portfolio-notification-cycle","command-center-pages"}
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
        req(self.requests<=180,"pre-arm barrier wait API budget exhausted")
        request=urllib.request.Request(
            "https://api.github.com/repos/"+self.repo+path,
            headers={
                "Authorization":"Bearer "+self.token,
                "Accept":"application/vnd.github+json",
                "X-GitHub-Api-Version":"2022-11-28",
                "User-Agent":"portfolio-step23-barrier-wait/1.0",
            },
        )
        with urllib.request.urlopen(request,timeout=30) as response:
            raw=response.read(5_000_001)
        req(len(raw)<=5_000_000,"provider response too large")
        return json.loads(raw)


def assert_main(api: API,exact_sha: str)->None:
    observed=api.get("/branches/main").get("commit",{}).get("sha")
    req(observed==exact_sha,f"PREARM_MAIN_MOVED expected={exact_sha} observed={observed}")


def main()->None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target",required=True,choices=sorted(ALLOWED_TARGETS))
    parser.add_argument("--exact-sha",required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()

    repo=os.environ.get("GITHUB_REPOSITORY","")
    token=os.environ.get("GITHUB_TOKEN","")
    prearm_id=os.environ.get("STEP23_PREARM_ID","")
    req(repo and token,"GitHub context required for reducer barrier wait")
    req(PREARM_ID.fullmatch(prearm_id) is not None,"reducer barrier wait is pre-arm only")
    req(len(args.exact_sha)==40,"exact main SHA malformed")

    api=API(repo,token)
    assert_main(api,args.exact_sha)
    expected=prearm_id+"-livebarrier"
    encoded=urllib.parse.quote(REDUCER_FILE,safe="")
    deadline=time.monotonic()+180
    selected=None
    while time.monotonic()<deadline:
        rows=api.get(
            f"/actions/workflows/{encoded}/runs?event=workflow_dispatch&branch=main&per_page=50"
        ).get("workflow_runs",[])
        req(isinstance(rows,list),"reducer barrier run listing malformed")
        matches=[
            row for row in rows
            if row.get("event")=="workflow_dispatch"
            and row.get("head_branch")=="main"
            and row.get("head_sha")==args.exact_sha
            and row.get("display_title")==expected
            and type(row.get("id")) is int
        ]
        req(len(matches)<=1,"ambiguous reducer barrier run")
        if matches:
            selected=matches[0]
            break
        time.sleep(3)
    req(selected is not None,"timed out locating reducer barrier run")

    run_id=int(selected["id"])
    deadline=time.monotonic()+600
    while time.monotonic()<deadline:
        row=api.get(f"/actions/runs/{run_id}")
        if row.get("status")=="completed":
            req(row.get("conclusion")=="success",
                f"reducer barrier run {run_id} concluded {row.get('conclusion')}")
            req(row.get("head_sha")==args.exact_sha and row.get("event")=="workflow_dispatch",
                "reducer barrier identity drifted")
            break
        time.sleep(5)
    else:
        raise RuntimeError(f"timed out waiting for reducer barrier run {run_id}")

    pending=pending_event_count(token)
    req(pending==0,f"reducer barrier left {pending} pending events")
    assert_main(api,args.exact_sha)

    result={
        "schema_version":"1.0.0",
        "status":"PASS",
        "target":args.target,
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
