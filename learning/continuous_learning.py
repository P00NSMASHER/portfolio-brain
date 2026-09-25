#!/usr/bin/env python3
"""Evidence-aware continuous portfolio learning engine.

This is a portfolio normalization/advisory layer built to conform to the pinned
AI Business OS learning semantics. It is deterministic, replayable, and cannot
promote policy or authority on its own.
"""
from __future__ import annotations
import hashlib, json, math
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
POLICY_PATH=ROOT/"learning"/"LEARNING_POLICY.json"

class LearningError(ValueError): pass

def req(ok: bool,msg: str)->None:
    if not ok: raise LearningError(msg)

def load(path: str|Path):
    p=Path(path)
    if not p.is_absolute(): p=ROOT/p
    return json.loads(p.read_text(encoding="utf-8"))

def canonical_hash(value: Any)->str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    return "sha256:"+hashlib.sha256(raw).hexdigest()

def _time(value: str,field: str)->datetime:
    req(isinstance(value,str) and value,f"{field} required")
    try: dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc: raise LearningError(f"{field} invalid ISO-8601") from exc
    req(dt.tzinfo is not None,f"{field} requires timezone")
    return dt

def policy(): return load(POLICY_PATH)

def validate_observation(o: dict[str,Any])->None:
    required={
      "schema_version","observation_id","domain","learning_key","scope","project_ids","objective_id",
      "phase","measurement_quality","signal_class","evidence_state","reward_signal","sample_size",
      "measured_numerator","measured_denominator","source_event_ids","evidence_ids",
      "resource_usage","observed_at","provenance_refs"
    }
    req(isinstance(o,dict) and set(o)==required,"learning observation fields changed")
    p=policy()
    req(o["schema_version"]=="1.0.0","observation schema mismatch")
    req(isinstance(o["observation_id"],str) and o["observation_id"].startswith("LRN-"),"invalid observation_id")
    req(o["domain"] in p["domains"],"unsupported learning domain")
    req(isinstance(o["learning_key"],str) and o["learning_key"],"learning_key required")
    req(o["scope"]=="GLOBAL" or (isinstance(o["scope"],str) and o["scope"].startswith("PRJ-")),"invalid learning scope")
    pids=o["project_ids"]; req(isinstance(pids,list) and len(pids)==len(set(pids)),"project_ids invalid")
    req(all(isinstance(x,str) and x.startswith("PRJ-") for x in pids),"invalid project_id")
    if o["scope"]!="GLOBAL": req(o["scope"] in pids,"project scope must appear in project_ids")
    req(o["objective_id"] is None or (isinstance(o["objective_id"],str) and o["objective_id"].startswith("OBJ-")),"invalid objective_id")
    req(o["phase"] in p["phases"],"invalid phase")
    req(o["measurement_quality"] in p["measurement_qualities"],"invalid measurement quality")
    req(o["signal_class"] in p["signal_classes"],"invalid signal class")
    req(o["evidence_state"] in {"OBSERVED","VERIFIED","INFERRED","UNKNOWN","CONTRADICTED","STALE","INVALID"},"invalid evidence state")
    reward=o["reward_signal"]
    req(reward is None or (type(reward) in {int,float} and math.isfinite(float(reward)) and -1<=float(reward)<=1),"invalid reward_signal")
    req(type(o["sample_size"]) is int and o["sample_size"]>=0,"invalid sample_size")
    num=o["measured_numerator"]; den=o["measured_denominator"]
    req((num is None)==(den is None),"measured numerator/denominator must both be null or both present")
    if num is not None:
        req(type(num) is int and type(den) is int and 0<=num<=den,"invalid measured numerator/denominator")
        req(o["sample_size"]>=den,"sample_size cannot be smaller than measured denominator")
    ev=o["evidence_ids"]; req(isinstance(ev,list) and ev and len(ev)==len(set(ev)),"evidence_ids required and unique")
    req(all(isinstance(x,str) and x.startswith("EVD-") for x in ev),"invalid evidence_id")
    event_ids=o["source_event_ids"];req(isinstance(event_ids,list) and len(event_ids)==len(set(event_ids)),"source_event_ids invalid")
    req(all(isinstance(x,str) and x.startswith("EVT-") for x in event_ids),"invalid source event id")
    ru=o["resource_usage"]; expected={"model_calls","tokens","cost_usd","compute_seconds","tool_calls"}
    req(isinstance(ru,dict) and set(ru)==expected,"resource_usage fields changed")
    for key in ["model_calls","tokens","tool_calls"]:
        req(type(ru[key]) is int and ru[key]>=0,f"invalid resource_usage.{key}")
    for key in ["cost_usd","compute_seconds"]:
        req(type(ru[key]) in {int,float} and math.isfinite(float(ru[key])) and ru[key]>=0,f"invalid resource_usage.{key}")
    _time(o["observed_at"],"observed_at")
    refs=o["provenance_refs"];req(isinstance(refs,list) and refs and len(refs)==len(set(refs)),"provenance_refs required")
    req(all(isinstance(x,str) and x for x in refs),"invalid provenance_ref")
    if o["signal_class"]!="INTERNAL_ACTIVITY":
        req(reward is not None,"measured signal class requires reward_signal")
    if o["signal_class"]=="VERIFIED_EXTERNAL_VALUE":
        req(o["evidence_state"]=="VERIFIED","external value must be VERIFIED")
        req(o["domain"] in {"SEARCH","PRODUCT","CUSTOMER","EXPERIMENT"},"external value domain unsupported")
    if o["signal_class"] in {"VERIFIED_TECHNICAL","COST_RESOURCE"}:
        req(o["evidence_state"]=="VERIFIED","technical/resource reward requires VERIFIED evidence")
    if o["domain"]=="CUSTOMER" and o["signal_class"]!="INTERNAL_ACTIVITY":
        req(o["signal_class"]=="VERIFIED_EXTERNAL_VALUE","customer learning value must be verified external value")
    if o["domain"]=="MODEL" and o["phase"]=="TRAIN":
        req(o["measurement_quality"]=="BENCHMARK","model TRAIN learning requires benchmark/held-out quality")
    if o["domain"]=="RESOURCE":
        req(o["signal_class"] in {"INTERNAL_ACTIVITY","COST_RESOURCE"},"resource domain uses activity or verified cost/resource signal only")

