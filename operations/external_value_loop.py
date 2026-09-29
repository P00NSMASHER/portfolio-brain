"""External-value operating loop for Portfolio Brain Steps 3-8."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
MILESTONES={"PUBLISH_PRODUCT","GET_BUYER_RESPONSE","DELIVER_PAID_WORK","VERIFY_PAYMENT","TEST_PRICE","VALIDATE_DEMAND"}
VALUE_LANES={"EXTERNAL_VALUE_BLOCKER":0,"CUSTOMER_DEMAND_VALIDATION":1,"PRODUCT_DELIVERABLE_COMPLETION":2}
EVIDENCE_CLASSES={"TECHNICAL_VERIFIED","MARKET_VERIFIED","REVENUE_VERIFIED"}

def load(path:str)->dict[str,Any]:
    return json.loads((ROOT/path).read_text(encoding="utf-8"))

def evidence_class(record:dict[str,Any])->str|None:
    if record.get("evidence_class") in EVIDENCE_CLASSES:return record["evidence_class"]
    if record.get("value_class")=="TECHNICAL_RESEARCH_DECISION_UTILITY" and record.get("evidence_state")=="VERIFIED":return "TECHNICAL_VERIFIED"
    if record.get("payment_verified") is True or record.get("verified_revenue_usd",0)>0:return "REVENUE_VERIFIED"
    if record.get("market_signal_verified") is True:return "MARKET_VERIFIED"
    return None

def business_investment_eligible(value:dict[str,Any]|str|None)->bool:
    klass=value if isinstance(value,str) else evidence_class(value or {})
    return klass in {"MARKET_VERIFIED","REVENUE_VERIFIED"}

def demand_signal()->dict[str,Any]:
    obs=load("commercial_evidence/CURRENT_SANITIZED_OBSERVATION.json")
    verified=obs.get("evidence_state")=="VERIFIED" and obs.get("threads_with_human_reply",0)>0
    return {"sensor":"VERIFIED_COMMERCIAL_EVIDENCE","channel":"DEMAND","evidence_class":"MARKET_VERIFIED" if verified else None,
            "verified":verified,"human_reply_threads":obs.get("threads_with_human_reply",0),"scope":obs.get("coverage_scope"),
            "observation_id":obs.get("observation_id")}

def supply_signal()->dict[str,Any]:
    return {"sensor":"PUBLIC_GITHUB","channel":"SUPPLY","verified":False,"can_justify_business_investment":False}

def owner_actions()->list[dict[str,Any]]:
    doc=load("operations/MICRO_PRODUCT_FACTORY.json")
    for sku in sorted(doc["skus"],key=lambda row:row["rank"]):
        if sku.get("status")=="READY_FOR_PUBLISH" and sku.get("publication_status")=="NOT_PUBLISHED":
            return [{"action_id":f"OWNER-{sku['sku_id']}-PUBLISH","milestone":"PUBLISH_PRODUCT","status":"WAITING_OWNER",
                     "sku_id":sku["sku_id"],"price_usd":sku["price_usd"],"package":sku["bundle_name"],
                     "message":f"OWNER ACTION REQUIRED: Publish {sku['sku_id']} at USD {sku['price_usd']:.2f} using {sku['bundle_name']}.",
                     "resume_condition":f"{sku['sku_id']}.publication_status != NOT_PUBLISHED","authority":"OWNER_REQUIRED"}]
    return []

def sku_blocker_candidates()->list[dict[str,Any]]:
    rows=[]
    for sku in load("operations/MICRO_PRODUCT_FACTORY.json")["skus"]:
        if sku.get("status")=="READY_FOR_RUNTIME_QA":
            rows.append({"source_ref":sku["sku_id"],"project_ids":["PRJ-000"],"work_type":"TEST","assigned_agent_id":"AGT-TESTER",
                         "agent_goal_type":"REGRESSION_VALIDATION","required_authority":"EXPERIMENT","consequence":"HIGH",
                         "external_milestone":"PUBLISH_PRODUCT","value_lane":"EXTERNAL_VALUE_BLOCKER","blocks_external_milestone":True,
                         "reason":f"{sku['sku_id']} runtime QA blocks bounded product publication.",
                         "evidence_refs":[f"micro-product:{sku['sku_id']}",f"artifact:{sku['artifact_name']}"]})
    return rows

def operator_summary()->dict[str,Any]:
    doc=load("operations/MICRO_PRODUCT_FACTORY.json");demand=demand_signal();actions=owner_actions()
    qa=[x for x in doc["skus"] if x.get("status")=="READY_FOR_RUNTIME_QA"]
    if actions: milestone="PUBLISH_PRODUCT";blocker=actions[0]["message"]
    elif qa: milestone="PUBLISH_PRODUCT";blocker=f"Runtime QA blocks {qa[0]['sku_id']} publication."
    else: milestone="VALIDATE_DEMAND";blocker="Await verified buyer or market evidence."
    return {"money_earned_usd":float(doc["verified_revenue_usd"]),"active_external_experiment":"Roblox micro-product factory",
            "closest_external_milestone":milestone,"current_blocker":blocker,
            "action_required_from_you":actions[0]["message"] if actions else "None",
            "last_verified_customer_market_signal":f"MARKET_VERIFIED: {demand['human_reply_threads']} verified human-reply thread(s)." if demand["verified"] else "None - current commercial observation is not VERIFIED market evidence."}
