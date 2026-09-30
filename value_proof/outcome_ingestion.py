#!/usr/bin/env python3
"""Atomic idempotent routing for one VERIFIED Portfolio Brain outcome.

This is intentionally an orchestration layer over the existing Hunter, model-feedback,
and continuous-learning engines. It owns no learning algorithm or duplicate ledger.
All destination states are mutated on deep copies and are returned only after every
projection validates, so malformed/conflicting input cannot partially mutate callers.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from hunting.autonomous_hunter import validate_state as validate_hunter_state
from learning.integrity import build_learning_integrity
from learning.live_observations import (
    apply_verified_value_outcome,
    validate_state as validate_learning_state,
)
from model_router.feedback_state import validate_state as validate_model_feedback_state
from value_proof.feedback_loop import apply_verified_value_feedback, validate_value_outcome
from value_proof.model_task import digest, load_contract
from value_proof.verifier import load_verifier_contract

class OutcomeIngestionError(ValueError):
    pass

def req(ok: bool, msg: str) -> None:
    if not ok:
        raise OutcomeIngestionError(msg)

def _known_outcome_hashes(learning_state: dict[str, Any], outcome_id: str) -> set[str]:
    prefix=f"value-outcome:{outcome_id}:"
    hashes=set()
    for key in learning_state["applied_source_keys"]:
        if isinstance(key,str) and key.startswith(prefix):
            hashes.add(key[len(prefix):])
    return hashes

def _hunter_feedback_ids(task_contract: dict[str, Any], outcome: dict[str, Any]) -> set[str]:
    source=task_contract["source_candidate"]
    current="HFB-"+hashlib.sha256(outcome["outcome_id"].encode()).hexdigest()[:24].upper()
    legacy_seed=json.dumps(
        {"task_id":task_contract["task_id"],"finding_id":source["finding_id"],"value_class":"TECHNICAL"},
        sort_keys=True,separators=(",",":"),
    )
    legacy="HFB-"+hashlib.sha256(legacy_seed.encode()).hexdigest()[:24].upper()
    return {current,legacy}

def _reject_conflicting_identity(
    hunter_state: dict[str, Any],
    learning_state: dict[str, Any],
    model_feedback_state: dict[str, Any],
    task_contract: dict[str, Any],
    outcome: dict[str, Any],
) -> None:
    known=_known_outcome_hashes(learning_state,outcome["outcome_id"])
    model_hashes=set()
    for row in model_feedback_state["outcomes"]:
        if row.get("outcome_event_id")!=outcome["outcome_id"]:
            continue
        for ref in row.get("provenance_refs",[]):
            if isinstance(ref,str) and ref.startswith("value-outcome:sha256:"):
                model_hashes.add(ref[len("value-outcome:"):])
    combined=known | model_hashes
    if combined and combined != {outcome["outcome_hash"]}:
        raise OutcomeIngestionError("conflicting verified outcome identity")

    # Hunter's legacy state stores only feedback IDs, not the source outcome hash.
    # If Hunter alone remembers this identity, we cannot prove whether a replay is
    # the same outcome or a conflicting one. Fail closed rather than silently
    # filling the other projections from an unverifiable partial state.
    hunter_feedback_ids=set(hunter_state["feedback_ids"])
    if _hunter_feedback_ids(task_contract,outcome) & hunter_feedback_ids and not combined:
        raise OutcomeIngestionError(
            "ambiguous prior Hunter feedback identity without outcome hash"
        )

def ingest_verified_outcome(
    *,
    task_contract: dict[str, Any],
    verifier_contract: dict[str, Any],
    outcome: dict[str, Any],
    builder_provider_receipt: dict[str, Any],
    verifier_provider_receipt: dict[str, Any],
    hunter_state: dict[str, Any],
    model_feedback_state: dict[str, Any],
    learning_state: dict[str, Any],
    controlled_cases: dict[str, Any],
    at: str | None=None,
) -> tuple[dict[str, Any],dict[str, Any],dict[str, Any],dict[str,Any]]:
    """Route exactly one verified outcome through existing engines.

    No caller-owned state is mutated unless the caller replaces it with the returned
    validated copies. The durable learning source key is the canonical conflict and
    idempotency registry for an outcome identity/hash pair.
    """
    validate_value_outcome(outcome)
    validate_hunter_state(hunter_state)
    validate_model_feedback_state(model_feedback_state)
    validate_learning_state(learning_state)
    _reject_conflicting_identity(
        hunter_state,learning_state,model_feedback_state,task_contract,outcome
    )

    hunter=copy.deepcopy(hunter_state)
    model=copy.deepcopy(model_feedback_state)
    learning=copy.deepcopy(learning_state)
    before={
      "hunter_sequence":hunter["sequence"],
      "model_feedback_sequence":model["sequence"],
      "learning_sequence":learning["sequence"],
    }
    feedback=apply_verified_value_feedback(
      task_contract=task_contract,
      verifier_contract=verifier_contract,
      outcome=outcome,
      builder_provider_receipt=builder_provider_receipt,
      verifier_provider_receipt=verifier_provider_receipt,
      hunter_state=hunter,
      model_feedback_state=model,
      controlled_cases=controlled_cases,
      at=at,
    )
    learning_result=apply_verified_value_outcome(
      learning,
      task_contract=task_contract,
      verifier_contract=verifier_contract,
      outcome=outcome,
      feedback_receipt=feedback,
      builder_provider_receipt=builder_provider_receipt,
      verifier_provider_receipt=verifier_provider_receipt,
      at=at,
    )
    validate_hunter_state(hunter)
    validate_model_feedback_state(model)
    validate_learning_state(learning)
    integrity=build_learning_integrity(hunter,model,learning)
    req(integrity["status"]=="HEALTHY","verified outcome projections failed integrity")

    changed=(
      hunter["sequence"]!=before["hunter_sequence"] or
      model["sequence"]!=before["model_feedback_sequence"] or
      learning["sequence"]!=before["learning_sequence"]
    )
    fully_new=(
      feedback["status"]=="FEEDBACK_APPLIED" and
      learning_result["status"]=="APPLIED"
    )
    if not changed:
        status="ALREADY_INGESTED"
    elif fully_new:
        status="INGESTED"
    else:
        status="RECONCILED"
    core={
      "schema_version":"1.0.0",
      "ingestion_id":"portfolio-verified-outcome-ingestion-v1",
      "status":status,
      "source_outcome_id":outcome["outcome_id"],
      "source_outcome_hash":outcome["outcome_hash"],
      "source_value_class":outcome["value_class"],
      "verification_scope":"TECHNICAL_RESEARCH_DECISION_UTILITY",
      "learning_projection_status":learning_result["status"],
      "feedback_projection_status":feedback["status"],
      "hunter_sequence":hunter["sequence"],
      "model_feedback_sequence":model["sequence"],
      "learning_sequence":learning["sequence"],
      "integrity_status":integrity["status"],
      "market_verified":False,
      "revenue_verified":False,
      "authority_granted":False,
      "evidence_upgraded":False,
    }
    report={**core,"ingestion_hash":digest(core),"integrity":integrity}
    return hunter,model,learning,report

def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--task-contract",type=Path,default=Path("value_proof/MODEL_TASK_CONTRACT.json"))
    ap.add_argument("--verifier-contract",type=Path,default=Path("value_proof/VERIFIER_CONTRACT.json"))
    ap.add_argument("--controlled-cases",type=Path,default=Path("hunting/CONTROLLED_PROOF_CASES.json"))
    ap.add_argument("--value-outcome",type=Path,required=True)
    ap.add_argument("--builder-provider-receipt",type=Path,required=True)
    ap.add_argument("--verifier-provider-receipt",type=Path,required=True)
    ap.add_argument("--hunter-state",type=Path,required=True)
    ap.add_argument("--model-feedback-state",type=Path,required=True)
    ap.add_argument("--learning-state",type=Path,required=True)
    ap.add_argument("--output-dir",type=Path,required=True)
    args=ap.parse_args()
    load=lambda p:json.loads(p.read_text(encoding="utf-8"))
    hunter,model,learning,report=ingest_verified_outcome(
      task_contract=load_contract(args.task_contract),
      verifier_contract=load_verifier_contract(args.verifier_contract),
      outcome=load(args.value_outcome),
      builder_provider_receipt=load(args.builder_provider_receipt),
      verifier_provider_receipt=load(args.verifier_provider_receipt),
      hunter_state=load(args.hunter_state),
      model_feedback_state=load(args.model_feedback_state),
      learning_state=load(args.learning_state),
      controlled_cases=load(args.controlled_cases),
    )
    args.output_dir.mkdir(parents=True,exist_ok=True)
    # Write only after every projection and cross-subsystem integrity check succeeds.
    for name,value in (
      ("hunter_state.json",hunter),
      ("model_feedback_state.json",model),
      ("learning_observation_state.json",learning),
      ("outcome_ingestion_receipt.json",report),
    ):
        (args.output_dir/name).write_text(json.dumps(value,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({k:report[k] for k in (
      "status","source_outcome_id","source_outcome_hash","integrity_status",
      "market_verified","revenue_verified","authority_granted"
    )},sort_keys=True))

if __name__=="__main__":
    main()