def memory_key(o: dict[str,Any])->str:
    validate_observation(o)
    objective=o["objective_id"] or "*"
    return f"{o['scope']}::{o['domain']}::{objective}::{o['learning_key']}"

def effective_reward(o: dict[str,Any])->float|None:
    validate_observation(o); p=policy()
    if o["phase"]!="TRAIN": return None
    if o["measurement_quality"] not in {"PROSPECTIVE","BENCHMARK"}: return None
    if o["evidence_state"]!="VERIFIED": return None
    weight=float(p["reward_weights"][o["signal_class"]])
    if weight<=0 or o["reward_signal"] is None:return None
    return max(-1.0,min(1.0,float(o["reward_signal"])*weight))

def _support_template():
    return {"observations":0,"sample_size":0,"reward_sum":0.0,"min_reward":None,"positive_observations":0}

def _support_add(bucket,o):
    reward=o["reward_signal"]
    bucket["observations"]+=1;bucket["sample_size"]+=o["sample_size"]
    if reward is not None and o["evidence_state"]=="VERIFIED" and o["measurement_quality"] in {"PROSPECTIVE","BENCHMARK"}:
        value=float(reward);bucket["reward_sum"]+=value
        bucket["min_reward"]=value if bucket["min_reward"] is None else min(bucket["min_reward"],value)
        if value>0:bucket["positive_observations"]+=1

def _support_finish(bucket):
    out=dict(bucket); n=out["observations"]
    out["mean_reward"]=out["reward_sum"]/n if n else 0.0
    del out["reward_sum"];return out

