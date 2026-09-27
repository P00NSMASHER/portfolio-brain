#!/usr/bin/env python3
"""Durable VERIFIED-outcome feedback state for Portfolio Brain model routing."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from model_router.model_router import validate_call_receipt, validate_feedback, value_summary

ROOT=Path(__file__).resolve().parents[1]
SEED=ROOT/"model_router"/"MODEL_FEEDBACK_STATE_SEED.json"
STATE_ID="portfolio-model-feedback-state"
ARTIFACT_NAME="portfolio-model-feedback-state"

class ModelFeedbackError(ValueError):
    pass

def req(ok:bool,msg:str)->None:
    if not ok:
        raise ModelFeedbackError(msg)

def canon(v:Any)->str:
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)

def digest(v:Any)->str:
    return "sha256:"+hashlib.sha256(canon(v).encode()).hexdigest()

def now_iso()->str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

def load_seed_state()->dict[str,Any]:
    return json.loads(SEED.read_text(encoding="utf-8"))

def _task_summaries(state:dict[str,Any])->dict[str,Any]:
    calls={row["invocation_id"]:row for row in state["calls"]}
    contexts={row["feedback_id"]:row for row in state["task_contexts"]}
    buckets={}
    for feedback in state["outcomes"]:
        if feedback["evidence_state"]!="VERIFIED":
            continue
        ctx=contexts.get(feedback["feedback_id"])
        if ctx is None:
            continue
        call=calls.get(feedback["invocation_id"])
        if call is None:
            continue
        task_kind=ctx["task_kind"]
        key=f"T{call['tier']}::{call['provider_id']}::{call['model_id']}"
        bucket=buckets.setdefault(task_kind,{}).setdefault(key,{
          "verified_outcomes":0,
          "outcome_value_sum":0.0,
          "cost_usd":0.0,
          "roles":{},
        })
        bucket["verified_outcomes"]+=1
        bucket["outcome_value_sum"]+=float(feedback["outcome_value"])
        bucket["cost_usd"]+=float(call["cost_usd"])
        bucket["roles"][ctx["role"]]=bucket["roles"].get(ctx["role"],0)+1
    for by_model in buckets.values():
        for bucket in by_model.values():
            bucket["mean_verified_outcome_value"]=bucket["outcome_value_sum"]/bucket["verified_outcomes"]
            bucket["mean_cost_per_verified_outcome_usd"]=bucket["cost_usd"]/bucket["verified_outcomes"]
            del bucket["outcome_value_sum"]
    return {task:dict(sorted(rows.items())) for task,rows in sorted(buckets.items())}

def rebuild_summaries(state:dict[str,Any])->None:
    state["routing_value_summary"]=value_summary(state["calls"],state["outcomes"])
    state["routing_task_summaries"]=_task_summaries(state)

def validate_state(state:dict[str,Any])->None:
    required={
      "schema_version","state_id","sequence","updated_at","calls","outcomes",
      "task_contexts","applied_feedback_keys","routing_value_summary","routing_task_summaries"
    }
    req(isinstance(state,dict) and set(state)==required,"model feedback state fields changed")
    req(state["schema_version"]=="1.0.0" and state["state_id"]==STATE_ID,"model feedback state identity mismatch")
    req(type(state["sequence"]) is int and state["sequence"]>=0,"model feedback sequence invalid")
    req(state["updated_at"] is None or isinstance(state["updated_at"],str),"model feedback updated_at invalid")
    req(isinstance(state["calls"],list) and isinstance(state["outcomes"],list),"model feedback ledgers invalid")
    req(isinstance(state["task_contexts"],list),"model feedback task contexts invalid")
    req(isinstance(state["applied_feedback_keys"],list),"model feedback keys invalid")
    req(len(state["applied_feedback_keys"])==len(set(state["applied_feedback_keys"])),"duplicate model feedback key")
    call_ids=set()
    for call in state["calls"]:
        validate_call_receipt(call)
        req(call["invocation_id"] not in call_ids,"duplicate model feedback invocation");call_ids.add(call["invocation_id"])
    feedback_ids=set()
    for feedback in state["outcomes"]:
        validate_feedback(feedback)
        req(feedback["feedback_id"] not in feedback_ids,"duplicate model feedback id");feedback_ids.add(feedback["feedback_id"])
        req(feedback["invocation_id"] in call_ids,"model feedback references unknown call")
    context_ids=set()
    for ctx in state["task_contexts"]:
        req(set(ctx)=={
          "feedback_id","feedback_key","task_kind","role","task_id","invocation_id",
          "outcome_event_id","tier","provider_id","model_id"
        },"model feedback context fields changed")
        req(ctx["feedback_id"] in feedback_ids,"model feedback context references unknown feedback")
        req(ctx["invocation_id"] in call_ids,"model feedback context references unknown call")
        req(ctx["feedback_id"] not in context_ids,"duplicate model feedback context");context_ids.add(ctx["feedback_id"])
        req(ctx["role"] in {"BUILDER","VERIFIER"},"model feedback role invalid")
        req(isinstance(ctx["task_kind"],str) and ctx["task_kind"],"model feedback task kind invalid")
        req(isinstance(ctx["feedback_key"],str) and ctx["feedback_key"],"model feedback key missing")
    req(context_ids==feedback_ids,"every model feedback outcome requires one task context")
    expected_global=value_summary(state["calls"],state["outcomes"])
    expected_task=_task_summaries(state)
    req(state["routing_value_summary"]==expected_global,"global routing value summary drift")
    req(state["routing_task_summaries"]==expected_task,"task routing value summary drift")

def stable_feedback_key(*,task_id:str,role:str,hunter_finding_id:str,value_class:str)->str:
    raw={"task_id":task_id,"role":role,"hunter_finding_id":hunter_finding_id,"value_class":value_class}
    return "MFBK-"+hashlib.sha256(canon(raw).encode()).hexdigest()[:24].upper()

def _feedback_id(key:str)->str:
    return "MFB-"+hashlib.sha256(key.encode()).hexdigest()[:24].upper()

def apply_verified_model_feedback(
    state:dict[str,Any],
    *,
    feedback_key:str,
    task_id:str,
    task_kind:str,
    role:str,
    hunter_finding_id:str,
    call_receipt:dict[str,Any],
    outcome_event_id:str,
    outcome_value:float,
    provenance_refs:list[str],
    at:str|None=None,
)->bool:
    validate_state(state)
    req(role in {"BUILDER","VERIFIER"},"feedback role invalid")
    req(feedback_key==stable_feedback_key(
      task_id=task_id,role=role,hunter_finding_id=hunter_finding_id,value_class="TECHNICAL"
    ),"feedback key does not match stable lineage")
    if feedback_key in state["applied_feedback_keys"]:
        return False
    validate_call_receipt(call_receipt)
    feedback={
      "schema_version":"1.0.0",
      "feedback_id":_feedback_id(feedback_key),
      "invocation_id":call_receipt["invocation_id"],
      "outcome_event_id":outcome_event_id,
      "evidence_state":"VERIFIED",
      "value_class":"TECHNICAL",
      "outcome_value":float(outcome_value),
      "provenance_refs":list(dict.fromkeys(provenance_refs)),
    }
    validate_feedback(feedback)
    req(-1<=float(outcome_value)<=1,"model feedback value outside range")
    if not any(x["invocation_id"]==call_receipt["invocation_id"] for x in state["calls"]):
        state["calls"].append(call_receipt)
    state["outcomes"].append(feedback)
    state["task_contexts"].append({
      "feedback_id":feedback["feedback_id"],
      "feedback_key":feedback_key,
      "task_kind":task_kind,
      "role":role,
      "task_id":task_id,
      "invocation_id":call_receipt["invocation_id"],
      "outcome_event_id":outcome_event_id,
      "tier":call_receipt["tier"],
      "provider_id":call_receipt["provider_id"],
      "model_id":call_receipt["model_id"],
    })
    state["applied_feedback_keys"].append(feedback_key)
    state["sequence"]+=1
    state["updated_at"]=at or now_iso()
    rebuild_summaries(state)
    validate_state(state)
    return True

def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--state",type=Path,required=True)
    args=ap.parse_args()
    state=json.loads(args.state.read_text(encoding="utf-8")) if args.state.exists() else load_seed_state()
    rebuild_summaries(state);validate_state(state)
    print(json.dumps({
      "state_id":state["state_id"],"sequence":state["sequence"],
      "calls":len(state["calls"]),"outcomes":len(state["outcomes"]),
      "task_kinds":sorted(state["routing_task_summaries"])
    },sort_keys=True))

if __name__=="__main__":
    main()
