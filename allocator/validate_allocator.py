#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from allocator.portfolio_allocator import build_allocation_snapshot,policy,summary
ROOT=Path(__file__).resolve().parents[1]
class AllocatorValidationError(ValueError):pass
def req(ok,msg):
    if not ok:raise AllocatorValidationError(msg)
def load(p):return json.loads((ROOT/p).read_text())

def _contains_score(value):
    if isinstance(value,dict):
        for k,v in value.items():
            if k in {"score","weighted_score","composite_score"}:return True
            if _contains_score(v):return True
    elif isinstance(value,list):
        return any(_contains_score(x) for x in value)
    return False

def validate_allocator():
    p=policy();pin=load("allocator/AI_BUSINESS_OS_CAPITAL_ALLOCATOR_PIN.json");schema=load("schemas/PORTFOLIO_ALLOCATION_PLAN_SCHEMA.json")
    expected=load("allocator/INITIAL_ALLOCATION_SUMMARY.json");snap=build_allocation_snapshot()
    req(pin["source_revision"]=="21b9023a57392f380c73b2fe952c35840f2e2025","allocator source revision mismatch")
    blobs={"capital_allocator":"cf08795e72de378656f9be963b36efa80b945c33","capital_allocator_contract":"d997ad49c90c9b8bcf298cffbb764d2122a66ad3","capital_allocator_tests":"3c15babd1cd899c32bcf62c0945c57e481a9d511","governance":"40d278e479830d6f76aca7da22b6893f5d0060a7","governance_tests":"3a1429ec8d81e92d1043e89c55a7868b226a6fd4"}
    for k,v in blobs.items():req(pin["components"][k]["blob_sha"]==v,f"{k} blob mismatch")
    req(pin["copied_source_code"] is False,"canonical allocator source must not be copied")
    req(schema["additionalProperties"] is False,"allocation plan schema must be closed")
    req(p["mode"]=="ADVISORY_NORMALIZED_SHARES_ONLY","allocator mode changed")
    req(p["resource_types"]==["MODEL_CALLS","ENGINEERING_CAPACITY","TESTING","RESEARCH","HUNTER_RUNS","ART_PRODUCTION","HUMAN_REVIEW","API_INFRASTRUCTURE","CASH"],"resource types changed")
    req(summary(snap)==expected,"initial allocation summary drifted")
    req(not _contains_score(snap),"opaque/composite score leaked into allocation snapshot")
    req(snap["active_resource_count"]==3 and snap["hold_resource_count"]==6,"unexpected active/hold allocation count")
    for plan in snap["plans"]:
        req(plan["allocated_share_basis_points"]+plan["unallocated_share_basis_points"]==10000,"resource share accounting does not conserve basis points")
        req(all(r["share_basis_points"]<=p["max_project_share_basis_points"] for r in plan["recommendations"]),"project concentration cap exceeded")
        req(all(r["uncertainty_components"] and r["evidence_refs"] for r in plan["recommendations"]),"allocation component evidence missing")
    by={x["resource_type"]:x for x in snap["plans"]}
    req(by["CASH"]["allocated_share_basis_points"]==0 and by["CASH"]["status"]=="HOLD_HUMAN_GATED_NO_APPROVED_POOL","cash allocation authority widened")
    req(by["MODEL_CALLS"]["allocated_share_basis_points"]==0 and by["MODEL_CALLS"]["status"]=="HOLD_PROVIDER_DISABLED","model allocation ignored provider gate")
    req(by["ENGINEERING_CAPACITY"]["allocated_share_basis_points"]==0 and by["TESTING"]["allocated_share_basis_points"]==0,"build/test activity allocated without experiment demand")
    req(by["ART_PRODUCTION"]["allocated_share_basis_points"]==0,"art allocated without art-specific evidence")
    req(by["HUMAN_REVIEW"]["recommendations"][0]["project_id"]=="PRJ-001","highest-value external validation did not lead human-review priority")
    req(by["HUMAN_REVIEW"]["recommendations"][0]["authority_requirement"]=="HUMAN_GATED_ACT","human review recommendation lost authority boundary")
    runtime=(ROOT/"runtime/continuous_runtime.py").read_text()
    req("portfolio_allocation_recommendation.json" in runtime and "build_allocation_snapshot" in runtime,"daily runtime not connected to allocator")
    return {"resource_types":9,"active_resources":3,"hold_resources":6,"recommendations":snap["recommendation_entry_count"],"cash_share_bps":0,"model_call_share_bps":0,"opaque_score":False}

if __name__=="__main__":print("portfolio-brain Step 15 allocator: PASS",json.dumps(validate_allocator(),sort_keys=True))
