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
    expected=load("uncertainty/INITIAL_UNCERTAINTY_SUMMARY.json")
    snapshot=build_snapshot()
    req(p["scalar_score_prohibited"] is True,"scalar scoring prohibition removed")
    req(p["ranking"]["method"]=="PARETO_LAYERS_THEN_EXPLICIT_LEXICOGRAPHIC_TIE_BREAK","ranking method changed")
    req(schema["additionalProperties"] is False,"uncertainty schema must be closed")
    req(summary(snapshot)==expected,"initial uncertainty snapshot drifted")
    req(snapshot["candidate_count"]==20 and snapshot["eligible_candidate_count"]==18,"unexpected candidate counts")
    req(snapshot["pareto_front_candidate_ids"]==["UNC-EXTERNAL-PRJ-001","UNC-LEARNING-PRJ-000"],"unexpected Pareto front")
    req(snapshot["selected_uncertainty_id"]=="UNC-EXTERNAL-PRJ-001","highest-value uncertainty changed")
    selected=next(c for c in snapshot["candidates"] if c["uncertainty_id"]==snapshot["selected_uncertainty_id"])
    req(selected["authority_requirement"]=="HUMAN_GATED_ACT" and selected["actionability"]=="HUMAN_APPROVAL_REQUIRED","selected human authority boundary lost")
    req("CUSTOMER_COMMUNICATION" in selected["approval_requirements"],"customer communication approval missing")
    req(set(selected["components"])==set(p["components"]),"selected component vector incomplete")
    req(all(x["evidence_refs"] for x in selected["components"].values()),"component evidence missing")
    req(all(c["components"]["test_cost"]["basis_type"]=="POLICY_ESTIMATE" for c in snapshot["candidates"]),"test cost must remain labeled estimate")
    req(all(c["components"]["time_to_evidence"]["basis_type"]=="POLICY_ESTIMATE" for c in snapshot["candidates"]),"time-to-evidence must remain labeled estimate")
    star=next(c for c in snapshot["candidates"] if c["uncertainty_id"]=="UNC-EXTERNAL-PRJ-005")
    abvm=next(c for c in snapshot["candidates"] if c["uncertainty_id"]=="UNC-EXTERNAL-PRJ-006")
    req("CONSEQUENTIAL_CHILD_FACING_CHANGE" in star["approval_requirements"] and "CONSEQUENTIAL_CHILD_FACING_CHANGE" in abvm["approval_requirements"],"child-facing approval boundary missing")
    trade=next(c for c in snapshot["candidates"] if c["uncertainty_id"]=="UNC-CAPABILITY-PRJ-007")
    req(trade["authority_requirement"]=="OBSERVE_ONLY","market research uncertainty must not grant trading authority")
    canary=next(c for c in snapshot["candidates"] if c["uncertainty_id"]=="UNC-CANARY-PRJ-000")
    req(canary["actionability"]=="BLOCKED" and "STEP-24-CANARY-GATE" in canary["hard_blockers"],"canary sequence gate missing")
    source=load("PORTFOLIO_BUILD_STATE.json")["repositories"]["REPO-001"]["last_inspected_sha"]
    req(source=="dcca6215f2439bb55391335fe0513f471c762290","source cursor not reconciled")
    runtime=(ROOT/"runtime/continuous_runtime.py").read_text()
    req("highest_value_uncertainty.json" in runtime and "build_uncertainty_snapshot" in runtime,"daily runtime not connected to uncertainty engine")
    return {"candidates":snapshot["candidate_count"],"eligible":snapshot["eligible_candidate_count"],"pareto_front":len(snapshot["pareto_front_candidate_ids"]),"selected":snapshot["selected_uncertainty_id"],"scalar_score":False}

if __name__=="__main__":print("portfolio-brain Step 11 uncertainty: PASS",json.dumps(validate_uncertainty(),sort_keys=True))
