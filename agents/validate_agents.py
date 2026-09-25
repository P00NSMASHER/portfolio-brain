#!/usr/bin/env python3
from __future__ import annotations
import json,tempfile
from pathlib import Path
from agents.persistent_agents import PortfolioAgentRuntime
ROOT=Path(__file__).resolve().parents[1]
class AgentValidationError(ValueError):pass
def req(ok,msg):
    if not ok:raise AgentValidationError(msg)
def load(p):return json.loads((ROOT/p).read_text())
def validate_agents():
    reg=load("agents/AGENT_REGISTRY.json");policy=load("agents/AGENT_POLICY.json");seed=load("agents/AGENT_STATE_SEED.json");pin=load("agents/AI_BUSINESS_OS_PERSISTENT_AGENT_PIN.json")
    roles=reg["roles"];by={r["agent_id"]:r for r in roles};expected={"PORTFOLIO_MANAGER","HUNTER","RESEARCHER","PRODUCT_ANALYST","ENGINEER","TESTER","AUDITOR","RED_TEAM","DATA_STEWARD","COMMERCIAL_ANALYST"}
    req(len(roles)==10 and {r["role_key"] for r in roles}==expected,"persistent role set mismatch");req(len(by)==10,"agent IDs must be unique")
    req(pin["source_revision"]=="21b9023a57392f380c73b2fe952c35840f2e2025","persistent-agent source revision mismatch")
    blobs={"durable_runtime":"f200573259bcf29c09fbe9e480df4f983dd50903","worker_contract":"19c9ae71701f6fa5ae9ed56ba29b3a965e4f360f","persistent_worker":"60e41f08508d93b6a6b6c16da25582a8481d536a","persistent_worker_test":"10652da1cd107c8e983f4166b2483c5244824e81","runtime_test":"20c10bf052fb7742bf5ef687a25e2b6b1fcae81b","lease_control_sql":"c419ff6260fe0c0da61b49ba6f153ac62c0efcb8","role_contracts":"0c12935168a72f66da058e1443f136549b025db8","runtime_gateway":"fdc77391ce6ed3e0f6db25aed859aa684e0818f0"}
    for k,v in blobs.items():req(pin["components"][k]["blob_sha"]==v,f"{k} blob mismatch")
    req(pin["copied_source_code"] is False,"canonical persistent-agent source must not be copied");req(all(r["persistent"] and not r["human_act_allowed"] and r["max_autonomy"]!="ACT" for r in roles),"agent authority widened")
    req([r["agent_id"] for r in roles if r["builder_eligible"]]==["AGT-ENGINEER"],"only Engineer may build")
    verifiers={r["role_key"] for r in roles if r["verifier_eligible"]};req(verifiers=={"TESTER","AUDITOR","RED_TEAM","DATA_STEWARD"},"verifier role set mismatch");req(all(not r["builder_eligible"] for r in roles if r["verifier_eligible"]),"builder/verifier separation weakened")
    req(by["AGT-AUDITOR"]["max_model_tier"]==3 and by["AGT-RED-TEAM"]["max_model_tier"]==3,"Tier 3 verifier ceiling missing");req(by["AGT-ENGINEER"]["max_model_tier"]<=2,"builder cannot route Tier 3");req(by["AGT-PORTFOLIO-MANAGER"]["can_delegate"] and sum(1 for r in roles if r["can_delegate"])==1,"delegation authority widened")
    for r in roles:
        if r["parent_agent_id"] is not None:req(r["parent_agent_id"] in by,"agent parent missing")
    req(not (set(policy["global_prohibitions"]) & {g for r in roles for g in r["allowed_goal_types"]}),"prohibited ACT leaked into goal types")
    req(len(seed["agents"])==10 and seed["work_items"]==[] and seed["evidence_refs"]==[],"agent seed fabricated work/evidence")
    state=load("PORTFOLIO_BUILD_STATE.json");req(state["repositories"]["REPO-001"]["last_inspected_sha"]==pin["source_revision"],"persistent-agent source cursor drifted")
    with tempfile.TemporaryDirectory() as td:
        rt=PortfolioAgentRuntime(Path(td)/"agents.sqlite3");req(rt.event_chain_valid(),"fresh event chain invalid");count=rt.conn.execute("SELECT count(*) AS n FROM agents").fetchone()["n"];rt.close()
    req(count==10,"runtime failed to bootstrap agents")
    provider=load("model_router/PROVIDER_REGISTRY.json");req(not any(p["enabled"] and m["enabled"] and m["tier"]>0 for p in provider["providers"] for m in p["models"]),"non-Tier-0 model unexpectedly enabled")
    return {"roles":10,"builder_roles":1,"verifier_roles":4,"human_act_roles":0,"seed_work_items":0,"enabled_nonzero_models":0}
if __name__=="__main__":print("portfolio-brain Step 14 agents: PASS",json.dumps(validate_agents(),sort_keys=True))
