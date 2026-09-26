#!/usr/bin/env python3
"""Cross-file Step 13 model-router validator."""
from __future__ import annotations
import json
from pathlib import Path
from model_router.model_router import provider_registry, route_request, value_summary

ROOT=Path(__file__).resolve().parents[1]
class RouterValidationError(ValueError):pass
def req(ok,msg):
    if not ok:raise RouterValidationError(msg)
def load(p):return json.loads((ROOT/p).read_text())

def validate_model_router():
    p=load("model_router/MODEL_ROUTER_POLICY.json");reg=provider_registry()
    req(p["mode"]=="DETERMINISTIC_FIRST","router is not deterministic-first")
    req(p["routing_adaptation"]=="VERIFIED_OUTCOME_FEEDBACK_ONLY","routing adaptation evidence weakened")
    req(set(p["tiers"])=={"0","1","2","3"},"tier set changed")
    enabled_nonzero=[]
    for provider in reg["providers"]:
        for model in provider["models"]:
            if provider["enabled"] and model["enabled"] and model["tier"]>0:enabled_nonzero.append((provider["provider_id"],model["model_id"]))
    req(enabled_nonzero==[
      ("openai","gpt-5.6-luna"),("openai","gpt-5.6-terra"),("openai","gpt-5.6-sol")
    ],"enabled model routes differ from approved GPT-5.6 set")
    det={
      "schema_version":"1.0.0","request_id":"MRQ-VALIDATE-0001","project_ids":["PRJ-000"],"task_kind":"SCHEMA_VALIDATION",
      "deterministic_sufficient":True,"consequence":"HIGH","data_classification":"SANITIZED","authority_class":"OBSERVE",
      "requires_independent_adversarial":False,"builder_independence_group":None,"max_cost_usd":0.0,"max_input_tokens":0,"max_output_tokens":0,
      "provider_allowlist":[],"evidence_refs":["validator:step13"]
    }
    routed=route_request(det,reg);req(routed["status"]=="ROUTED" and routed["tier"]==0 and routed["provider_id"]=="deterministic","Tier 0 routing failed")
    model=dict(det);model.update({"request_id":"MRQ-VALIDATE-0002","task_kind":"ARCHITECTURE","deterministic_sufficient":False,"max_cost_usd":1.0,"max_input_tokens":1000,"max_output_tokens":1000})
    routed_model=route_request(model,reg);req(routed_model["status"]=="ROUTED" and routed_model["tier"]==2 and routed_model["model_id"]=="gpt-5.6-terra","Tier 2 OpenAI routing failed")
    adv=dict(det);adv.update({"request_id":"MRQ-VALIDATE-0003","task_kind":"PROMOTION_VERIFICATION","deterministic_sufficient":False,"requires_independent_adversarial":True,"builder_independence_group":"openai-terra","max_cost_usd":1.0,"max_input_tokens":1000,"max_output_tokens":1000})
    routed_adv=route_request(adv,reg);req(routed_adv["status"]=="ROUTED" and routed_adv["tier"]==3 and routed_adv["model_id"]=="gpt-5.6-sol","Tier 3 OpenAI routing failed")
    ledger=load("model_router/MODEL_ROUTING_LEDGER.json")
    req(ledger["calls"]==[] and ledger["outcomes"]==[],"Step 13 checked-in routing ledger must start empty")
    req(value_summary([],[])=={},"empty routing ledger produced learned value")
    gw=load("model_router/AI_BUSINESS_OS_RUNTIME_GATEWAY_PIN.json")
    req(gw["source_revision"]=="c6276c80828d2632d5fee37cdaaf65f1d5b36427","runtime gateway pin revision mismatch")
    req(gw["gateway"]["blob_sha"]=="fdc77391ce6ed3e0f6db25aed859aa684e0818f0","runtime gateway blob mismatch")
    state=load("PORTFOLIO_BUILD_STATE.json");req(state["repositories"]["REPO-001"]["last_inspected_sha"]=="c6276c80828d2632d5fee37cdaaf65f1d5b36427","source cursor not reconciled")
    return {"tiers":4,"enabled_nonzero_models":3,"tier0_provider":"deterministic","checked_in_calls":0,"checked_in_outcomes":0}

if __name__=="__main__":print("portfolio-brain Step 13 model router: PASS",json.dumps(validate_model_router(),sort_keys=True))
