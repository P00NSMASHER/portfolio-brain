#!/usr/bin/env python3
"""Cross-file Step 11 uncertainty-engine validator."""
from __future__ import annotations
import json
from pathlib import Path
from uncertainty.highest_value_uncertainty import build_snapshot, dominates, policy, summary

ROOT=Path(__file__).resolve().parents[1]
class UncertaintyValidationError(ValueError):pass
def req(ok,msg):
    if not ok:raise UncertaintyValidationError(msg)
def load(p):return json.loads((ROOT/p).read_text())

def validate_uncertainty():
    p=policy();schema=load("schemas/UNCERTAINTY_SCHEMA.json")
    baseline=load("uncertainty/INITIAL_UNCERTAINTY_SUMMARY.json")
    snapshot=build_snapshot()
    req(p["scalar_score_prohibited"] is True,"scalar scoring prohibition removed")
    req(p["ranking"]["method"]=="PARETO_LAYERS_THEN_EXPLICIT_LEXICOGRAPHIC_TIE_BREAK","ranking method changed")
    req(schema["additionalProperties"] is False,"uncertainty schema must be closed")
    req(baseline["schema_version"]=="1.0.0" and baseline["candidate_count"]==20,"initial uncertainty baseline corrupted")
    req(snapshot["candidate_count"]==20 and snapshot["eligible_candidate_count"]==18,"unexpected candidate counts")
    req(snapshot["pareto_front_candidate_ids"]==["UNC-EXTERNAL-PRJ-001","UNC-LEARNING-PRJ-000"],"unexpected Pareto front")
    req(snapshot["selected_uncertainty_id"]=="UNC-EXTERNAL-PRJ-001","highest-value uncertainty changed")
    selected=next(c for c in snapshot["candidates"] if c["uncertainty_id"]==snapshot["selected_uncertainty_id"])
    req(selected["authority_requirement"]=="BOUNDED_ACT" and selected["actionability"]=="READY_FOR_BOUNDED_EXTERNAL_EXECUTION","selected bounded authority path missing")
    req("CUSTOMER_COMMUNICATION" not in selected["approval_requirements"],"bounded customer communication remained approval-gated")
    req(set(selected["components"])==set(p["components"]),"selected component vector incomplete")
    req(all(x["evidence_refs"] for x in selected["components"].values()),"component evidence missing")
    req(all(c["components"]["test_cost"]["basis_type"]=="POLICY_ESTIMATE" for c in snapshot["candidates"]),"test cost must remain labeled estimate")
    req(all(c["components"]["time_to_evidence"]["basis_type"]=="POLICY_ESTIMATE" for c in snapshot["candidates"]),"time-to-evidence must remain labeled estimate")
    star=next(c for c in snapshot["candidates"] if c["uncertainty_id"]=="UNC-EXTERNAL-PRJ-005")
    abvm=next(c for c in snapshot["candidates"] if c["uncertainty_id"]=="UNC-EXTERNAL-PRJ-006")
    for education in (star,abvm):
        req(education["authority_requirement"]=="BOUNDED_ACT","education validation did not move to bounded ACT")
        req(education["actionability"]=="READY_FOR_BOUNDED_EXTERNAL_EXECUTION","education validation is still approval-blocked")
        req(education["approval_requirements"]==[],"adult-only education validation retained unnecessary approvals")
        req("action-policy:action_engine/EDUCATION_VALIDATION_POLICY.json" in education["evidence_refs"],"education validation policy provenance missing")
        req("adult-stakeholder" in education["question"] and "without direct child contact" in education["question"],"adult-only education scope not explicit")
    education_policy=load("action_engine/EDUCATION_VALIDATION_POLICY.json")
    req(education_policy["direct_minor_contact_allowed"] is False and education_policy["child_data_collection_allowed"] is False and education_policy["consequential_child_facing_change_allowed"] is False,"education child-safety boundaries weakened")
    trade=next(c for c in snapshot["candidates"] if c["uncertainty_id"]=="UNC-CAPABILITY-PRJ-007")
    req(trade["authority_requirement"]=="OBSERVE_ONLY","market research uncertainty must not grant trading authority")
    canary=next(c for c in snapshot["candidates"] if c["uncertainty_id"]=="UNC-CANARY-PRJ-000")
    req(canary["actionability"]=="BLOCKED" and "STEP-24-CANARY-GATE" in canary["hard_blockers"],"canary sequence gate missing")
    source=load("PORTFOLIO_BUILD_STATE.json")["repositories"]["REPO-001"]["last_inspected_sha"]
    req(source=="c6276c80828d2632d5fee37cdaaf65f1d5b36427","source cursor not reconciled")
    runtime=(ROOT/"runtime/continuous_runtime.py").read_text()
    req("highest_value_uncertainty.json" in runtime and "build_uncertainty_snapshot" in runtime,"daily runtime not connected to uncertainty engine")
    return {"candidates":snapshot["candidate_count"],"eligible":snapshot["eligible_candidate_count"],"pareto_front":len(snapshot["pareto_front_candidate_ids"]),"selected":snapshot["selected_uncertainty_id"],"scalar_score":False}

if __name__=="__main__":print("portfolio-brain Step 11 uncertainty: PASS",json.dumps(validate_uncertainty(),sort_keys=True))
