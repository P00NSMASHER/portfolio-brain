#!/usr/bin/env python3
"""Step 8: feed one VERIFIED value outcome back into Hunter and model routing."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from hunting.autonomous_hunter import apply_verified_feedback, validate_state as validate_hunter_state
from model_router.feedback_state import (
    apply_verified_model_feedback,
    rebuild_summaries,
    stable_feedback_key,
    validate_state as validate_model_feedback_state,
)
from model_router.model_router import validate_call_receipt
from value_proof.model_task import digest, load_contract
from value_proof.verifier import load_verifier_contract

ROOT=Path(__file__).resolve().parents[1]
CONTROLLED_CASES=ROOT/"hunting"/"CONTROLLED_PROOF_CASES.json"

class FeedbackLoopError(ValueError):
    pass

def req(ok:bool,msg:str)->None:
    if not ok:
        raise FeedbackLoopError(msg)

def _load(path:Path)->dict[str,Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def validate_value_outcome(outcome:dict[str,Any])->None:
    required={
      "schema_version","outcome_id","task_id","project_ids","hunter_finding_id",
      "hunter_experiment_proposal_id","repository_full_name","revision","evidence_pack_hash",
      "builder_execution_receipt_hash","builder_provider_receipt_hash","builder_model_id",
      "deterministic_verification_receipt_hash","independent_verification_receipt_hash",
      "verifier_provider_receipt_hash","verifier_model_id","value_status","value_class",
      "decision","decision_basis","evidence_state","useful_outcome",
      "external_customer_value_claimed","rights_state","capability_verification_claimed",
      "deployment_authorized","authority_granted","evidence_upgraded","provenance_refs",
      "outcome_hash"
    }
    req(isinstance(outcome,dict) and set(outcome)==required,"value outcome fields changed")
    req(outcome["schema_version"]=="1.0.0","value outcome schema mismatch")
    req(outcome["value_status"]=="VALUE_OUTCOME_VERIFIED","feedback requires verified value outcome")
    req(outcome["evidence_state"]=="VERIFIED","feedback requires VERIFIED evidence")
    req(outcome["useful_outcome"] is True,"feedback requires useful outcome")
    req(outcome["value_class"]=="TECHNICAL_RESEARCH_DECISION_UTILITY","unexpected value class")
    req(outcome["external_customer_value_claimed"] is False,"technical proof may not claim customer value")
    req(outcome["rights_state"]=="UNKNOWN_REQUIRES_REVIEW","rights state improperly upgraded")
    req(outcome["capability_verification_claimed"] is False,"capability verification improperly claimed")
    req(outcome["deployment_authorized"] is False,"deployment authority improperly granted")
    req(outcome["authority_granted"] is False and outcome["evidence_upgraded"] is False,"feedback source widened authority/evidence")
    req(outcome["provenance_refs"],"value outcome provenance missing")
    body=dict(outcome);given=body.pop("outcome_hash")
    req(given==digest(body),"value outcome hash mismatch")

def _resolve_strategy(task_contract:dict[str,Any],cases:dict[str,Any])->str:
    source=task_contract["source_candidate"]
    matches=[]
    for case in cases["cases"]:
        expected_finding="HFD-CONTROLLED-"+case["case_id"]
        if (
          expected_finding==source["finding_id"]
          and case["repository_full_name"]==source["repository_full_name"]
          and set(case["project_ids"])==set(task_contract["project_ids"])
        ):
            matches.append(case)
    req(len(matches)==1,"unable to resolve unique Hunter strategy lineage")
    return matches[0]["strategy_id"]

def _hunter_feedback_id(*,outcome_id:str)->str:
    return "HFB-"+hashlib.sha256(outcome_id.encode()).hexdigest()[:24].upper()

def _legacy_hunter_feedback_id(*,task_id:str,finding_id:str)->str:
    seed=json.dumps({"task_id":task_id,"finding_id":finding_id,"value_class":"TECHNICAL"},sort_keys=True,separators=(",",":"))
    return "HFB-"+hashlib.sha256(seed.encode()).hexdigest()[:24].upper()

def apply_verified_value_feedback(
    *,
    task_contract:dict[str,Any],
    verifier_contract:dict[str,Any],
    outcome:dict[str,Any],
    builder_provider_receipt:dict[str,Any],
    verifier_provider_receipt:dict[str,Any],
    hunter_state:dict[str,Any],
    model_feedback_state:dict[str,Any],
    controlled_cases:dict[str,Any],
    at:str|None=None,
)->dict[str,Any]:
    validate_value_outcome(outcome)
    validate_call_receipt(builder_provider_receipt)
    validate_call_receipt(verifier_provider_receipt)
    validate_hunter_state(hunter_state)
    rebuild_summaries(model_feedback_state);validate_model_feedback_state(model_feedback_state)

    source=task_contract["source_candidate"]
    req(outcome["task_id"]==task_contract["task_id"],"outcome task mismatch")
    req(outcome["hunter_finding_id"]==source["finding_id"],"outcome Hunter finding mismatch")
    req(outcome["hunter_experiment_proposal_id"]==source["experiment_proposal_id"],"outcome Hunter proposal mismatch")
    req(outcome["repository_full_name"]==source["repository_full_name"],"outcome repository mismatch")
    req(outcome["revision"]==source["revision"],"outcome revision mismatch")
    req(outcome["builder_provider_receipt_hash"]==builder_provider_receipt["receipt_hash"],"builder receipt lineage mismatch")
    req(outcome["verifier_provider_receipt_hash"]==verifier_provider_receipt["receipt_hash"],"verifier receipt lineage mismatch")
    req(outcome["builder_model_id"]==builder_provider_receipt["model_id"],"builder model lineage mismatch")
    req(outcome["verifier_model_id"]==verifier_provider_receipt["model_id"],"verifier model lineage mismatch")
    req(builder_provider_receipt["tier"]==task_contract["model_contract"]["expected_tier"],"builder tier mismatch")
    req(verifier_provider_receipt["tier"]==verifier_contract["model_contract"]["expected_tier"],"verifier tier mismatch")
    req(builder_provider_receipt["independence_group"]!=verifier_provider_receipt["independence_group"],"builder/verifier independence collapsed")

    strategy_id=_resolve_strategy(task_contract,controlled_cases)
    req(strategy_id in hunter_state["strategy_stats"],"resolved Hunter strategy missing from state")

    hfb_id=_hunter_feedback_id(outcome_id=outcome["outcome_id"])
    legacy_id=_legacy_hunter_feedback_id(task_id=task_contract["task_id"],finding_id=source["finding_id"])
    hunter_applied=False
    if legacy_id in hunter_state["feedback_ids"]:
        hfb_id=legacy_id
    elif hfb_id not in hunter_state["feedback_ids"]:
        apply_verified_feedback(hunter_state,{
          "feedback_id":hfb_id,
          "strategy_id":strategy_id,
          "finding_id":source["finding_id"],
          "outcome_event_id":outcome["outcome_id"],
          "evidence_state":"VERIFIED",
          "value_realized":True,
        },task_contract=task_contract,outcome=outcome)
        hunter_state["sequence"]+=1
        hunter_state["updated_at"]=at or verifier_provider_receipt["completed_at"]
        hunter_applied=True

    common_provenance=[
      "value-outcome:"+outcome["outcome_hash"],
      "hunter-finding:"+source["finding_id"],
      "hunter-strategy:"+strategy_id,
      "task:"+task_contract["task_id"],
    ]
    builder_key=stable_feedback_key(
      task_id=task_contract["task_id"],role="BUILDER",
      hunter_finding_id=source["finding_id"],value_class="TECHNICAL"
    )
    verifier_key=stable_feedback_key(
      task_id=task_contract["task_id"],role="VERIFIER",
      hunter_finding_id=source["finding_id"],value_class="TECHNICAL"
    )
    builder_applied=apply_verified_model_feedback(
      model_feedback_state,
      feedback_key=builder_key,
      task_id=task_contract["task_id"],
      task_kind=task_contract["model_contract"]["task_kind"],
      role="BUILDER",
      hunter_finding_id=source["finding_id"],
      call_receipt=builder_provider_receipt,
      outcome_event_id=outcome["outcome_id"],
      outcome_value=1.0,
      provenance_refs=[
        *common_provenance,
        "provider-receipt:"+builder_provider_receipt["receipt_hash"],
        "role:BUILDER",
      ],
      at=at or verifier_provider_receipt["completed_at"],
    )
    verifier_applied=apply_verified_model_feedback(
      model_feedback_state,
      feedback_key=verifier_key,
      task_id=task_contract["task_id"],
      task_kind=verifier_contract["model_contract"]["task_kind"],
      role="VERIFIER",
      hunter_finding_id=source["finding_id"],
      call_receipt=verifier_provider_receipt,
      outcome_event_id=outcome["outcome_id"],
      outcome_value=1.0,
      provenance_refs=[
        *common_provenance,
        "provider-receipt:"+verifier_provider_receipt["receipt_hash"],
        "role:VERIFIER",
      ],
      at=at or verifier_provider_receipt["completed_at"],
    )
    rebuild_summaries(model_feedback_state);validate_model_feedback_state(model_feedback_state)
    validate_hunter_state(hunter_state)

    applied=any((hunter_applied,builder_applied,verifier_applied))
    core={
      "schema_version":"1.0.0",
      "feedback_loop_id":"portfolio-verified-value-feedback-v1",
      "status":"FEEDBACK_APPLIED" if applied else "ALREADY_APPLIED",
      "source_outcome_id":outcome["outcome_id"],
      "source_outcome_hash":outcome["outcome_hash"],
      "hunter_finding_id":source["finding_id"],
      "hunter_strategy_id":strategy_id,
      "hunter_feedback_id":hfb_id,
      "hunter_feedback_applied":hunter_applied,
      "hunter_verified_value_outcomes":hunter_state["strategy_stats"][strategy_id]["verified_value_outcomes"],
      "builder_feedback_key":builder_key,
      "builder_feedback_applied":builder_applied,
      "verifier_feedback_key":verifier_key,
      "verifier_feedback_applied":verifier_applied,
      "model_feedback_sequence":model_feedback_state["sequence"],
      "routing_value_summary":model_feedback_state["routing_value_summary"],
      "routing_task_summaries":model_feedback_state["routing_task_summaries"],
      "authority_granted":False,
      "evidence_upgraded":False,
      "customer_value_claimed":False,
    }
    return {**core,"receipt_hash":digest(core)}

def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--task-contract",type=Path,default=Path("value_proof/MODEL_TASK_CONTRACT.json"))
    ap.add_argument("--verifier-contract",type=Path,default=Path("value_proof/VERIFIER_CONTRACT.json"))
    ap.add_argument("--value-outcome",type=Path,required=True)
    ap.add_argument("--builder-provider-receipt",type=Path,required=True)
    ap.add_argument("--verifier-provider-receipt",type=Path,required=True)
    ap.add_argument("--hunter-state",type=Path,required=True)
    ap.add_argument("--model-feedback-state",type=Path,required=True)
    ap.add_argument("--output-dir",type=Path,required=True)
    args=ap.parse_args()

    task_contract=load_contract(args.task_contract)
    verifier_contract=load_verifier_contract(args.verifier_contract)
    hunter_state=_load(args.hunter_state)
    model_state=_load(args.model_feedback_state)
    report=apply_verified_value_feedback(
      task_contract=task_contract,
      verifier_contract=verifier_contract,
      outcome=_load(args.value_outcome),
      builder_provider_receipt=_load(args.builder_provider_receipt),
      verifier_provider_receipt=_load(args.verifier_provider_receipt),
      hunter_state=hunter_state,
      model_feedback_state=model_state,
      controlled_cases=_load(CONTROLLED_CASES),
    )
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/"hunter_state.json").write_text(json.dumps(hunter_state,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    (args.output_dir/"model_feedback_state.json").write_text(json.dumps(model_state,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    (args.output_dir/"feedback_loop_receipt.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({
      "status":report["status"],
      "hunter_strategy":report["hunter_strategy_id"],
      "hunter_verified_value_outcomes":report["hunter_verified_value_outcomes"],
      "model_feedback_sequence":report["model_feedback_sequence"],
      "receipt_hash":report["receipt_hash"],
    },sort_keys=True))

if __name__=="__main__":
    main()
