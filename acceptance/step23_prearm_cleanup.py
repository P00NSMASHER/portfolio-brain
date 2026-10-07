"""Remove non-counting pre-arm workflow runs whose title captured credential material."""
# Retrigger marker: post-#629 reducer-zombie cleanup exact-main pre-arm, 2026-10-07.
# Retrigger marker: steady-barrier liveness repair verified; fresh exact-main pre-arm, 2026-10-07.
# Retrigger marker: reducer-liveness repair exact-main pre-arm, 2026-10-07.
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from state_journal.provider_quarantine import require_quarantined_reducer_identity

SECRET_MARKERS=("ghs_","gho_","ghu_","ghr_","github_pat_")
BLOCKER_PATHS={
    ".github/workflows/portfolio-state-reducer.yml",
    ".github/workflows/runtime-hourly-sync.yml",
    ".github/workflows/runtime-event-observe.yml",
    ".github/workflows/runtime-daily-learning.yml",
    ".github/workflows/runtime-weekly-synthesis.yml",
    ".github/workflows/portfolio-autonomous-scheduler.yml",
    ".github/workflows/hunter-autonomous-cycle.yml",
    ".github/workflows/agent-heartbeat-sweep.yml",
    ".github/workflows/portfolio-cost-watchdog.yml",
    ".github/workflows/portfolio-notification-cycle.yml",
    ".github/workflows/command-center-pages.yml",
    ".github/workflows/verified-feedback-bootstrap.yml",
}
STALE_CANCELLABLE_EVENTS={"workflow_run","push"}


def req(ok:bool,message:str)->None:
    if not ok:
        raise RuntimeError(message)


def leaked_title(value:Any)->bool:
    return isinstance(value,str) and value.startswith("prearm-") and any(marker in value for marker in SECRET_MARKERS)


def stale_non_schedule_blocker(row:dict[str,Any],exact_sha:str)->bool:
    return (
        type(row.get("id")) is int
        and row.get("head_branch")=="main"
        and row.get("head_sha")!=exact_sha
        and row.get("path") in BLOCKER_PATHS
        and row.get("status")!="completed"
        and (
            row.get("event") in STALE_CANCELLABLE_EVENTS
            or (
                row.get("event")=="workflow_dispatch"
                and isinstance(row.get("display_title"),str)
                and row["display_title"].startswith("prearm-")
            )
        )
    )


