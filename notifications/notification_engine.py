#!/usr/bin/env python3
"""Evidence-gated, deduplicated, rate-limited notification engine."""
from __future__ import annotations
import argparse,copy,hashlib,json,os
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

from cost_governor.cost_governor import hard_stop_reason,load_state as load_cost_state
from dashboard.executive_dashboard import build_dashboard_snapshot
from experiments.experiment_engine import build_experiment_portfolio
from scheduler.autonomous_scheduler import build_context,load_state as load_scheduler_state,schedule_cycle
from transfer.cross_project_transfer import build_transfer_state
from uncertainty.highest_value_uncertainty import build_snapshot as build_uncertainty_snapshot

ROOT=Path(__file__).resolve().parents[1]
class NotificationError(ValueError):pass
def req(ok,msg):
    if not ok:raise NotificationError(msg)
def load(path):
    p=Path(path)
    if not p.is_absolute():p=ROOT/p
    return json.loads(p.read_text())
def policy():return load("notifications/NOTIFICATION_POLICY.json")
def canon(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def hashv(v):return "sha256:"+hashlib.sha256(canon(v).encode()).hexdigest()
def now_iso():return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def _time(v,field):
    req(isinstance(v,str) and v,f"{field} required")
    try:d=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError as exc:raise NotificationError(f"{field} invalid ISO-8601") from exc
    req(d.tzinfo is not None,f"{field} requires timezone")
    return d.astimezone(timezone.utc)

def validate_policy(p=None):
    p=p or policy()
    req(p["schema_version"]=="1.0.0","notification policy schema mismatch")
    req(p["mode"]=="EVIDENCE_GATED_DEDUP_RATE_LIMITED","notification mode weakened")
    req(p["authority_class"]=="NONE","notification layer may not hold authority")
    req(p["delivery_channels"]==["GITHUB_ACTIONS_ANNOTATION","GITHUB_STEP_SUMMARY"],"notification delivery surface widened")
    req(set(p["severity_order"])=={"CRITICAL","HIGH","MEDIUM","INFO"},"severity set changed")
    req(all(type(v) is int and v>0 for v in p["cooldown_minutes"].values()),"cooldowns invalid")
    req(type(p["max_emitted_per_cycle"]) is int and 1<=p["max_emitted_per_cycle"]<=20,"emission ceiling invalid")
    req(type(p["failure_escalate_after_seen"]) is int and p["failure_escalate_after_seen"]>=2,"failure escalation threshold invalid")

def validate_alert_record(a):
    required={"schema_version","alert_id","fingerprint","kind","severity","project_ids","entity_refs","evidence_refs","title_code","summary_code","status","first_seen_at","last_seen_at","seen_count","last_emitted_at","emission_count"}
    req(isinstance(a,dict) and set(a)==required,"alert record fields changed")
    p=policy();req(a["schema_version"]=="1.0.0","alert schema mismatch")
    req(a["alert_id"].startswith("ALT-"),"alert id invalid")
    req(isinstance(a["fingerprint"],str) and a["fingerprint"].startswith("sha256:"),"alert fingerprint invalid")
    req(a["kind"] in p["alert_classes"],"unknown alert kind")
    req(a["severity"] in p["severity_order"],"unknown alert severity")
    req(isinstance(a["project_ids"],list) and len(a["project_ids"])==len(set(a["project_ids"])),"project ids invalid")
    req(isinstance(a["entity_refs"],list) and a["entity_refs"] and len(a["entity_refs"])==len(set(a["entity_refs"])),"entity refs invalid")
    req(isinstance(a["evidence_refs"],list) and a["evidence_refs"] and len(a["evidence_refs"])==len(set(a["evidence_refs"])),"evidence refs invalid")
    req(a["status"] in {"ACTIVE","RESOLVED"},"alert status invalid")
    _time(a["first_seen_at"],"first_seen_at");_time(a["last_seen_at"],"last_seen_at")
    req(type(a["seen_count"]) is int and a["seen_count"]>=1,"seen count invalid")
    req(type(a["emission_count"]) is int and a["emission_count"]>=0,"emission count invalid")
    if a["last_emitted_at"] is not None:_time(a["last_emitted_at"],"last_emitted_at")

def validate_state(state):
    p=policy()
    required={"schema_version","state_id","sequence","updated_at","last_dashboard_hash","alert_records","recent_deliveries"}
    req(isinstance(state,dict) and set(state)==required,"notification state fields changed")
    req(state["schema_version"]=="1.0.0" and state["state_id"]=="portfolio-notification-state","notification state identity mismatch")
    req(type(state["sequence"]) is int and state["sequence"]>=0,"notification sequence invalid")
    if state["updated_at"] is not None:_time(state["updated_at"],"updated_at")
    req(state["last_dashboard_hash"] is None or str(state["last_dashboard_hash"]).startswith("sha256:"),"dashboard hash invalid")
    req(isinstance(state["alert_records"],list) and len(state["alert_records"])<=p["max_alert_records"],"alert record ledger invalid")
    req(isinstance(state["recent_deliveries"],list) and len(state["recent_deliveries"])<=p["recent_delivery_limit"],"delivery ledger invalid")
    seen=set()
    for a in state["alert_records"]:
        validate_alert_record(a);req(a["fingerprint"] not in seen,"duplicate alert fingerprint");seen.add(a["fingerprint"])

def load_state(path=None):
    if path is not None and Path(path).exists():s=json.loads(Path(path).read_text())
    else:s=load("notifications/NOTIFICATION_STATE_SEED.json")
    validate_state(s);return s

def killed():
    p=policy();k=load(p["kill_switches"]["file"])
    if k.get("disabled") is True:return True,k.get("reason") or "file notification kill switch"
    if os.environ.get(p["kill_switches"]["repository_variable"],"").strip().lower()=="true":return True,"repository/environment notification kill switch"
    return False,None

def _signal(kind,project_ids,entity_refs,evidence_refs,state_code):
    p=policy();project_ids=sorted(set(project_ids));entity_refs=sorted(set(entity_refs));evidence_refs=list(dict.fromkeys(evidence_refs))
    req(entity_refs and evidence_refs,"signal requires entity/evidence refs")
    core={"kind":kind,"project_ids":project_ids,"entity_refs":entity_refs,"state_code":state_code}
    fp=hashv(core)
    return {"fingerprint":fp,"kind":kind,"severity":p["alert_classes"][kind],"project_ids":project_ids,"entity_refs":entity_refs,
            "evidence_refs":evidence_refs[:50],"title_code":kind,"summary_code":f"{kind}:COUNT_{len(entity_refs)}"}

def _experiment_outcome_signals(outcomes,plans):
    by={p["experiment_id"]:p for p in plans};signals=[]
    for o in outcomes:
        if o.get("evidence_state")!="VERIFIED" or o.get("result") not in {"PASSED","FAILED"}:continue
        plan=by.get(o.get("experiment_id"));pids=[] if plan is None else plan.get("project_ids",[])
        negative=o["result"]=="FAILED";kind="VERIFIED_NEGATIVE_OUTCOME" if negative else "VERIFIED_POSITIVE_OUTCOME"
        refs=[*o.get("evidence_ids",[]),*o.get("event_ids",[]),*o.get("provenance_refs",[])]
        if not refs:continue
        signals.append(_signal(kind,pids,[o["outcome_id"]],refs,o["result"]))
    return signals

def _transfer_outcome_signals(outcomes):
    signals=[]
    for o in outcomes:
        if o.get("evidence_state")!="VERIFIED" or o.get("result") not in {"VERIFIED_EFFECTIVE","VERIFIED_NO_VALUE"}:continue
        negative=o["result"]=="VERIFIED_NO_VALUE";kind="VERIFIED_NEGATIVE_OUTCOME" if negative else "VERIFIED_POSITIVE_OUTCOME"
        refs=[*o.get("implementation_evidence_ids",[]),*o.get("measurement_evidence_ids",[]),*o.get("provenance_refs",[])]
        if not refs:continue
        signals.append(_signal(kind,[o.get("target_project_id")] if o.get("target_project_id") else [],[o["outcome_id"]],refs,o["result"]))
    return signals

def build_signals(*,at,dashboard=None,scheduler_receipt=None,scheduler_state=None,cost_state=None,build_state=None,experiment_outcomes=None,experiment_plans=None,transfer_outcomes=None,last_dashboard_hash=None):
    dashboard=dashboard or build_dashboard_snapshot()
    build_state=build_state or load("PORTFOLIO_BUILD_STATE.json")
    scheduler_state=scheduler_state or load_scheduler_state()
    if scheduler_receipt is None:
        _,scheduler_receipt=schedule_cycle(scheduler_state,build_context(),at=at)
    cost_state=cost_state or load_cost_state()
    if experiment_outcomes is None:experiment_outcomes=load("experiments/EXPERIMENT_OUTCOME_LEDGER.json")["outcomes"]
    if experiment_plans is None:
        u=build_uncertainty_snapshot();experiment_plans=build_experiment_portfolio(u)["plans"]
    if transfer_outcomes is None:transfer_outcomes=load("transfer/TRANSFER_LEDGER.json")["outcomes"]
    signals=[]

    blocked=scheduler_receipt.get("blocked_work",[])
    approvals=[w for w in blocked if w.get("approval_requirements")]
    if approvals:
        pids=sorted({pid for w in approvals for pid in w.get("project_ids",[])})
        entities=[str(w.get("scheduler_work_id") or w.get("fingerprint")) for w in approvals]
        refs=list(dict.fromkeys(ref for w in approvals for ref in w.get("evidence_refs",[])))
        if refs:signals.append(_signal("HUMAN_APPROVAL_QUEUE",pids,entities,refs,"APPROVAL_REQUIRED"))

    human_blockers=[b for b in build_state.get("blockers",[]) if b.get("status")=="OPEN" and b.get("requires_human_decision") is True]
    if human_blockers:
        ids=[b["blocker_id"] for b in human_blockers]
        signals.append(_signal("OPEN_HUMAN_BLOCKERS",[],ids,[f"build-blocker:{x}" for x in ids],"OPEN_HUMAN_DECISION"))

    cancelled=[w for w in scheduler_state.get("work_items",[]) if w.get("state")=="CANCELLED"]
    if cancelled:
        pids=sorted({pid for w in cancelled for pid in w.get("project_ids",[])})
        entities=[str(w.get("scheduler_work_id") or w.get("fingerprint")) for w in cancelled]
        refs=list(dict.fromkeys(ref for w in cancelled for ref in w.get("evidence_refs",[])))
        if not refs:refs=[f"scheduler-work:{x}" for x in entities]
        signals.append(_signal("AUTONOMOUS_WORK_FAILURE",pids,entities,refs,"CANCELLED"))

    hard=hard_stop_reason(cost_state,at=at)
    if hard is not None:
        code=hard.split(":",1)[0]
        signals.append(_signal("COST_HARD_STOP",["PRJ-000"],[code],[f"cost-hard-stop:{code}"],code))

    signals.extend(_experiment_outcome_signals(experiment_outcomes,experiment_plans))
    signals.extend(_transfer_outcome_signals(transfer_outcomes))

    current_hash=dashboard["snapshot_hash"]
    if last_dashboard_hash is not None and current_hash!=last_dashboard_hash:
        signals.append(_signal("PORTFOLIO_STATE_CHANGED",["PRJ-000"],[current_hash],[last_dashboard_hash,current_hash],"DASHBOARD_HASH_CHANGED"))
    return sorted(signals,key=lambda s:(policy()["severity_order"].index(s["severity"]),s["kind"],s["fingerprint"])),current_hash

def _delivery(record,at):
    core={"schema_version":"1.0.0","delivery_id":"DLV-"+hashlib.sha256((record["alert_id"]+"\0"+at+"\0"+str(record["emission_count"]+1)).encode()).hexdigest()[:20].upper(),
          "alert_id":record["alert_id"],"fingerprint":record["fingerprint"],"kind":record["kind"],"severity":record["severity"],
          "project_ids":record["project_ids"],"entity_refs":record["entity_refs"],"evidence_refs":record["evidence_refs"],
          "title_code":record["title_code"],"summary_code":record["summary_code"],"emitted_at":at,
          "requires_human_attention":record["severity"] in {"CRITICAL","HIGH"},"authority_granted":False,
          "delivery_channels":policy()["delivery_channels"]}
    return {**core,"delivery_hash":hashv(core)}

def notification_cycle(state,*,at=None,sources=None):
    validate_policy();validate_state(state);at=at or now_iso();_time(at,"at")
    disabled,reason=killed()
    if disabled:
        return state,{"schema_version":"1.0.0","cycle_id":"notify-disabled","status":"DISABLED","reason":reason,"emitted_alerts":[],"suppressed_fingerprints":[],"resolved_alert_ids":[]}
    sources=dict(sources or {})
    signals,dash_hash=build_signals(at=at,last_dashboard_hash=state["last_dashboard_hash"],**sources)
    out=copy.deepcopy(state);by={a["fingerprint"]:a for a in out["alert_records"]};current={s["fingerprint"] for s in signals}
    resolved=[]
    for record in out["alert_records"]:
        if record["status"]=="ACTIVE" and record["fingerprint"] not in current:
            record["status"]="RESOLVED";record["last_seen_at"]=at;resolved.append(record["alert_id"])
    candidates=[];suppressed=[]
    for s in signals:
        r=by.get(s["fingerprint"])
        if r is None:
            r={"schema_version":"1.0.0","alert_id":"ALT-"+hashlib.sha256(s["fingerprint"].encode()).hexdigest()[:20].upper(),**s,
               "status":"ACTIVE","first_seen_at":at,"last_seen_at":at,"seen_count":1,"last_emitted_at":None,"emission_count":0}
            out["alert_records"].append(r);by[r["fingerprint"]]=r
        else:
            r["status"]="ACTIVE";r["last_seen_at"]=at;r["seen_count"]+=1
            r["evidence_refs"]=list(dict.fromkeys([*r["evidence_refs"],*s["evidence_refs"]]))[:50]
        if r["kind"]=="AUTONOMOUS_WORK_FAILURE" and r["seen_count"]>=policy()["failure_escalate_after_seen"]:
            r["severity"]="CRITICAL";r["summary_code"]="AUTONOMOUS_WORK_FAILURE:PERSISTENT"
        emit=False
        if r["last_emitted_at"] is None:emit=True
        else:
            minutes=(_time(at,"at")-_time(r["last_emitted_at"],"last_emitted_at")).total_seconds()/60
            if minutes>=policy()["cooldown_minutes"][r["severity"]]:emit=True
        if emit:candidates.append(r)
        else:suppressed.append(r["fingerprint"])
    order={s:i for i,s in enumerate(policy()["severity_order"])}
    candidates.sort(key=lambda r:(order[r["severity"]],r["kind"],r["alert_id"]))
    emitted=[]
    for r in candidates[:policy()["max_emitted_per_cycle"]]:
        d=_delivery(r,at);emitted.append(d);r["last_emitted_at"]=at;r["emission_count"]+=1
    suppressed.extend(r["fingerprint"] for r in candidates[policy()["max_emitted_per_cycle"]:])
    out["sequence"]+=1;out["updated_at"]=at;out["last_dashboard_hash"]=dash_hash
    out["recent_deliveries"]=([*out["recent_deliveries"],*emitted])[-policy()["recent_delivery_limit"]:]
    req(len(out["alert_records"])<=policy()["max_alert_records"],"notification state capacity exceeded")
    validate_state(out)
    seed={"prior_sequence":state["sequence"],"signals":[s["fingerprint"] for s in signals],"emitted":[d["delivery_id"] for d in emitted],"resolved":resolved}
    receipt={"schema_version":"1.0.0","cycle_id":"NTF-"+hashlib.sha256(canon(seed).encode()).hexdigest()[:20].upper(),
             "status":"PASS","signal_count":len(signals),"active_alert_count":sum(1 for a in out["alert_records"] if a["status"]=="ACTIVE"),
             "emitted_alerts":emitted,"suppressed_fingerprints":sorted(set(suppressed)),"resolved_alert_ids":sorted(resolved),
             "authority_granted":False,"delivery_channels":policy()["delivery_channels"]}
    receipt["receipt_hash"]=hashv(receipt)
    return out,receipt

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--state",default="notifications/live/notification_state.json");ap.add_argument("--scheduler-state",default="scheduler/live/scheduler_state.json");ap.add_argument("--cost-state",default="cost_governor/live/cost_state.json");ap.add_argument("--output-dir",default="notifications/out")
    a=ap.parse_args();state=load_state(a.state)
    scheduler_state=load_scheduler_state(a.scheduler_state);cost_state=load_cost_state(a.cost_state)
    state,receipt=notification_cycle(state,sources={"scheduler_state":scheduler_state,"cost_state":cost_state})
    out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
    (out/"notification_state.json").write_text(json.dumps(state,indent=2)+"\n")
    (out/"notification_cycle_receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    (out/"emitted_alerts.json").write_text(json.dumps(receipt["emitted_alerts"],indent=2)+"\n")
    print(json.dumps({"cycle_id":receipt["cycle_id"],"status":receipt["status"],"signals":receipt.get("signal_count",0),"emitted":len(receipt["emitted_alerts"])},sort_keys=True))
if __name__=="__main__":main()
