#!/usr/bin/env python3
"""Validate the machine-readable Portfolio Brain authority matrix."""
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
class BoundaryValidationError(ValueError): pass
def req(ok,msg):
    if not ok: raise BoundaryValidationError(msg)
def load(path): return json.loads((ROOT/path).read_text(encoding="utf-8"))

EXPECTED_ACTIONS={
 "OBSERVATION","REPOSITORY_CANDIDATE_WRITE","PR_CREATION","PROTECTED_BOT_REPAIR_INTEGRATION",
 "PRODUCTION_DEPLOYMENT","CUSTOMER_EMAIL_GMAIL","FINANCIAL_ACTION","DESTRUCTIVE_ACTION",
 "CHILD_FACING_ACTION","LIVE_TRADING","PAGES_PUBLICATION"
}

def validate_boundaries()->dict[str,object]:
    policy=load("governance/boundaries.json")
    projects=load("registry/projects.json")["projects"]
    adapters=load("adapters/ADAPTER_REGISTRY.json")["adapters"]

    req(policy["schema_version"]=="1.0.0","boundary schema mismatch")
    req(policy["authority_model"]=="DENY_BY_DEFAULT_PROJECT_SCOPED_NO_INHERITANCE","authority model weakened")
    req(policy["default_effect"]=="DENY","default authority must deny")
    deps=policy["core_autonomy_dependencies"]
    req(deps=={"interactive_chatgpt_required":False,"gmail_required":False},"core autonomy gained an external connector dependency")
    req(set(policy["actions"])==EXPECTED_ACTIONS,"authority action coverage changed")

    actions=policy["actions"]
    for action in ("PRODUCTION_DEPLOYMENT","FINANCIAL_ACTION","DESTRUCTIVE_ACTION","CHILD_FACING_ACTION"):
        req(actions[action]["decision"]=="HUMAN_APPROVAL_REQUIRED","high-risk action lost human gate: "+action)
        req(actions[action]["autonomous_allowed"] is False,"high-risk action became autonomous: "+action)
    gmail=actions["CUSTOMER_EMAIL_GMAIL"]
    req(gmail["decision"]=="EXPLICIT_MACHINE_POLICY_GATE" and gmail["autonomous_allowed"] is True,"explicit Gmail exception not represented")
    req(gmail["core_runtime_dependency"] is False and gmail["policy_ref"]=="action_engine/ACTION_POLICY.json","Gmail became a core dependency or lost policy binding")
    action_policy=load("action_engine/ACTION_POLICY.json")
    req(action_policy["enabled"] is True and "CUSTOMER_EMAIL" in action_policy["allowed_actions"],"governance Gmail exception lacks machine-policy authorization")
    req(actions["LIVE_TRADING"]["decision"]=="PROHIBITED" and actions["LIVE_TRADING"]["autonomous_allowed"] is False,"live trading must remain prohibited")
    req(actions["PAGES_PUBLICATION"]["publication_only"] is True,"Pages must remain publication-only")
    req(actions["PAGES_PUBLICATION"]["production_deploy_authority"] is False,"Pages publication gained deployment authority")
    bot=actions["PROTECTED_BOT_REPAIR_INTEGRATION"]
    req(bot["project_ids"]==["PRJ-000"] and bot["repository_ids"]==["REPO-008"],"bot integration escaped Portfolio Brain")
    req("APP_5121826_EXACT_HEAD_SUCCESS" in bot["requires"],"hosted verifier gate missing from protected integration")
    req(bot["bypass_authority"] is False,"bot integration gained bypass authority")

    registered={row["project_id"] for row in projects}
    caps=policy["project_capabilities"]
    req({row["project_id"] for row in caps}==registered,"project capability coverage mismatch")
    req(len(caps)==len(registered),"duplicate project capability record")
    enabled_by_project={pid:set() for pid in registered}
    for adapter in adapters:
        if adapter["enabled"]:
            req(adapter["authority_class"]=="OBSERVE","enabled repository adapter widened beyond OBSERVE")
            for pid in adapter["project_ids"]:
                req(pid in registered,"adapter references unknown project")
                enabled_by_project[pid].add(adapter["repository_id"])

    for row in caps:
        pid=row["project_id"]
        req(set(row)=={"project_id","READ_OBSERVE","CANDIDATE_PR","DEPLOY","EXTERNAL_ACTION"},"project capability fields changed")
        read=row["READ_OBSERVE"]
        req(read["allowed"] is True,"registered project observation unexpectedly disabled")
        req(set(read["repository_ids"])==enabled_by_project[pid],"project observation repositories do not match enabled adapters")
        req(row["DEPLOY"]=={"allowed":False},"project gained deploy authority")
        req(row["EXTERNAL_ACTION"]=={"allowed":False},"project gained external-action authority")
        candidate=row["CANDIDATE_PR"]
        if pid=="PRJ-000":
            req(candidate["allowed"] is True and candidate["repository_ids"]==["REPO-008"],"Portfolio Brain candidate scope changed")
            req(candidate["branch_prefixes"]==["factory/","auto-repair/"],"candidate branch scope changed")
        else:
            req(candidate=={"allowed":False,"repository_ids":[],"branch_prefixes":[]},"downstream project inherited candidate PR authority")

    abvm=policy["constrained_integrations"]["PRJ-006"]
    req(abvm["repository_id"]=="REPO-003","ABVM repository binding changed")
    req(set(abvm["allowed_evidence"])=={"AUTOMATION_HEALTH","PROGRESS_EVIDENCE"},"ABVM evidence scope widened")
    req(abvm["persisted_payload"]=="SANITIZED_METADATA_ONLY","ABVM payload boundary widened")
    req(abvm["child_facing_mutation"] is False,"ABVM gained child-facing mutation")
    req(abvm["deployment_authority"] is False,"ABVM gained deployment authority")
    req(abvm["school_content_publication_authority"] is False,"ABVM gained school-content publication authority")

    return {"projects":len(registered),"enabled_adapters":sum(1 for a in adapters if a["enabled"]),"authority_model":policy["authority_model"],"abvm_scope":abvm["allowed_evidence"]}

if __name__=="__main__":
    print("portfolio-brain governance boundaries: PASS",json.dumps(validate_boundaries(),sort_keys=True))
