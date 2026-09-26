#!/usr/bin/env python3
"""Cross-file Step 12 experiment-engine validator."""
from __future__ import annotations
import json
from pathlib import Path
from experiments.experiment_engine import build_experiment_portfolio, validate_outcome

ROOT=Path(__file__).resolve().parents[1]
class ExperimentValidationError(ValueError):pass
def req(ok,msg):
    if not ok:raise ExperimentValidationError(msg)
def load(p):return json.loads((ROOT/p).read_text())

def validate_experiments():
    pin=load("experiments/HUNTER_EXPERIMENT_SEMANTICS_PIN.json")
    policy=load("experiments/EXPERIMENT_POLICY.json")
    exp_schema=load("schemas/EXPERIMENT_SCHEMA.json");out_schema=load("schemas/EXPERIMENT_OUTCOME_SCHEMA.json")
    outcomes=load("experiments/EXPERIMENT_OUTCOME_LEDGER.json")
    uncertainty=__import__("uncertainty.highest_value_uncertainty",fromlist=["build_snapshot"]).build_snapshot()
    portfolio=build_experiment_portfolio(uncertainty)
    req(pin["source_revision"]=="c6276c80828d2632d5fee37cdaaf65f1d5b36427","unexpected experiment source revision")
    expected={"allocator":"7832c10f16925d35b6446c24a999b9cef5e212b5","work_identity":"ac783e93b8c1db54a374d00de1cfb8dd7883e617","action_router":"1941232cf3ff9b11ac5191b7001f29b387c23ea2","action_tests":"473df7dc20558aff91eafe12fa89598e2d4f5ae4"}
    for k,v in expected.items():req(pin["components"][k]["blob_sha"]==v,f"{k} blob mismatch")
    req(pin["copied_source_code"] is False,"canonical experiment source must not be copied")
    req(exp_schema["additionalProperties"] is False and out_schema["additionalProperties"] is False,"experiment schemas must be closed")
    req(policy["automatic_external_act"] is True and policy["automatic_model_calls"] is True,"bounded external/model execution not enabled")
    req(policy["automatic_downstream_modify"] is False and policy["automatic_cash_spend"] is False,"downstream/cash authority widened")
    req(portfolio["plan_count"]==20,"unexpected experiment plan count")
    req(portfolio["status_counts"]=={"READY_FOR_ISOLATED_EXECUTION":12,"READY_FOR_BOUNDED_EXECUTION":4,"HUMAN_APPROVAL_REQUIRED":2,"BLOCKED":2},"unexpected experiment status distribution")
    selected=next(p for p in portfolio["plans"] if p["experiment_id"]==portfolio["selected_experiment_id"])
    req(selected["uncertainty_id"]=="UNC-EXTERNAL-PRJ-001","selected experiment not bound to selected uncertainty")
    req(selected["status"]=="READY_FOR_BOUNDED_EXECUTION" and selected["autonomous_execution_allowed"] is True,"selected external validation not bounded-executable")
    req(selected["execution_mode"]=="BOUNDED_EXTERNAL_VALIDATION","selected external validation mode mismatch")
    req("CUSTOMER_COMMUNICATION" not in selected["approval_requirements"],"selected bounded experiment remained approval-gated")
    req(selected["cost_boundary"]["external_messages_max"]==1 and selected["cost_boundary"]["autonomous_cash_spend_usd_max"]==0,"selected bounded action ceiling mismatch")
    star=next(p for p in portfolio["plans"] if p["uncertainty_id"]=="UNC-EXTERNAL-PRJ-005")
    abvm=next(p for p in portfolio["plans"] if p["uncertainty_id"]=="UNC-EXTERNAL-PRJ-006")
    req("CONSEQUENTIAL_CHILD_FACING_CHANGE" in star["approval_requirements"] and "CONSEQUENTIAL_CHILD_FACING_CHANGE" in abvm["approval_requirements"],"child-facing approval not inherited")
    trading=next(p for p in portfolio["plans"] if p["uncertainty_id"]=="UNC-CAPABILITY-PRJ-007")
    req({"NO_AUTONOMOUS_TRADING","NO_BROKER_ORDER_EXECUTION"}<=set(trading["inherited_hard_boundaries"]),"trading hard boundary lost")
    req(trading["execution_mode"]=="READ_ONLY_EVIDENCE_ACQUISITION","trading research plan gained execution authority")
    req(outcomes["outcomes"]==[],"Step 12 outcome ledger must start empty")
    runtime=(ROOT/"runtime/continuous_runtime.py").read_text()
    req("experiment_plan.json" in runtime and "build_experiment_portfolio" in runtime,"daily runtime not connected to experiment planner")
    return {"plans":portfolio["plan_count"],"ready_isolated":12,"ready_bounded":4,"human_approval_required":2,"blocked":2,"outcomes":0,"selected_uncertainty":"UNC-EXTERNAL-PRJ-001"}

if __name__=="__main__":print("portfolio-brain Step 12 experiments: PASS",json.dumps(validate_experiments(),sort_keys=True))
