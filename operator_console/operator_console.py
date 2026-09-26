#!/usr/bin/env python3
"""Authenticated manual operator-control helpers.

This module is only invoked by the workflow_dispatch Operator Console. It is
not imported by or published with the public Pages UI.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cost_governor.cancel_managed_jobs import managed_run_ids
from cost_governor.cost_governor import validate_policy
from dashboard.operational_telemetry import build_operational_telemetry
from scheduler.autonomous_scheduler import load_state as load_scheduler_state, mark_work, validate_state as validate_scheduler_state

ROOT=Path(__file__).resolve().parents[1]


class OperatorConsoleError(ValueError):
    pass


def req(ok:bool,msg:str)->None:
    if not ok:raise OperatorConsoleError(msg)


def load_json(path:str|Path)->dict[str,Any]:
    p=Path(path)
    if not p.is_absolute():p=ROOT/p
    return json.loads(p.read_text(encoding="utf-8"))


def policy()->dict[str,Any]:
    return load_json("operator_console/OPERATOR_POLICY.json")


def actor()->str:
    return os.environ.get("GITHUB_ACTOR","")


def validate_actor(value:str|None=None)->str:
    value=value or actor()
    req(value in policy()["allowed_actors"],"operator actor is not allowlisted")
    return value


def _request(url:str,token:str,*,method:str="GET",body:dict[str,Any]|None=None)->bytes:
    payload=None if body is None else json.dumps(body).encode("utf-8")
    request=urllib.request.Request(
        url,data=payload,method=method,
        headers={
            "Accept":"application/vnd.github+json",
            "Authorization":f"Bearer {token}",
            "X-GitHub-Api-Version":"2022-11-28",
            "User-Agent":"portfolio-brain-operator-console/1.0",
            **({"Content-Type":"application/json"} if payload is not None else {}),
        },
    )
    with urllib.request.urlopen(request,timeout=20) as response:return response.read()


def dispatch_workflow(operation:str,*,token:str,repo:str,transport=_request)->dict[str,Any]:
    validate_actor()
    p=policy();mapping=p["workflow_dispatch_map"]
    req(operation in mapping,"operation is not a rerunnable workflow")
    req(token and repo,"GitHub execution context required")
    workflow=mapping[operation]
    transport(
        f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches",
        token,method="POST",body={"ref":"main"},
    )
    return {"status":"DISPATCHED","operation":operation,"workflow":workflow,"ref":"main"}


def stop_running_autonomy(*,token:str,repo:str,current_run_id:str|None,transport=_request)->dict[str,Any]:
    validate_actor()
    req(token and repo,"GitHub execution context required")
    p=load_json("cost_governor/COST_GOVERNOR_POLICY.json")
    body=transport(f"https://api.github.com/repos/{repo}/actions/runs?per_page=100",token)
    runs=json.loads(body.decode("utf-8")).get("workflow_runs",[])
    ids=managed_run_ids(
        runs,current_run_id=current_run_id,
        managed_names=set(p["managed_workflow_names"]),
        limit=p["max_cancellations_per_cycle"],
    )
    for run_id in ids:
        transport(f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/cancel",token,method="POST")
    return {"status":"STOP_REQUESTED","cancelled_run_ids":ids,"count":len(ids)}


def cancel_queue_item(state_path:str|Path,work_id:str,output_path:str|Path)->dict[str,Any]:
    validate_actor()
    req(isinstance(work_id,str) and work_id.startswith("SWORK-"),"scheduler work id required")
    state=load_scheduler_state(str(state_path))
    matches=[w for w in state["work_items"] if w["scheduler_work_id"]==work_id]
    req(len(matches)==1,"scheduler work id missing or duplicate")
    work=matches[0]
    req(work["state"] in {"QUEUED","ACTIVE"},"only queued/active work can be cancelled")
    out=mark_work(state,work["fingerprint"],"CANCELLED")
    validate_scheduler_state(out)
    output=Path(output_path);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return {
        "status":"QUEUE_ITEM_CANCELLED",
        "work_id":work_id,
        "prior_state":work["state"],
        "project_ids":work["project_ids"],
        "assigned_agent_id":work["assigned_agent_id"],
    }


def _clean_reason(value:str)->str:
    value=(value or "").strip()
    req(1<=len(value)<=240,"operator reason must be 1-240 characters")
    req("\r" not in value and "\n" not in value,"operator reason must be one line")
    return value


def edit_kill_switch(target:str,desired_state:str,reason:str,*,at:str|None=None,actor_name:str|None=None)->dict[str,Any]:
    who=validate_actor(actor_name)
    cfg=policy()["kill_switch_targets"].get(target)
    req(cfg is not None,"unknown kill-switch target")
    req(desired_state in {"ENABLED","DISABLED"},"desired state must be ENABLED or DISABLED")
    reason=_clean_reason(reason)
    path=ROOT/cfg["path"];data=json.loads(path.read_text())
    data[cfg["field"]]=desired_state=="DISABLED"
    data["reason"]=reason if desired_state=="DISABLED" else None
    if "changed_at" in data:
        data["changed_at"]=at or datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
    if "changed_by" in data:data["changed_by"]=who
    path.write_text(json.dumps(data,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return {"status":"PROPOSAL_EDITED","target":target,"desired_state":desired_state,"path":cfg["path"]}


def edit_budget(cost_usd:float,model_calls:int,reason:str,*,actor_name:str|None=None)->dict[str,Any]:
    who=validate_actor(actor_name)
    p=policy();limits=p["budget_proposal_limits"]
    req(type(cost_usd) in {int,float} and 0<float(cost_usd)<=limits["cost_usd_max"],"cost proposal outside console limit")
    req(type(model_calls) is int and 0<model_calls<=limits["model_calls_max"],"model-call proposal outside console limit")
    reason=_clean_reason(reason)
    path=ROOT/"cost_governor/COST_GOVERNOR_POLICY.json";data=json.loads(path.read_text())
    data["portfolio_ceiling"]["cost_usd"]=float(cost_usd)
    data["portfolio_ceiling"]["model_calls"]=int(model_calls)
    data.setdefault("operator_change_provenance",{})
    data["operator_change_provenance"]={
        "proposed_by":who,
        "reason":reason,
        "execution_mode":"PULL_REQUEST_ONLY",
    }
    # validate_policy uses a closed policy schema, so provenance may not be a valid
    # contract field. Keep provenance in the PR body, not the policy itself.
    data.pop("operator_change_provenance",None)
    validate_policy(data)
    path.write_text(json.dumps(data,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return {
        "status":"PROPOSAL_EDITED","path":"cost_governor/COST_GOVERNOR_POLICY.json",
        "cost_usd":float(cost_usd),"model_calls":int(model_calls),"reason":reason,
    }


def status_summary(output:str|Path)->dict[str,Any]:
    validate_actor()
    telemetry=build_operational_telemetry()
    q=telemetry["queue"];cost=telemetry["cost"];cycles=telemetry["cycles"]
    lines=[
        "# Portfolio Brain Operator Console",
        "",
        f"- Generated: {telemetry['generated_at']}",
        f"- Open scheduler work: {q['open_total']} (queued {q['counts']['QUEUED']}, active {q['counts']['ACTIVE']})",
        f"- Terminal work: complete {q['counts']['COMPLETE']}, cancelled {q['counts']['CANCELLED']}",
        f"- Actual cost today: ${cost['actual_usage_today']['cost_usd']:.4f}",
        f"- Actual model calls today: {cost['actual_usage_today']['model_calls']}",
        f"- Governor-accounted runner minutes: {cost['budget_accounted_usage_today']['github_runner_minutes']}",
        f"- Active failure signals: {telemetry['failures']['count']}",
        f"- Sent action receipts: {telemetry['actions']['total_sent']}",
        f"- Verified external outcomes: {telemetry['verified_external_outcomes']}",
    ]
    latest=cycles.get("latest_overall")
    lines.append("- Last successful cycle: "+("none" if latest is None else f"{latest['subsystem']} {latest['cycle_id']} at {latest['finished_at']}"))
    lines += ["","## Agent heartbeats",""]
    for row in telemetry["agents"]["agents"]:
        lines.append(f"- {row['agent_id']}: {row['heartbeat_health']} · {row['last_heartbeat_at'] or 'never'} · {row['last_activity_kind'] or 'no activity'}")
    Path(output).write_text("\n".join(lines)+"\n",encoding="utf-8")
    return {"status":"STATUS_READY","open_work":q["open_total"],"failures":telemetry["failures"]["count"]}


def main()->None:
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="command",required=True)

    va=sub.add_parser("validate-actor");va.add_argument("--actor",default=None)
    st=sub.add_parser("status");st.add_argument("--output",required=True)
    di=sub.add_parser("dispatch");di.add_argument("--operation",required=True)
    sp=sub.add_parser("stop")
    cq=sub.add_parser("cancel-queue");cq.add_argument("--state",required=True);cq.add_argument("--work-id",required=True);cq.add_argument("--output",required=True)
    ks=sub.add_parser("edit-kill-switch");ks.add_argument("--target",required=True);ks.add_argument("--desired-state",required=True);ks.add_argument("--reason",required=True)
    bu=sub.add_parser("edit-budget");bu.add_argument("--cost-usd",type=float,required=True);bu.add_argument("--model-calls",type=int,required=True);bu.add_argument("--reason",required=True)

    a=ap.parse_args()
    if a.command=="validate-actor":result={"status":"AUTHORIZED","actor":validate_actor(a.actor)}
    elif a.command=="status":result=status_summary(a.output)
    elif a.command=="dispatch":result=dispatch_workflow(a.operation,token=os.environ.get("GITHUB_TOKEN",""),repo=os.environ.get("GITHUB_REPOSITORY",""))
    elif a.command=="stop":result=stop_running_autonomy(token=os.environ.get("GITHUB_TOKEN",""),repo=os.environ.get("GITHUB_REPOSITORY",""),current_run_id=os.environ.get("GITHUB_RUN_ID"))
    elif a.command=="cancel-queue":result=cancel_queue_item(a.state,a.work_id,a.output)
    elif a.command=="edit-kill-switch":result=edit_kill_switch(a.target,a.desired_state,a.reason)
    elif a.command=="edit-budget":result=edit_budget(a.cost_usd,a.model_calls,a.reason)
    else:raise OperatorConsoleError("unsupported command")
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
