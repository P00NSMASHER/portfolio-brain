#!/usr/bin/env python3
"""Deterministic-first, provider-agnostic model router."""
from __future__ import annotations
import hashlib, json, math
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

ROOT=Path(__file__).resolve().parents[1]
class ModelRouterError(ValueError): pass
def req(ok,msg):
    if not ok:raise ModelRouterError(msg)
def load(path):
    p=Path(path)
    if not p.is_absolute():p=ROOT/p
    return json.loads(p.read_text())
def canon(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def hashv(v):return "sha256:"+hashlib.sha256(canon(v).encode()).hexdigest()
def policy():return load("model_router/MODEL_ROUTER_POLICY.json")
def provider_registry():return load("model_router/PROVIDER_REGISTRY.json")
def _time(v,field):
    req(isinstance(v,str) and v,f"{field} required")
    try:dt=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError as exc:raise ModelRouterError(f"{field} invalid ISO-8601") from exc
    req(dt.tzinfo is not None,f"{field} requires timezone")
    return dt

def validate_request(r):
    required={"schema_version","request_id","project_ids","task_kind","deterministic_sufficient","consequence","data_classification","authority_class","requires_independent_adversarial","builder_independence_group","max_cost_usd","max_input_tokens","max_output_tokens","provider_allowlist","evidence_refs"}
    req(isinstance(r,dict) and set(r)==required,"route request fields changed")
    p=policy()
    req(r["schema_version"]=="1.0.0","request schema mismatch")
    req(isinstance(r["request_id"],str) and r["request_id"].startswith("MRQ-"),"invalid request_id")
    req(r["project_ids"] and len(r["project_ids"])==len(set(r["project_ids"])),"project_ids required and unique")
    req(r["task_kind"] in set(p["deterministic_task_kinds"]+p["tier1_task_kinds"]+p["tier2_task_kinds"]+p["tier3_task_kinds"]),"unknown task kind")
    req(r["consequence"] in {"LOW","MEDIUM","HIGH","CRITICAL"},"invalid consequence")
    req(r["data_classification"] in {"PUBLIC","SANITIZED","PRIVATE_REFERENCE_ONLY"},"invalid data classification")
    req(r["authority_class"] in {"NONE","OBSERVE","EXPERIMENT","MODIFY","ACT"},"invalid authority class")
    req(type(r["max_cost_usd"]) in {int,float} and math.isfinite(float(r["max_cost_usd"])) and r["max_cost_usd"]>=0,"invalid cost ceiling")
    req(type(r["max_input_tokens"]) is int and r["max_input_tokens"]>=0,"invalid input token ceiling")
    req(type(r["max_output_tokens"]) is int and r["max_output_tokens"]>=0,"invalid output token ceiling")
    req(isinstance(r["provider_allowlist"],list) and len(r["provider_allowlist"])==len(set(r["provider_allowlist"])),"provider allowlist invalid")
    req(isinstance(r["evidence_refs"],list) and r["evidence_refs"],"evidence refs required")
    if r["requires_independent_adversarial"]:
        req(r["builder_independence_group"] is not None,"independent adversarial routing requires builder independence group")

def required_tier(r):
    validate_request(r);p=policy()
    if r["requires_independent_adversarial"] or r["task_kind"] in p["tier3_task_kinds"]:return 3
    if r["deterministic_sufficient"] or r["task_kind"] in p["deterministic_task_kinds"]:return 0
    if r["task_kind"] in p["tier1_task_kinds"]:return 1
    if r["task_kind"] in p["tier2_task_kinds"]:return 2
    raise ModelRouterError("unable to classify tier")

def _cost(model,r):
    pricing=model["pricing"];basis=pricing["basis"]
    if basis=="ZERO_TIER0":return 0.0
    if basis=="CONFIGURED_RATE":
        vals=[pricing["input_usd_per_million_tokens"],pricing["output_usd_per_million_tokens"],pricing["fixed_call_usd"]]
        req(all(type(x) in {int,float} and math.isfinite(float(x)) and x>=0 for x in vals),"invalid configured pricing")
        return float(pricing["fixed_call_usd"])+(r["max_input_tokens"]*float(pricing["input_usd_per_million_tokens"])+r["max_output_tokens"]*float(pricing["output_usd_per_million_tokens"]))/1_000_000
    raise ModelRouterError("provider lacks configured pre-call pricing")

def _candidates(r,registry,tier):
    out=[]
    allowed=set(r["provider_allowlist"])
    for provider in registry["providers"]:
        if not provider.get("enabled"):continue
        if allowed and provider["provider_id"] not in allowed:continue
        for model in provider.get("models",[]):
            if not model.get("enabled") or model.get("tier")!=tier:continue
            if r["data_classification"] not in model.get("supported_data_classifications",[]):continue
            if r["max_input_tokens"]>model.get("max_input_tokens",0) or r["max_output_tokens"]>model.get("max_output_tokens",0):continue
            if tier==3 and model.get("independence_group")==r["builder_independence_group"]:continue
            try:cost=_cost(model,r)
            except ModelRouterError:continue
            if cost>float(r["max_cost_usd"])+1e-12:continue
            out.append((cost,provider["provider_id"],model["model_id"],model["independence_group"],provider["adapter_kind"]))
    return sorted(out,key=lambda x:(x[0],x[1],x[2]))

def route_request(r,registry=None):
    validate_request(r);registry=registry or provider_registry();tier=required_tier(r)
    if tier==0:
        provider=next(p for p in registry["providers"] if p["provider_id"]=="deterministic" and p["enabled"])
        model=next(m for m in provider["models"] if m["tier"]==0 and m["enabled"])
        selected=(0.0,provider["provider_id"],model["model_id"],model["independence_group"],provider["adapter_kind"])
        status="ROUTED"
        reasons=["DETERMINISTIC_SUFFICIENT","TIER0_PREFERRED"]
    else:
        candidates=_candidates(r,registry,tier)
        if not candidates:
            status="BLOCKED_NO_ELIGIBLE_PROVIDER";selected=None
            reasons=["NO_ENABLED_COMPATIBLE_PROVIDER_WITHIN_COST_AND_DATA_BOUNDARIES"]
            if tier==3:reasons.append("INDEPENDENT_ADVERSARIAL_ROUTE_REQUIRED")
        else:
            selected=candidates[0];status="ROUTED";reasons=[f"TIER_{tier}_REQUIRED","LOWEST_CONFIGURED_COST_WITHIN_TIER"]
            if tier==3:reasons.append("INDEPENDENCE_GROUP_DIFFERS_FROM_BUILDER")
    route_core={
      "request_id":r["request_id"],"tier":tier,"status":status,
      "provider_id":selected[1] if selected else None,"model_id":selected[2] if selected else None,
      "independence_group":selected[3] if selected else None,"adapter_kind":selected[4] if selected else None,
      "max_estimated_cost_usd":selected[0] if selected else None,
      "reason_codes":reasons,"can_grant_authority":False,"can_upgrade_evidence":False,
      "requires_independent_adversarial":r["requires_independent_adversarial"] or tier==3
    }
    route_id="MRT-"+hashlib.sha256(canon(route_core).encode()).hexdigest()[:20].upper()
    route={**route_core,"route_id":route_id}
    return {**route,"route_hash":hashv(route)}

class ProviderExecutor(Protocol):
    def invoke(self,*,provider_id:str,model_id:str,input_hash:str,max_output_tokens:int)->dict[str,Any]: ...

def validate_call_receipt(receipt,route=None,request=None):
    required={"schema_version","invocation_id","request_id","route_id","tier","provider_id","model_id","independence_group","status","started_at","completed_at","input_tokens","output_tokens","cost_usd","cost_basis","latency_ms","input_hash","output_hash","authority_granted","evidence_upgraded","downstream_outcome_ids","receipt_hash"}
    req(isinstance(receipt,dict) and set(receipt)==required,"call receipt fields changed")
    req(receipt["schema_version"]=="1.0.0","call receipt schema mismatch")
    req(receipt["authority_granted"] is False and receipt["evidence_upgraded"] is False,"model receipt cannot grant authority/evidence upgrade")
    req(_time(receipt["completed_at"],"completed_at")>=_time(receipt["started_at"],"started_at"),"call completes before start")
    for k in ["input_tokens","output_tokens","latency_ms"]:req(type(receipt[k]) is int and receipt[k]>=0,f"invalid {k}")
    req(type(receipt["cost_usd"]) in {int,float} and math.isfinite(float(receipt["cost_usd"])) and receipt["cost_usd"]>=0,"invalid call cost")
    body=dict(receipt);given=body.pop("receipt_hash");req(given==hashv(body),"call receipt hash mismatch")
    if receipt["tier"]==0:
        req(receipt["provider_id"]=="deterministic" and receipt["model_id"]=="NONE","Tier 0 receipt provider/model mismatch")
        req(receipt["input_tokens"]==0 and receipt["output_tokens"]==0 and receipt["cost_usd"]==0,"Tier 0 must have zero model usage/cost")
        req(receipt["cost_basis"]=="ZERO_TIER0","Tier 0 cost basis mismatch")
    if route is not None:
        req(receipt["route_id"]==route["route_id"] and receipt["tier"]==route["tier"],"receipt route mismatch")
        req(route["status"]=="ROUTED","cannot record successful call for blocked route")
        req(receipt["provider_id"]==route["provider_id"] and receipt["model_id"]==route["model_id"],"receipt provider/model mismatch")
        if route["max_estimated_cost_usd"] is not None:req(receipt["cost_usd"]<=route["max_estimated_cost_usd"]+1e-9,"actual call cost exceeds routed ceiling")
    if request is not None:
        req(receipt["request_id"]==request["request_id"],"receipt request mismatch")
        req(receipt["cost_usd"]<=request["max_cost_usd"]+1e-9,"actual call cost exceeds request ceiling")

def make_tier0_receipt(route,request,*,input_hash,output_hash,started_at,completed_at,latency_ms=0):
    req(route["tier"]==0 and route["status"]=="ROUTED","Tier 0 receipt requires routed Tier 0")
    core={
      "schema_version":"1.0.0","invocation_id":"MINV-"+hashlib.sha256((route["route_id"]+"\0"+input_hash+"\0"+output_hash).encode()).hexdigest()[:20].upper(),
      "request_id":request["request_id"],"route_id":route["route_id"],"tier":0,"provider_id":"deterministic","model_id":"NONE","independence_group":"deterministic",
      "status":"SUCCESS","started_at":started_at,"completed_at":completed_at,"input_tokens":0,"output_tokens":0,"cost_usd":0.0,"cost_basis":"ZERO_TIER0","latency_ms":int(latency_ms),
      "input_hash":input_hash,"output_hash":output_hash,"authority_granted":False,"evidence_upgraded":False,"downstream_outcome_ids":[]
    }
    receipt={**core,"receipt_hash":hashv(core)};validate_call_receipt(receipt,route,request);return receipt

def validate_feedback(f):
    required={"schema_version","feedback_id","invocation_id","outcome_event_id","evidence_state","value_class","outcome_value","provenance_refs"}
    req(isinstance(f,dict) and set(f)==required,"feedback fields changed")
    req(f["evidence_state"] in {"OBSERVED","VERIFIED","INFERRED","UNKNOWN","CONTRADICTED","STALE","INVALID"},"invalid feedback evidence state")
    req(f["value_class"] in {"TECHNICAL","EXTERNAL_VALUE","COST_EFFICIENCY"},"invalid feedback value class")
    req(type(f["outcome_value"]) in {int,float} and math.isfinite(float(f["outcome_value"])) and -1<=float(f["outcome_value"])<=1,"invalid outcome value")
    req(f["provenance_refs"],"feedback provenance required")

def value_summary(calls,feedback):
    by_inv={}
    for c in calls:
        validate_call_receipt(c);req(c["invocation_id"] not in by_inv,"duplicate invocation_id");by_inv[c["invocation_id"]]=c
    seen=set();buckets={}
    for f in feedback:
        validate_feedback(f);req(f["feedback_id"] not in seen,"duplicate feedback_id");seen.add(f["feedback_id"])
        req(f["invocation_id"] in by_inv,"feedback references unknown invocation")
        if f["evidence_state"]!="VERIFIED":continue
        c=by_inv[f["invocation_id"]];key=f"T{c['tier']}::{c['provider_id']}::{c['model_id']}"
        b=buckets.setdefault(key,{"verified_outcomes":0,"outcome_value_sum":0.0,"cost_usd":0.0})
        b["verified_outcomes"]+=1;b["outcome_value_sum"]+=float(f["outcome_value"]);b["cost_usd"]+=float(c["cost_usd"])
    for b in buckets.values():
        b["mean_verified_outcome_value"]=b["outcome_value_sum"]/b["verified_outcomes"];del b["outcome_value_sum"]
    return dict(sorted(buckets.items()))

def prepare_governed_execution(request, cost_state, *, attempt=1, at=None, registry=None, policy_data=None):
    """Route first, then require the Step 20 cost boundary before provider execution."""
    route = route_request(request, registry)
    if route["status"] != "ROUTED":
        return cost_state, {
            "route": route,
            "cost_decision": None,
            "cost_gate_passed": False,
            "authority_granted": False,
        }
    from cost_governor.cost_governor import reserve_model_execution
    next_state, decision = reserve_model_execution(
        cost_state,
        route,
        request,
        attempt=attempt,
        at=at,
        policy_data=policy_data,
    )
    return next_state, {
        "route": route,
        "cost_decision": decision,
        "cost_gate_passed": bool(decision.get("can_execute")),
        "authority_granted": False,
    }

