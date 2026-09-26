#!/usr/bin/env python3
"""GitHub-authenticated Portfolio Brain operator console helpers.

The public command center never imports or invokes this module. The operator
workflow is owner-only and all persistent policy changes are proposed on a
branch/PR rather than silently mutating main.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cost_governor.cost_governor import validate_policy as validate_cost_policy
from dashboard.history_state import load_state as load_history_state, public_history
from dashboard.operational_telemetry import build_operational_telemetry
from scheduler.autonomous_scheduler import load_state as load_scheduler_state, mark_work, validate_state as validate_scheduler_state

ROOT=Path(__file__).resolve().parents[1]


class OperatorError(ValueError):pass


def req(ok:bool,msg:str)->None:
    if not ok:raise OperatorError(msg)


def _now()->str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")


def _safe_text(value:str,field:str,max_len:int=240)->str:
    req(isinstance(value,str) and 1<=len(value)<=max_len,f"{field} invalid")
    req("\n" not in value and "\r" not in value and "@" not in value,f"{field} must be sanitized")
    return value


def _reason_hash(reason:str)->str:
    req(isinstance(reason,str) and 1<=len(reason)<=500,"operator reason must be 1-500 characters")
    req("\n" not in reason and "\r" not in reason,"operator reason must be one line")
    return "sha256:"+hashlib.sha256(reason.encode()).hexdigest()


def load_json(path:str|Path)->Any:
    p=Path(path)
    if not p.is_absolute():p=ROOT/p
    return json.loads(p.read_text())


def write_json(path:str|Path,value:Any)->None:
    p=Path(path)
    if not p.is_absolute():p=ROOT/p
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n")


def validate_approval_ledger(doc:dict[str,Any])->None:
    req(set(doc)=={"schema_version","ledger_id","approvals"},"approval ledger fields changed")
    req(doc["schema_version"]=="1.0.0" and doc["ledger_id"]=="portfolio-owner-approvals","approval ledger identity mismatch")
    req(isinstance(doc["approvals"],list) and len(doc["approvals"])<=200,"approval ledger capacity invalid")
    seen=set()
    for row in doc["approvals"]:
        fields={"approval_id","source_ref","project_ids","approval_requirements","approved_by","approved_at","status","reason_hash"}
        req(set(row)==fields,"approval record fields changed")
        req(row["approval_id"].startswith("OAPR-") and row["approval_id"] not in seen,"approval id invalid");seen.add(row["approval_id"])
        _safe_text(row["source_ref"],"source_ref")
        req(isinstance(row["project_ids"],list) and row["project_ids"] and len(row["project_ids"])==len(set(row["project_ids"])),"approval project ids invalid")
        req(all(isinstance(x,str) and x.startswith("PRJ-") for x in row["project_ids"]),"approval project id invalid")
        req(isinstance(row["approval_requirements"],list) and row["approval_requirements"] and len(row["approval_requirements"])==len(set(row["approval_requirements"])),"approval requirements invalid")
        req(all(isinstance(x,str) and 1<=len(x)<=160 for x in row["approval_requirements"]),"approval requirement invalid")
        _safe_text(row["approved_by"],"approved_by")
        datetime.fromisoformat(row["approved_at"].replace("Z","+00:00"))
        req(row["status"] in {"ACTIVE","REVOKED"},"approval status invalid")
        req(isinstance(row["reason_hash"],str) and row["reason_hash"].startswith("sha256:"),"approval reason hash invalid")


def prepare_approval(*,source_ref:str,project_id:str,approval_code:str,actor:str,reason:str,at:str|None=None)->dict[str,Any]:
    source_ref=_safe_text(source_ref,"source_ref");project_id=_safe_text(project_id,"project_id")
    approval_code=_safe_text(approval_code,"approval_code");actor=_safe_text(actor,"actor")
    operator_policy=load_json("operator_console/OPERATOR_POLICY.json")
    req(actor in set(operator_policy.get("allowed_approval_actors") or []),"actor is not allowed to persist owner approval")
    req(project_id in {f"PRJ-{i:03d}" for i in range(12)},"unknown project")
    path=ROOT/"operator_console"/"OWNER_APPROVALS.json";doc=json.loads(path.read_text());validate_approval_ledger(doc)
    at=at or _now()
    core={"source_ref":source_ref,"project_ids":[project_id],"approval_requirements":[approval_code],"approved_by":actor,"approved_at":at}
    approval_id="OAPR-"+hashlib.sha256(json.dumps(core,sort_keys=True).encode()).hexdigest()[:20].upper()
    row={"approval_id":approval_id,**core,"status":"ACTIVE","reason_hash":_reason_hash(reason)}
    doc["approvals"]=[x for x in doc["approvals"] if not (x["source_ref"]==source_ref and x["project_ids"]==[project_id] and x["approval_requirements"]==[approval_code] and x["status"]=="ACTIVE")]
    doc["approvals"].append(row);validate_approval_ledger(doc);write_json(path,doc);return row


KILL_SWITCHES={
  "runtime":("runtime/KILL_SWITCH.json","disabled"),
  "scheduler":("scheduler/KILL_SWITCH.json","disabled"),
  "hunter":("hunting/KILL_SWITCH.json","disabled"),
  "notifications":("notifications/KILL_SWITCH.json","disabled"),
  "spend":("cost_governor/COST_KILL_SWITCH.json","spend_disabled"),
  "action":("action_engine/KILL_SWITCH.json","disabled"),
}


def prepare_kill_switch(*,subsystem:str,disabled:bool,actor:str,reason:str,at:str|None=None)->dict[str,Any]:
    req(subsystem in KILL_SWITCHES,"unknown kill-switch subsystem");actor=_safe_text(actor,"actor")
    path,field=KILL_SWITCHES[subsystem];doc=load_json(path);doc[field]=bool(disabled);doc["reason"]=None if not disabled else "operator-reason:"+_reason_hash(reason)
    if "changed_at" in doc:doc["changed_at"]=at or _now()
    if "changed_by" in doc:doc["changed_by"]=actor
    write_json(path,doc)
    return {"subsystem":subsystem,"disabled":disabled,"path":path,"reason_hash":_reason_hash(reason)}


def prepare_budget(*,cost_usd:float,model_calls:int,api_calls:int,reason:str)->dict[str,Any]:
    req(0<cost_usd<=1000,"cost_usd outside operator ceiling")
    req(0<model_calls<=10000 and 0<api_calls<=10000,"model/API calls outside operator ceiling")
    path=ROOT/"cost_governor"/"COST_GOVERNOR_POLICY.json";doc=json.loads(path.read_text())
    doc["portfolio_ceiling"]["cost_usd"]=float(cost_usd)
    doc["portfolio_ceiling"]["model_calls"]=int(model_calls)
    doc["portfolio_ceiling"]["api_calls"]=int(api_calls)
    validate_cost_policy(doc);write_json(path,doc)
    return {"cost_usd":cost_usd,"model_calls":model_calls,"api_calls":api_calls,"reason_hash":_reason_hash(reason)}


def cancel_queue_item(*,state_path:str,output_path:str,work_id:str)->dict[str,Any]:
    state=load_scheduler_state(state_path);matches=[w for w in state["work_items"] if w["scheduler_work_id"]==work_id]
    req(len(matches)==1,"work id missing or duplicate")
    work=matches[0];req(work["state"] in {"QUEUED","ACTIVE"},"only queued/active work may be cancelled")
    out=mark_work(state,work["fingerprint"],"CANCELLED");validate_scheduler_state(out);write_json(output_path,out)
    return {"work_id":work_id,"fingerprint":work["fingerprint"],"prior_state":work["state"],"new_state":"CANCELLED"}


def operator_report(*,output_json:str,output_md:str)->dict[str,Any]:
    telemetry=build_operational_telemetry()
    history_path=ROOT/"dashboard"/"live"/"history_state.json"
    history=public_history(load_history_state(history_path if history_path.exists() else None))
    sources=load_json(ROOT/"dashboard"/"live"/"state_sources.json") if (ROOT/"dashboard"/"live"/"state_sources.json").exists() else {"bridge_status":"FALLBACK","sources":{}}
    report={
      "schema_version":"1.0.0","report_id":"portfolio-operator-report-v1","generated_at":telemetry["generated_at"],
      "authority_class":"OBSERVE","telemetry":telemetry,"history":history,"state_sources":sources,
    }
    write_json(output_json,report)
    q=telemetry["queue"]["counts"];actual=telemetry["cost"]["actual_usage_today"];accounted=telemetry["cost"]["budget_accounted_usage_today"];cycle=telemetry["cycles"]["latest_overall"]
    lines=[
      "# Portfolio Brain Operator Report","",
      f"Generated: {report['generated_at']}",
      f"Live-state bridge: {sources.get('bridge_status','UNKNOWN')}",
      f"Queue: QUEUED {q['QUEUED']} | ACTIVE {q['ACTIVE']} | COMPLETE {q['COMPLETE']} | CANCELLED {q['CANCELLED']}",
      f"Actual today: USD {actual['cost_usd']:.4f} | model calls {actual['model_calls']} | API calls {actual['api_calls']} | runner minutes {actual['github_runner_minutes']}",
      f"Governor-accounted today: USD {accounted['cost_usd']:.4f} | model calls {accounted['model_calls']} | API calls {accounted['api_calls']} | runner minutes {accounted['github_runner_minutes']}",
      f"Actions sent: {telemetry['actions']['total_sent']} | failures: {telemetry['failures']['count']} | verified outcomes: {telemetry['verified_external_outcomes']}",
      "Last successful cycle: "+("NONE" if cycle is None else f"{cycle['subsystem']} {cycle['cycle_id']} {cycle['finished_at']}"),
      "","## Agent heartbeats","",
    ]
    for row in telemetry["agents"]["agents"]:
        lines.append(f"- {row['agent_id']}: {row['heartbeat_health']} | {row['last_heartbeat_at'] or 'never'} | {row['last_activity_kind'] or 'none'}")
    Path(output_md).parent.mkdir(parents=True,exist_ok=True);Path(output_md).write_text("\n".join(lines)+"\n")
    return report


def main()->None:
    ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("report");p.add_argument("--output-json",required=True);p.add_argument("--output-md",required=True)
    p=sub.add_parser("cancel-work");p.add_argument("--state",required=True);p.add_argument("--output",required=True);p.add_argument("--work-id",required=True)
    p=sub.add_parser("prepare-kill-switch");p.add_argument("--subsystem",required=True,choices=sorted(KILL_SWITCHES));p.add_argument("--disabled",required=True,choices=["true","false"]);p.add_argument("--actor",required=True);p.add_argument("--reason",default="")
    p=sub.add_parser("prepare-budget");p.add_argument("--cost-usd",required=True,type=float);p.add_argument("--model-calls",required=True,type=int);p.add_argument("--api-calls",required=True,type=int);p.add_argument("--reason",default="")
    p=sub.add_parser("prepare-approval");p.add_argument("--source-ref",required=True);p.add_argument("--project-id",required=True);p.add_argument("--approval-code",required=True);p.add_argument("--actor",required=True);p.add_argument("--reason",default="")
    a=ap.parse_args()
    if a.cmd=="report":result=operator_report(output_json=a.output_json,output_md=a.output_md)
    elif a.cmd=="cancel-work":result=cancel_queue_item(state_path=a.state,output_path=a.output,work_id=a.work_id)
    elif a.cmd=="prepare-kill-switch":result=prepare_kill_switch(subsystem=a.subsystem,disabled=a.disabled=="true",actor=a.actor,reason=a.reason)
    elif a.cmd=="prepare-budget":result=prepare_budget(cost_usd=a.cost_usd,model_calls=a.model_calls,api_calls=a.api_calls,reason=a.reason)
    else:result=prepare_approval(source_ref=a.source_ref,project_id=a.project_id,approval_code=a.approval_code,actor=a.actor,reason=a.reason)
    print(json.dumps(result,sort_keys=True,default=str))


if __name__=="__main__":main()