def rebuild_state(observations: list[dict[str,Any]])->dict[str,Any]:
    p=policy()
    seen=set(); rows=[]
    for o in observations:
        validate_observation(o)
        req(o["observation_id"] not in seen,"duplicate learning observation_id")
        seen.add(o["observation_id"]); rows.append(o)
    rows.sort(key=lambda x:(x["observed_at"],x["observation_id"]))
    records={}
    for o in rows:
        key=memory_key(o)
        rec=records.setdefault(key,{
          "memory_key":key,"scope":o["scope"],"domain":o["domain"],"objective_id":o["objective_id"],
          "learning_key":o["learning_key"],"q_value":0.0,"visits":0,"reward_ma":0.0,
          "last_reward":None,"last_observation_id":None,"updated_at":None,
          "_train":_support_template(),"_confirm":_support_template(),
          "retrospective_observations":0,"internal_activity_observations":0,"evaluation_only_observations":0,
          "resource_usage":{"model_calls":0,"tokens":0,"cost_usd":0.0,"compute_seconds":0.0,"tool_calls":0}
        })
        req(rec["domain"]==o["domain"] and rec["scope"]==o["scope"],"learning memory identity collision")
        ru=rec["resource_usage"]
        for k in ["model_calls","tokens","cost_usd","compute_seconds","tool_calls"]:ru[k]+=o["resource_usage"][k]
        if o["phase"]=="TRAIN":_support_add(rec["_train"],o)
        elif o["phase"]=="CONFIRM":_support_add(rec["_confirm"],o)
        else:rec["evaluation_only_observations"]+=1
        if o["measurement_quality"]=="RETROSPECTIVE":rec["retrospective_observations"]+=1
        if o["measurement_quality"]=="INTERNAL_ACTIVITY" or o["signal_class"]=="INTERNAL_ACTIVITY":rec["internal_activity_observations"]+=1
        reward=effective_reward(o)
        if reward is not None:
            cfg=p["q_config"];target=reward+float(cfg["gamma"])*0.0
            rec["q_value"]=max(float(cfg["q_floor"]),min(float(cfg["q_ceiling"]),(1-float(cfg["alpha"]))*rec["q_value"]+float(cfg["alpha"])*target))
            rec["visits"]+=1
            rec["reward_ma"]=reward if rec["visits"]==1 else (1-float(cfg["alpha"]))*rec["reward_ma"]+float(cfg["alpha"])*reward
            rec["last_reward"]=reward;rec["last_observation_id"]=o["observation_id"];rec["updated_at"]=o["observed_at"]

    gate=p["promotion_gate"]; alerts=[]
    final=[]
    for key in sorted(records):
        rec=records[key]; train=_support_finish(rec.pop("_train")); confirm=_support_finish(rec.pop("_confirm"))
        rec["train_support"]=train;rec["confirm_support"]=confirm
        train_ready=train["observations"]>=gate["minimum_train_observations"] and train["sample_size"]>=gate["minimum_train_sample_size"]
        confirm_ready=(
          confirm["observations"]>=gate["minimum_confirm_observations"] and
          confirm["sample_size"]>=gate["minimum_confirm_sample_size"] and
          confirm["mean_reward"]>=gate["minimum_confirm_mean_reward"] and
          confirm["min_reward"] is not None and confirm["min_reward"]>=gate["minimum_confirm_min_reward"] and
          confirm["positive_observations"]>=gate["minimum_confirm_positive_observations"]
        )
        rec["train_evidence_ready"]=train_ready;rec["confirm_evidence_ready"]=confirm_ready
        rec["eligible_for_policy_consideration"]=bool(train_ready and confirm_ready)
        if rec["eligible_for_policy_consideration"]: status="confirmed"
        elif train_ready and confirm["observations"]>=2 and confirm["mean_reward"]<0: status="overfit_signal"
        elif train_ready and confirm["observations"]>=2 and confirm["min_reward"] is not None and confirm["min_reward"]<0: status="confirm_regression_signal"
        elif train_ready: status="awaiting_confirm"
        else: status="gathering_evidence"
        rec["generalization_status"]=status
        if status in {"overfit_signal","confirm_regression_signal"}:
            alerts.append({"memory_key":key,"type":status,"recommended_action":"Keep suppressed from live priors; reproduce the failure and route it into the repair pipeline when a regression test can be defined."})
        final.append(rec)

    counts={d:sum(1 for x in rows if x["domain"]==d) for d in p["domains"]}
    source_hash=canonical_hash(rows)
    return {
      "schema_version":"1.0.0","state_id":"portfolio-learning-state","mode":p["mode"],"policy_effect":"NONE",
      "source_observation_count":len(rows),"source_snapshot_hash":source_hash,
      "domain_observation_counts":counts,"records":final,"learning_alerts":alerts,
      "eligible_record_count":sum(1 for x in final if x["eligible_for_policy_consideration"]),
      "state_hash":canonical_hash({"source_snapshot_hash":source_hash,"records":final,"learning_alerts":alerts})
    }

def rebuild_from_ledger()->dict[str,Any]:
    ledger=load("learning/LEARNING_OBSERVATION_LEDGER.json")
    req(ledger["schema_version"]=="1.0.0" and ledger["ledger_id"]=="portfolio-learning-observations","learning ledger identity mismatch")
    req(isinstance(ledger["observations"],list),"learning ledger observations must be list")
    return rebuild_state(ledger["observations"])
