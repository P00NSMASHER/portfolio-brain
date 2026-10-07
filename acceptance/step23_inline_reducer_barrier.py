"""Run a synchronous reducer barrier from a pre-arm writer job.

The caller already owns portfolio-state-writer-v1, so no producer can publish
new state while this helper drains the journal. This is pre-arm-only and grants
no Step 23 acceptance credit.
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

ALLOWED_TARGETS={"hunter-autonomous-cycle","command-center-pages"}
REDUCER_FILE="portfolio-state-reducer.yml"
PREARM_ID=re.compile(r"^prearm-[0-9]+-[a-z0-9-]+$")


def req(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


class API:
    def __init__(self, repo: str, token: str):
        self.repo=repo
        self.token=token
        self.requests=0

    def request(self, path: str, *, method: str="GET", payload: dict[str,Any] | None=None) -> tuple[int,bytes]:
        req(path.startswith("/") and "://" not in path and ".." not in path,"unsafe GitHub API path")
        self.requests+=1
        req(self.requests<=240,"inline reducer barrier API budget exhausted")
        body=None if payload is None else json.dumps(payload).encode()
        request=urllib.request.Request(
            "https://api.github.com/repos/"+self.repo+path,
            data=body,
            method=method,
            headers={
                "Authorization":"Bearer "+self.token,
                "Accept":"application/vnd.github+json",
                "X-GitHub-Api-Version":"2022-11-28",
                "Content-Type":"application/json",
                "User-Agent":"portfolio-step23-inline-barrier/1.0",
            },
        )
        with urllib.request.urlopen(request,timeout=30) as response:
            raw=response.read(5_000_001)
            status=response.status
        req(len(raw)<=5_000_000,"provider response too large")
        return status,raw

    def get(self,path: str)->Any:
        status,raw=self.request(path)
        req(status==200,f"unexpected GitHub GET status {status}")
        return json.loads(raw)

    def post(self,path: str,payload: dict[str,Any])->None:
        status,_=self.request(path,method="POST",payload=payload)
        req(status==204,f"unexpected GitHub dispatch status {status}")


def assert_main(api: API, exact_sha: str)->None:
    observed=api.get("/branches/main").get("commit",{}).get("sha")
    req(observed==exact_sha,f"PREARM_MAIN_MOVED expected={exact_sha} observed={observed}")


def run_reducer(api: API, *, exact_sha: str, correlation: str) -> dict[str,Any]:
    encoded=urllib.parse.quote(REDUCER_FILE,safe="")
    api.post(
        f"/actions/workflows/{encoded}/dispatches",
        {"ref":"main","inputs":{"prearm_id":correlation}},
    )
    deadline=time.monotonic()+180
    selected=None
    while time.monotonic()<deadline:
        rows=api.get(
            f"/actions/workflows/{encoded}/runs?event=workflow_dispatch&branch=main&per_page=50"
        ).get("workflow_runs",[])
        matches=[
            row for row in rows
            if row.get("event")=="workflow_dispatch"
            and row.get("head_branch")=="main"
            and row.get("head_sha")==exact_sha
            and row.get("display_title")==correlation
            and type(row.get("id")) is int
        ]
        req(len(matches)<=1,"ambiguous inline reducer barrier run")
        if matches:
            selected=matches[0]
            break
        time.sleep(3)
    req(selected is not None,"timed out locating inline reducer barrier run")
    run_id=int(selected["id"])
    deadline=time.monotonic()+600
    while time.monotonic()<deadline:
        row=api.get(f"/actions/runs/{run_id}")
        if row.get("status")=="completed":
            req(row.get("conclusion")=="success",
                f"inline reducer barrier run {run_id} concluded {row.get('conclusion')}")
            req(row.get("head_sha")==exact_sha and row.get("event")=="workflow_dispatch",
                "inline reducer barrier identity drifted")
            return row
        time.sleep(5)
    raise RuntimeError(f"timed out waiting for inline reducer barrier run {run_id}")


def main()->None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target",required=True,choices=sorted(ALLOWED_TARGETS))
    parser.add_argument("--exact-sha",required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()

    repo=os.environ.get("GITHUB_REPOSITORY","")
    token=os.environ.get("GITHUB_TOKEN","")
    parent=os.environ.get("GITHUB_RUN_ID","")
    prearm_id=os.environ.get("STEP23_PREARM_ID","")
    req(repo and token and parent,"GitHub context required for inline reducer barrier")
    req(PREARM_ID.fullmatch(prearm_id) is not None,"inline reducer barrier is pre-arm only")
    req(len(args.exact_sha)==40,"exact main SHA malformed")

    api=API(repo,token)
    assert_main(api,args.exact_sha)
    runs=[]
    pending_before=pending_event_count(token)
    for round_number in range(1,4):
        correlation=f"prearm-{parent}-{args.target}-inlinebarrier-{round_number}"
        row=run_reducer(api,exact_sha=args.exact_sha,correlation=correlation)
        runs.append({
            "run_id":row["id"],
            "conclusion":row["conclusion"],
            "head_sha":row["head_sha"],
            "correlation":correlation,
        })
        pending=pending_event_count(token)
        if pending==0:
            break
    else:
        raise RuntimeError("inline reducer barrier did not drain pending events")

    assert_main(api,args.exact_sha)
    result={
        "schema_version":"1.0.0",
        "status":"PASS",
        "target":args.target,
        "exact_main_sha":args.exact_sha,
        "pending_events_before":pending_before,
        "pending_events_final":0,
        "reducer_runs":runs,
        "acceptance_credit":False,
        "api_requests":api.requests,
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
