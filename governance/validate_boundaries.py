#!/usr/bin/env python3
"""Validate explicit project-scoped authority boundaries."""
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class BoundaryError(ValueError):
    pass

def req(ok: bool, message: str)->None:
    if not ok:
        raise BoundaryError(message)

def load(path: str):
    return json.loads((ROOT/path).read_text(encoding="utf-8"))

def validate_boundaries()->dict:
    policy=load("governance/boundaries.json")
    projects=load("registry/projects.json")["projects"]
    adapters=load("adapters/ADAPTER_REGISTRY.json")["adapters"]
    runtime=load("runtime/RUNTIME_POLICY.json")
    operating=load("operations/OPERATING_MODE_POLICY.json")

    req(policy["default_decision"]=="DENY","authority default must deny")
    req(policy["inheritance_policy"]=="NO_PROJECT_INHERITS_PORTFOLIO_BRAIN_AUTHORITY","project authority inheritance enabled")
    req(policy["core_autonomy_dependencies"]=={"interactive_chatgpt_required":False,"gmail_required":False},"core autonomy gained connector dependency")
    req(operating.get("interactive_chatgpt_runtime_dependency") is False,"interactive ChatGPT became a core runtime dependency")
    req(runtime["authority_class"]=="OBSERVE" and runtime["downstream_writes_allowed"]==0 and runtime["external_actions_allowed"]==0,
        "observation runtime gained mutation/action authority")

    matrix=policy["authority_matrix"]
    required={"OBSERVATION","REPOSITORY_CANDIDATE_WRITE","PR_CREATION","PROTECTED_BOT_REPAIR_INTEGRATION",
              "PRODUCTION_DEPLOYMENT","CUSTOMER_EMAIL_GMAIL","FINANCIAL_ACTION","DESTRUCTIVE_ACTION",
              "CHILD_FACING_ACTION","LIVE_TRADING","PAGES_PUBLIC_PUBLICATION"}
    req(set(matrix)==required,"authority matrix coverage drifted")
    req(matrix["PRODUCTION_DEPLOYMENT"]["autonomous"] is False,"production deployment became autonomous")
    req(matrix["FINANCIAL_ACTION"]["autonomous"] is False,"financial action became autonomous")
    req(matrix["DESTRUCTIVE_ACTION"]["autonomous"] is False,"destructive action became autonomous")
    req(matrix["CHILD_FACING_ACTION"]["autonomous"] is False,"child-facing action became autonomous")
    req(matrix["LIVE_TRADING"]["decision"]=="PROHIBITED","live trading prohibition weakened")
    req(matrix["PAGES_PUBLIC_PUBLICATION"]["production_deploy_authority"] is False,"Pages publication granted deployment authority")
    req(matrix["PAGES_PUBLIC_PUBLICATION"]["verification_credit"]=="NONE_BY_ITSELF","Pages publication gained verification credit")
    req(matrix["CUSTOMER_EMAIL_GMAIL"]["core_dependency"] is False and matrix["CUSTOMER_EMAIL_GMAIL"]["authority_from_observation"] is False,
        "Gmail became core autonomy or inherited observation authority")
    req(matrix["PROTECTED_BOT_REPAIR_INTEGRATION"]["bypass_protection"] is False,"protected repair gained bypass")

    rows=policy["project_capabilities"]
    project_ids={p["project_id"] for p in projects}
    req({r["project_id"] for r in rows}==project_ids,"project capability coverage mismatch")
    req(len(rows)==len(project_ids),"duplicate project capability row")
    for row in rows:
        caps=row["capabilities"]
        req(set(caps)=={"READ_OBSERVE","CANDIDATE_PR","DEPLOY","EXTERNAL_ACTION"},"project capability fields changed")
        req(all(type(value) is bool for value in caps.values()),"project capabilities must be explicit booleans")
        req(caps["READ_OBSERVE"] is True,"registered project lost read observation")
        req(caps["DEPLOY"] is False and caps["EXTERNAL_ACTION"] is False,
            f"{row['project_id']} forwarding layer gained deploy/external action")
        if row["project_id"]!="PRJ-000":
            req(caps["CANDIDATE_PR"] is False,f"{row['project_id']} inherited candidate PR authority")
    root=next(r for r in rows if r["project_id"]=="PRJ-000")
    req(root["capabilities"]["CANDIDATE_PR"] is True,"Portfolio Brain protected candidate capability missing")

    enabled=[a for a in adapters if a.get("enabled")]
    by_project={r["project_id"]:r for r in rows}
    for adapter in enabled:
        req(adapter["authority_class"]=="OBSERVE","enabled adapter authority widened")
        for pid in adapter["project_ids"]:
            row=by_project[pid]
            req(row["capabilities"]["READ_OBSERVE"] is True,"adapter routes to project without read capability")
            req(row["repository_id"]==adapter["repository_id"],"project capability repository binding mismatches enabled adapter")

    abvm=by_project["PRJ-006"]
    req(abvm["repository_id"]=="REPO-003","ABVM repository binding changed")
    req(abvm["observation_evidence_allowlist"]==["AUTOMATION_HEALTH","AUTOMATION_PROGRESS"],"ABVM observation scope widened")
    req(abvm["child_facing_mutation"] is False and abvm["school_content_publication"] is False,"ABVM child/school publication authority widened")
    trading=by_project["PRJ-007"]
    req(not any(trading["capabilities"][x] for x in ("CANDIDATE_PR","DEPLOY","EXTERNAL_ACTION")),"trading research gained action capability")

    semantics=policy["semantics"]
    req(semantics["heartbeat"]=="CONNECTIVITY_TELEMETRY_ONLY","heartbeat semantics widened")
    req(semantics["notification"]=="ALERT_ONLY","notification semantics widened")
    req(semantics["pages_publication"]=="SANITIZED_PUBLICATION_ONLY","Pages semantics widened")
    return {"projects":len(rows),"enabled_adapters":len(enabled),"default_decision":policy["default_decision"]}

def main()->None:
    print(json.dumps(validate_boundaries(),sort_keys=True))

if __name__=="__main__":
    main()
