#!/usr/bin/env python3
"""Explainable multi-resource portfolio allocator.

The allocator recommends normalized shares only. It never claims real hours,
dollars, model calls or cash are available, and it never executes allocations.
"""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from typing import Any

from uncertainty.highest_value_uncertainty import dominates

ROOT=Path(__file__).resolve().parents[1]
class AllocationError(ValueError):pass
def req(ok,msg):
    if not ok:raise AllocationError(msg)
def load(path):
    p=Path(path)
    if not p.is_absolute():p=ROOT/p
    return json.loads(p.read_text())
def canon(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def hashv(v):return "sha256:"+hashlib.sha256(canon(v).encode()).hexdigest()
def policy():return load("allocator/ALLOCATOR_POLICY.json")

def _tie_key(c):
    v={k:c["components"][k]["value"] for k in c["components"]}
    return (-v["external_validation_value"],-v["importance"],-v["uncertainty"],-v["downstream_impact"],-v["strategic_reuse"],v["test_cost"],v["time_to_evidence"],-v["reversibility"],c["primary_project_id"],c["uncertainty_id"])

def _pareto_rank(candidates):
    remaining=list(candidates);layers={};layer=0
    while remaining:
        front=[c for c in remaining if not any(dominates(o,c) for o in remaining if o is not c)]
        req(front,"no Pareto front found")
        for c in front:layers[c["uncertainty_id"]]=layer
        ids={c["uncertainty_id"] for c in front};remaining=[c for c in remaining if c["uncertainty_id"] not in ids];layer+=1
    ranked=sorted(candidates,key=lambda c:(layers[c["uncertainty_id"]],*_tie_key(c)))
    return [(c,layers[c["uncertainty_id"]],i+1) for i,c in enumerate(ranked)]

def _project_best(candidates):
    out={}
    for c,layer,rank in _pareto_rank(candidates):
        pid=c["primary_project_id"]
        if pid not in out:out[pid]=(c,layer,rank)
    return list(out.values())

def _allocate_shares(items):
    p=policy();total=p["normalized_share_basis_points"];cap=p["max_project_share_basis_points"];weights=p["ranking"]["layer_share_weights"]
    if not items:return [],0,total
    raw=[]
    for c,layer,rank in items:
        weight=int(weights.get(str(layer),weights["default"]));raw.append([c,layer,rank,weight])
    denom=sum(x[3] for x in raw);shares=[];used=0
    for c,layer,rank,w in raw:
        s=min(cap,(total*w)//denom);shares.append([c,layer,rank,s]);used+=s
    remainder=total-used
    for row in shares:
        if remainder<=0:break
        room=cap-row[3]
        add=min(room,remainder);row[3]+=add;remainder-=add
    recs=[]
    for c,layer,rank,share in shares:
        if share<=0:continue
        recs.append((c,layer,rank,share))
    allocated=sum(x[3] for x in recs)
    return recs,allocated,total-allocated

def _enabled_nonzero_models():
    reg=load("model_router/PROVIDER_REGISTRY.json")
    return [(p["provider_id"],m["model_id"]) for p in reg["providers"] if p["enabled"] for m in p["models"] if m["enabled"] and m["tier"]>0]

def _resource_candidates(resource,uncertainty,experiments):
    by_unc={c["uncertainty_id"]:c for c in uncertainty["candidates"]}
    plans=experiments["plans"]
    if resource=="MODEL_CALLS":
        ids=[p["uncertainty_id"] for p in plans if p["status"] in {"READY_FOR_ISOLATED_EXECUTION","READY_FOR_BOUNDED_EXECUTION"}]
        return [by_unc[x] for x in ids],"Enabled Tier 1-3 routes create bounded reasoning capacity for isolated and bounded external experiments plus evidence synthesis."
    if resource=="RESEARCH":
        ids=[p["uncertainty_id"] for p in plans if p["status"]=="READY_FOR_ISOLATED_EXECUTION" and p["execution_mode"]=="READ_ONLY_EVIDENCE_ACQUISITION"]
        return [by_unc[x] for x in ids],"Read-only evidence acquisition is an evidence-backed research demand."
    if resource=="HUNTER_RUNS":
        return [c for c in uncertainty["candidates"] if c["question_type"]=="CAPABILITY_EVIDENCE_GAP" and c["actionability"]=="READY_FOR_INFORMATION_GATHERING"],"Capability-evidence gaps are suitable for bounded public Hunter search."
    if resource=="HUMAN_REVIEW":
        ids=[p["uncertainty_id"] for p in plans if p["status"]=="HUMAN_APPROVAL_REQUIRED"]
        return [by_unc[x] for x in ids],"Human-gated experiments require review attention; recommendation is not approval."
    if resource in {"ENGINEERING_CAPACITY","TESTING"}:
        ids=[p["uncertainty_id"] for p in plans if p["status"]=="READY_FOR_ISOLATED_EXECUTION" and p["execution_mode"]=="ISOLATED_SYNTHETIC_TEST"]
        return [by_unc[x] for x in ids],"Only ready isolated synthetic work creates current engineering/testing demand."
    if resource=="ART_PRODUCTION":
        projects={p["project_id"]:p for p in load("registry/projects.json")["projects"]}
        candidates=[]
        for c in uncertainty["candidates"]:
            p=projects[c["primary_project_id"]]
            q=c["question"].casefold()
            if ("game" in p["categories"] or "education" in p["categories"]) and any(k in q for k in ("art","asset","visual","avatar","scene")) and c["ranking"]["eligible"]:
                candidates.append(c)
        return candidates,"Art capacity requires an explicit art/asset/visual uncertainty; project identity alone is insufficient."
    return [],"No evidence-backed candidate mapping exists for this resource."

def _hold(resource,reason,status="HOLD_NO_ELIGIBLE_EVIDENCE"):
    body={"schema_version":"1.0.0","resource_type":resource,"status":status,"normalized_share_basis_points":10000,"allocated_share_basis_points":0,"unallocated_share_basis_points":10000,"hold_reason":reason,"recommendations":[]}
    return {**body,"plan_hash":hashv(body)}

def resource_plan(resource,uncertainty,experiments):
    if resource=="MODEL_CALLS":
        if not _enabled_nonzero_models():return _hold(resource,"Checked-in Tier 1-3 providers are disabled; deterministic Tier 0 requires no model-call pool.","HOLD_PROVIDER_DISABLED")
    if resource=="API_INFRASTRUCTURE":
        return _hold(resource,"No approved API/infrastructure expansion need is present in the current evidence state.","HOLD_NO_APPROVED_INFRASTRUCTURE_NEED")
    if resource=="CASH":
        return _hold(resource,"No human-approved concrete cash pool/governance receipt is present; normalized allocation cannot move money.","HOLD_HUMAN_GATED_NO_APPROVED_POOL")
    candidates,fit=_resource_candidates(resource,uncertainty,experiments)
    if not candidates:return _hold(resource,fit)
    ranked=_project_best(candidates);shares,allocated,unallocated=_allocate_shares(ranked)
    exp_by_unc={p["uncertainty_id"]:p for p in experiments["plans"]}
    recs=[]
    for c,layer,rank,share in shares:
        exp=exp_by_unc[c["uncertainty_id"]]
        recs.append({
          "project_id":c["primary_project_id"],"source_uncertainty_id":c["uncertainty_id"],"source_experiment_id":exp["experiment_id"],
          "pareto_layer":layer,"rank_order":rank,"share_basis_points":share,
          "authority_requirement":c["authority_requirement"],"actionability":c["actionability"],
          "resource_fit_reason":fit,"uncertainty_components":c["components"],
          "evidence_refs":list(dict.fromkeys([*c["evidence_refs"],f"experiment:{exp['experiment_id']}"]))
        })
    body={"schema_version":"1.0.0","resource_type":resource,"status":"ACTIVE_RECOMMENDATION","normalized_share_basis_points":10000,
          "allocated_share_basis_points":allocated,"unallocated_share_basis_points":unallocated,"hold_reason":None,"recommendations":recs}
    return {**body,"plan_hash":hashv(body)}

def build_allocation_snapshot(uncertainty_snapshot=None,experiment_portfolio=None,generated_at=None):
    if uncertainty_snapshot is None:
        from uncertainty.highest_value_uncertainty import build_snapshot
        uncertainty_snapshot=build_snapshot(generated_at=generated_at)
    if experiment_portfolio is None:
        from experiments.experiment_engine import build_experiment_portfolio
        experiment_portfolio=build_experiment_portfolio(uncertainty_snapshot)
    plans=[resource_plan(r,uncertainty_snapshot,experiment_portfolio) for r in policy()["resource_types"]]
    active=[p for p in plans if p["status"]=="ACTIVE_RECOMMENDATION"]
    hold=[p for p in plans if p["status"]!="ACTIVE_RECOMMENDATION"]
    return {
      "schema_version":"1.0.0","generated_at":generated_at,"mode":policy()["mode"],
      "opaque_score_used":False,"normalized_share_basis_points":policy()["normalized_share_basis_points"],
      "resource_plan_count":len(plans),"active_resource_count":len(active),"hold_resource_count":len(hold),
      "recommendation_entry_count":sum(len(p["recommendations"]) for p in plans),
      "plans":plans
    }

def summary(snapshot):
    by={p["resource_type"]:p for p in snapshot["plans"]}
    def top(resource):
        recs=by[resource]["recommendations"]
        return recs[0]["project_id"] if recs else None
    return {
      "schema_version":"1.0.0","resource_plan_count":snapshot["resource_plan_count"],"active_resource_count":snapshot["active_resource_count"],
      "hold_resource_count":snapshot["hold_resource_count"],"recommendation_entry_count":snapshot["recommendation_entry_count"],
      "active_resource_types":sorted([p["resource_type"] for p in snapshot["plans"] if p["status"]=="ACTIVE_RECOMMENDATION"]),
      "hold_resource_types":sorted([p["resource_type"] for p in snapshot["plans"] if p["status"]!="ACTIVE_RECOMMENDATION"]),
      "top_research_project_id":top("RESEARCH"),"top_hunter_project_id":top("HUNTER_RUNS"),"top_human_review_project_id":top("HUMAN_REVIEW"),
      "cash_allocated_share_basis_points":by["CASH"]["allocated_share_basis_points"],
      "model_calls_allocated_share_basis_points":by["MODEL_CALLS"]["allocated_share_basis_points"],
      "opaque_score_used":snapshot["opaque_score_used"]
    }