class API:
    def __init__(self,repo:str,token:str):
        self.repo=repo
        self.token=token
        self.requests=0

    def request(self,path:str,*,method:str="GET")->tuple[int,bytes]:
        req(path.startswith("/") and "://" not in path and ".." not in path,"unsafe GitHub API path")
        self.requests+=1
        req(self.requests<=80,"pre-arm cleanup API budget exhausted")
        request=urllib.request.Request(
            "https://api.github.com/repos/"+self.repo+path,
            method=method,
            headers={
                "Authorization":"Bearer "+self.token,
                "Accept":"application/vnd.github+json",
                "X-GitHub-Api-Version":"2022-11-28",
                "User-Agent":"portfolio-step23-prearm-cleanup/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request,timeout=20) as response:
                return response.status,response.read(5_000_001)
        except urllib.error.HTTPError as exc:
            return exc.code,exc.read(5_000_001)

    def get(self,path:str)->Any:
        status,raw=self.request(path)
        req(status==200,f"unexpected GitHub GET status {status}")
        return json.loads(raw)

    def post(self,path:str)->int:
        status,_=self.request(path,method="POST")
        return status

    def delete(self,path:str)->int:
        status,_=self.request(path,method="DELETE")
        return status


def _wait_stopped(api:API,run_id:int,label:str,*,attempts:int)->bool:
    req(1<=attempts<=30,"invalid pre-arm cleanup wait bound")
    for _ in range(attempts):
        current=api.get(f"/actions/runs/{run_id}")
        if current.get("status")=="completed":
            return True
        time.sleep(2)
    return False


def _provider_time(value:Any,label:str)->datetime:
    req(isinstance(value,str) and value,label+" timestamp missing")
    try:
        parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc:
        raise RuntimeError(label+" timestamp malformed") from exc
    req(parsed.tzinfo is not None,label+" timestamp lacks timezone")
    return parsed.astimezone(timezone.utc)


def _later_success_proves_zombie_inert(api:API,current:dict[str,Any],label:str)->int|None:
    """Return a later same-workflow success proving the ghost holds no scheduler lane."""
    run_id=current.get("id")
    workflow_id=current.get("workflow_id")
    path=current.get("path")
    req(type(run_id) is int and type(workflow_id) is int and isinstance(path,str) and path,
        label+" queued zombie identity malformed")
    created=_provider_time(current.get("created_at"),label+" queued zombie")
    doc=api.get(f"/actions/runs?branch=main&per_page=100")
    rows=doc.get("workflow_runs",[])
    req(isinstance(rows,list),"workflow run listing malformed")
    candidates=[]
    for row in rows:
        if (
            type(row.get("id")) is int
            and row["id"]!=run_id
            and row.get("workflow_id")==workflow_id
            and row.get("path")==path
            and row.get("head_branch")=="main"
            and row.get("status")=="completed"
            and row.get("conclusion")=="success"
            and _provider_time(row.get("created_at"),"successor run")>created
        ):
            candidates.append(row)
    if not candidates:
        return None
    candidates.sort(key=lambda row:(_provider_time(row["created_at"],"successor run"),row["id"]))
    return int(candidates[0]["id"])


def _delete_jobless_queued_zombie(api:API,run_id:int,label:str)->str|None:
    """Resolve only a provider-stuck queued run that has never received a job or artifact."""
    current=api.get(f"/actions/runs/{run_id}")
    if current.get("status")!="queued":
        return None
    jobs=api.get(f"/actions/runs/{run_id}/jobs?filter=all&per_page=100")
    rows=jobs.get("jobs",[])
    req(isinstance(rows,list),"workflow job listing malformed")
    total=jobs.get("total_count",len(rows))
    req(type(total) is int and total>=len(rows),"workflow job count malformed")
    if total!=0 or rows:
        return None
    artifacts=api.get(f"/actions/runs/{run_id}/artifacts?per_page=100")
    artifact_rows=artifacts.get("artifacts",[])
    artifact_total=artifacts.get("total_count",len(artifact_rows))
    req(isinstance(artifact_rows,list),"workflow artifact listing malformed")
    req(type(artifact_total) is int and artifact_total>=len(artifact_rows),
        "workflow artifact count malformed")
    if artifact_total!=0 or artifact_rows:
        return None
    deleted=api.delete(f"/actions/runs/{run_id}")
    if deleted==204:
        status,_=api.request(f"/actions/runs/{run_id}")
        req(status==404,f"{label} queued zombie run {run_id} remained visible after delete")
        return "DELETE_JOBLESS_QUEUE"
    if deleted in {403,409}:
        require_quarantined_reducer_identity(current)
        successor=_later_success_proves_zombie_inert(api,current,label)
        req(successor is not None,
            f"could not delete {label} queued zombie run {run_id}: {deleted}; "
            "no later successful same-workflow run proves it inert")
        return f"PROVEN_INERT_QUARANTINED_QUEUE:{successor}"
    raise RuntimeError(f"could not delete {label} queued zombie run {run_id}: {deleted}")

def _cancel_and_wait(api:API,run_id:int,label:str)->str:
    cancel=api.post(f"/actions/runs/{run_id}/cancel")
    req(cancel in {202,409},f"could not cancel {label} run {run_id}: {cancel}")
    if _wait_stopped(api,run_id,label,attempts=10):
        return "NORMAL_CANCEL"

    force=api.post(f"/actions/runs/{run_id}/force-cancel")
    req(force in {202,409},f"could not force-cancel {label} run {run_id}: {force}")
    if _wait_stopped(api,run_id,label,attempts=20):
        return "FORCE_CANCEL"
    resolution=_delete_jobless_queued_zombie(api,run_id,label)
    if resolution is not None:
        return resolution
    raise RuntimeError(f"{label} run {run_id} did not stop after force-cancel")


def purge(api:API,*,exact_sha:str)->dict[str,Any]:
    req(isinstance(exact_sha,str) and len(exact_sha)==40,"exact main SHA malformed")
    main=api.get("/branches/main")
    req(main.get("commit",{}).get("sha")==exact_sha,"PREARM_MAIN_MOVED")

    rows=[]
    for page in range(1,6):
        doc=api.get(f"/actions/runs?branch=main&per_page=100&page={page}")
        batch=doc.get("workflow_runs",[])
        req(isinstance(batch,list),"workflow run listing malformed")
        rows.extend(batch)
        if len(batch)<100:
            break

    leaked=[
        row for row in rows
        if type(row.get("id")) is int and leaked_title(row.get("display_title"))
    ]
    stale=[
        row for row in rows
        if stale_non_schedule_blocker(row,exact_sha)
        and not leaked_title(row.get("display_title"))
    ]

    deleted=[]
    cancelled_stale=[]
    force_cancelled=[]
    deleted_stale=[]
    proven_inert_stale=[]
    for row in leaked:
        run_id=int(row["id"])
        if row.get("status")!="completed":
            mode=_cancel_and_wait(api,run_id,"leaked pre-arm")
            if mode=="FORCE_CANCEL":
                force_cancelled.append(run_id)
        result=api.delete(f"/actions/runs/{run_id}")
        req(result==204,f"could not delete leaked pre-arm run {run_id}: {result}")
        deleted.append(run_id)

    for row in stale:
        run_id=int(row["id"])
        mode=_cancel_and_wait(api,run_id,"stale pre-arm blocker")
        if mode=="FORCE_CANCEL":
            force_cancelled.append(run_id)
        elif mode=="DELETE_JOBLESS_QUEUE":
            deleted_stale.append(run_id)
        elif mode.startswith("PROVEN_INERT_QUARANTINED_QUEUE:"):
            evidence_run_id=int(mode.rsplit(":",1)[1])
            proven_inert_stale.append({
                "run_id":run_id,
                "evidence_run_id":evidence_run_id,
            })
        cancelled_stale.append(run_id)

    main=api.get("/branches/main")
    req(main.get("commit",{}).get("sha")==exact_sha,"PREARM_MAIN_MOVED")
    return {
        "schema_version":"1.4.0",
        "status":"PASS",
        "exact_main_sha":exact_sha,
        "deleted_run_ids":deleted,
        "deleted_count":len(deleted),
        "cancelled_stale_run_ids":cancelled_stale,
        "cancelled_stale_count":len(cancelled_stale),
        "force_cancelled_run_ids":force_cancelled,
        "force_cancelled_count":len(force_cancelled),
        "deleted_stale_run_ids":deleted_stale,
        "deleted_stale_count":len(deleted_stale),
        "proven_inert_stale_run_ids":[row["run_id"] for row in proven_inert_stale],
        "proven_inert_stale_count":len(proven_inert_stale),
        "proven_inert_stale_evidence":proven_inert_stale,
        "api_requests":api.requests,
    }


def main()->None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--exact-sha",required=True)
    args=parser.parse_args()
    repo=os.environ.get("GITHUB_REPOSITORY","")
    token=os.environ.get("GITHUB_TOKEN","")
    req(repo and token,"GitHub context required for pre-arm cleanup")
    result=purge(API(repo,token),exact_sha=args.exact_sha)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
