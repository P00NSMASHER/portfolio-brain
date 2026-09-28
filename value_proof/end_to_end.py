#!/usr/bin/env python3
"""Finalize one end-to-end Portfolio Brain model-value proof.

This module separates three states:
1) MODEL_CALL_SUCCESS (builder provider execution),
2) OUTPUT_VERIFIED (independent verifier),
3) VALUE_OUTCOME_VERIFIED (a bounded decision-useful technical research outcome).

The final state does not claim external customer value, reuse rights, capability
verification, deployment permission, or additional authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from model_router.model_router import validate_call_receipt
from value_proof.model_task import (
    digest,
    load_contract,
    parse_and_validate_output,
    validate_evidence_pack,
    validate_execution_receipt,
)
from value_proof.verifier import (
    deterministic_verify,
    load_verifier_contract,
    parse_verifier_output,
    validate_verification_receipt,
)

class EndToEndProofError(ValueError):
    pass

def req(ok:bool,msg:str)->None:
    if not ok:
        raise EndToEndProofError(msg)

def build_value_outcome(*,task_contract:dict[str,Any],verifier_contract:dict[str,Any],pack:dict[str,Any],builder_output:dict[str,Any],builder_execution_receipt:dict[str,Any],builder_provider_receipt:dict[str,Any],deterministic_receipt:dict[str,Any],verifier_output:dict[str,Any],verifier_receipt:dict[str,Any],verifier_provider_receipt:dict[str,Any])->dict[str,Any]:
    validate_evidence_pack(pack,task_contract)
    builder=parse_and_validate_output(json.dumps(builder_output,sort_keys=True),task_contract)
    validate_call_receipt(builder_provider_receipt)
    validate_execution_receipt(builder_execution_receipt,task_contract,pack,builder_provider_receipt,builder)
    rebuilt=deterministic_verify(
      task_contract=task_contract,
      verifier_contract=verifier_contract,
      pack=pack,
      builder_output=builder,
      execution_receipt=builder_execution_receipt,
      provider_receipt=builder_provider_receipt,
    )
    req(rebuilt["receipt_hash"]==deterministic_receipt["receipt_hash"],"deterministic verification receipt lineage drift")
    parsed_verifier=parse_verifier_output(json.dumps(verifier_output,sort_keys=True),verifier_contract)
    validate_call_receipt(verifier_provider_receipt)
    validate_verification_receipt(
      verifier_receipt,
      verifier_contract,
      task_contract,
      deterministic_receipt,
      verifier_provider_receipt,
      parsed_verifier,
    )
    req(verifier_receipt["status"]=="OUTPUT_VERIFIED","independent verifier did not verify builder output")
    req(parsed_verifier["verdict"]=="PASS","independent verifier verdict not PASS")
    req(parsed_verifier["useful_for_bounded_followup"] is True,"independent verifier did not find decision utility")
    decision=(
      "PROCEED_TO_BOUNDED_INTEGRATION_REVIEW"
      if builder["recommendation"]=="DEEPER_BOUNDED_REVIEW"
      else "STOP_CANDIDATE_REVIEW"
    )
    source=task_contract["source_candidate"]
    seed={
      "task_id":task_contract["task_id"],
      "builder_receipt_hash":builder_execution_receipt["receipt_hash"],
      "verification_receipt_hash":verifier_receipt["receipt_hash"],
      "evidence_pack_hash":pack["pack_hash"],
      "decision":decision,
    }
    outcome_id="MVOUT-"+hashlib.sha256(json.dumps(seed,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:20].upper()
    core={
      "schema_version":"1.0.0",
      "outcome_id":outcome_id,
      "task_id":task_contract["task_id"],
      "project_ids":task_contract["project_ids"],
      "hunter_finding_id":source["finding_id"],
      "hunter_experiment_proposal_id":source["experiment_proposal_id"],
      "repository_full_name":source["repository_full_name"],
      "revision":source["revision"],
      "evidence_pack_hash":pack["pack_hash"],
      "builder_execution_receipt_hash":builder_execution_receipt["receipt_hash"],
      "builder_provider_receipt_hash":builder_provider_receipt["receipt_hash"],
      "builder_model_id":builder_execution_receipt["model_id"],
      "deterministic_verification_receipt_hash":deterministic_receipt["receipt_hash"],
      "independent_verification_receipt_hash":verifier_receipt["receipt_hash"],
      "verifier_provider_receipt_hash":verifier_provider_receipt["receipt_hash"],
      "verifier_model_id":verifier_receipt["verifier_model_id"],
      "value_status":"VALUE_OUTCOME_VERIFIED",
      "value_class":"TECHNICAL_RESEARCH_DECISION_UTILITY",
      "decision":decision,
      "decision_basis":{
        "builder_recommendation":builder["recommendation"],
        "builder_confidence":builder["confidence"],
        "verifier_confidence":parsed_verifier["confidence"],
        "evidence_supported":parsed_verifier["evidence_supported"],
        "contract_compliant":parsed_verifier["contract_compliant"],
        "useful_for_bounded_followup":parsed_verifier["useful_for_bounded_followup"],
      },
      "evidence_state":"VERIFIED",
      "useful_outcome":True,
      "external_customer_value_claimed":False,
      "rights_state":"OPERATOR_ASSUMED",
      "capability_verification_claimed":False,
      "deployment_authorized":False,
      "authority_granted":False,
      "evidence_upgraded":False,
      "provenance_refs":[
        *task_contract["provenance_refs"],
        "builder-execution:"+builder_execution_receipt["receipt_hash"],
        "deterministic-verification:"+deterministic_receipt["receipt_hash"],
        "independent-verification:"+verifier_receipt["receipt_hash"],
        "evidence-pack:"+pack["pack_hash"],
      ],
    }
    return {**core,"outcome_hash":digest(core)}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--task-contract",type=Path,default=Path("value_proof/MODEL_TASK_CONTRACT.json"))
    ap.add_argument("--verifier-contract",type=Path,default=Path("value_proof/VERIFIER_CONTRACT.json"))
    ap.add_argument("--evidence-pack",type=Path,required=True)
    ap.add_argument("--builder-output",type=Path,required=True)
    ap.add_argument("--builder-execution-receipt",type=Path,required=True)
    ap.add_argument("--builder-provider-receipt",type=Path,required=True)
    ap.add_argument("--deterministic-receipt",type=Path,required=True)
    ap.add_argument("--verifier-output",type=Path,required=True)
    ap.add_argument("--verification-receipt",type=Path,required=True)
    ap.add_argument("--verifier-provider-receipt",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()

    task_contract=load_contract(args.task_contract)
    verifier_contract=load_verifier_contract(args.verifier_contract)
    def read(path): return json.loads(path.read_text(encoding="utf-8"))
    outcome=build_value_outcome(
      task_contract=task_contract,
      verifier_contract=verifier_contract,
      pack=read(args.evidence_pack),
      builder_output=read(args.builder_output),
      builder_execution_receipt=read(args.builder_execution_receipt),
      builder_provider_receipt=read(args.builder_provider_receipt),
      deterministic_receipt=read(args.deterministic_receipt),
      verifier_output=read(args.verifier_output),
      verifier_receipt=read(args.verification_receipt),
      verifier_provider_receipt=read(args.verifier_provider_receipt),
    )
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(outcome,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({
      "outcome_id":outcome["outcome_id"],
      "status":outcome["value_status"],
      "value_class":outcome["value_class"],
      "decision":outcome["decision"],
      "external_customer_value_claimed":outcome["external_customer_value_claimed"],
      "outcome_hash":outcome["outcome_hash"],
    },sort_keys=True))

if __name__=="__main__":
    main()
