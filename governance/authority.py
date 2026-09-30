#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[1]
BOUNDARIES=ROOT/"governance"/"boundaries.json"
CAPABILITIES={"READ_OBSERVE","CANDIDATE_PR","DEPLOY","EXTERNAL_ACTION"}
ACTIONS={"observation","repository_candidate_write","pr_creation","protected_bot_repair_integration","production_deployment","customer_email_gmail","financial_actions","destructive_actions","child_facing_actions","live_trading","pages_publication"}
class BoundaryError(ValueError):pass
def req(ok:bool,msg:str)->None:
    if not ok:raise BoundaryError(msg)
def load_boundaries(path:Path|None=None)->dict[str,Any]:return json.loads((path or BOUNDARIES).read_text(encoding="utf-8"))
def _registry_project_ids()->set[str]:
    return {x["project_id"] for x in json.loads((ROOT/"registry"/"projects.json").read_text())["projects"]}
def validate_boundaries(data:dict[str,Any]|None=None)->dict[str,int]:
    b=data or load_boundaries()
    req(b.get("schema_version")=="1.0.0" and b.get("boundary_id")=="portfolio-authority-boundaries-v1","boundary identity mismatch")
    req(b.get("default_policy")=="DENY","authority must fail closed")
    req(b.get("inheritance_policy")=="NO_PROJECT_INHERITS_PORTFOLIO_BRAIN_AUTHORITY","project authority inheritance enabled")
    req(set(b.get("capability_keys",[]))==CAPABILITIES,"capability keys drifted")
    req(b.get("core_autonomy_dependencies")=={"interactive_chatgpt_required":False,"gmail_required":False,"external_customer_communication_required":False},"core autonomy gained connector dependency")
    rows=b.get("projects");req(isinstance(rows,list),"project boundaries missing");by={}
    for row in rows:
        req(set(row)=={"project_id","capabilities","hard_boundaries"},"project boundary fields changed")
        pid=row["project_id"];req(pid not in by,"duplicate project boundary")
        req(set(row["capabilities"])==CAPABILITIES and all(type(v) is bool for v in row["capabilities"].values()),"project capability vector invalid")
        req(isinstance(row["hard_boundaries"],list) and len(row["hard_boundaries"])==len(set(row["hard_boundaries"])),"hard boundaries invalid")
        by[pid]=row
    req(set(by)==_registry_project_ids(),"authority matrix does not cover registry exactly")
    req(by["PRJ-000"]["capabilities"]["CANDIDATE_PR"] is True,"PRJ-000 candidate PR capability missing")
    for pid,row in by.items():
        if pid!="PRJ-000":req(row["capabilities"]["CANDIDATE_PR"] is False,f"{pid} inherited candidate PR authority")
        req(row["capabilities"]["DEPLOY"] is False,f"{pid} gained deploy authority")
        req(row["capabilities"]["EXTERNAL_ACTION"] is False,f"{pid} gained external action authority")
    req(by["PRJ-006"]["capabilities"]=={"READ_OBSERVE":True,"CANDIDATE_PR":False,"DEPLOY":False,"EXTERNAL_ACTION":False},"ABVM authority widened")
    req({"CHILD_FACING_MUTATION_HUMAN_GATED","SCHOOL_CONTENT_PUBLICATION_HUMAN_GATED","PRODUCTION_DEPLOYMENT_HUMAN_GATED"}<=set(by["PRJ-006"]["hard_boundaries"]),"ABVM hard boundary missing")
    req({"LIVE_TRADING_PROHIBITED","BROKER_ORDER_EXECUTION_PROHIBITED"}<=set(by["PRJ-007"]["hard_boundaries"]),"trading prohibition missing")
    m=b.get("action_matrix",{});req(set(m)==ACTIONS,"action matrix incomplete")
    for k in ("production_deployment","customer_email_gmail","financial_actions","destructive_actions","child_facing_actions"):req(m[k]["decision"]=="HUMAN_APPROVAL_REQUIRED",f"{k} gate weakened")
    req(m["customer_email_gmail"]["core_autonomy_dependency"] is False,"Gmail became core dependency")
    req(m["live_trading"]["decision"]=="PROHIBITED","live trading prohibition weakened")
    req(m["pages_publication"]["decision"]=="ALLOWED_SANITIZED_PUBLICATION_ONLY" and m["pages_publication"]["production_deployment_authority"] is False and m["pages_publication"]["public_persistence"]=="SANITIZED_ONLY","Pages boundary widened")
    return {"projects":len(by),"capabilities":len(CAPABILITIES),"actions":len(m)}
def project_capability(project_id:str,capability:str)->bool:
    b=load_boundaries();validate_boundaries(b);req(capability in CAPABILITIES,"unknown capability")
    row=next((x for x in b["projects"] if x["project_id"]==project_id),None);req(row is not None,"unknown project")
    return bool(row["capabilities"][capability])
def require_project_capability(project_id:str,capability:str)->None:
    if not project_capability(project_id,capability):raise BoundaryError(f"{project_id} lacks {capability}")
def action_boundary(action:str)->dict[str,Any]:
    b=load_boundaries();validate_boundaries(b);req(action in ACTIONS,"unknown governed action");return b["action_matrix"][action]
