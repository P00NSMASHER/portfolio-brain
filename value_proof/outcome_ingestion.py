#!/usr/bin/env python3
"""Single recurring ingestion path for verified technical value outcomes.

This module is an orchestrator only. It deliberately reuses the existing Hunter
feedback, model-feedback, and live-learning engines rather than creating another
ledger or learning implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from hunting.autonomous_hunter import (
    load_seed_state as load_hunter_seed_state,
    validate_state as validate_hunter_state,
)
from learning.live_observations import (
    apply_verified_value_outcome,
    load_seed_state as load_learning_seed_state,
    validate_state as validate_learning_state,
)
from model_router.feedback_state import (
    load_seed_state as load_model_feedback_seed_state,
    validate_state as validate_model_feedback_state,
)
from value_proof.feedback_loop import apply_verified_value_feedback, validate_value_outcome
from value_proof.model_task import digest, load_contract
from value_proof.verifier import load_verifier_contract

ROOT=Path(__file__).resolve().parents[1]


class OutcomeIngestionError(ValueError):
    pass


def req(ok:bool,msg:str)->None:
    if not ok:
        raise OutcomeIngestionError(msg)


def canon(v:Any)->str:
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)


def _copy(v:Any)->Any:
    return json.loads(json.dumps(v))


def _load_or_seed(path:Path|None,loader)->dict[str,Any]:
    if path is not None and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return loader()


def _identity_key(outcome:dict[str,Any])->str:
    return "verified-outcome:"+outcome["outcome_id"]


def _ingestion_id(outcome:dict[str,Any])->str:
    return "VOI-"+hashlib.sha256(_identity_key(outcome).encode("utf-8")).hexdigest()[:24].upper()


def _assert_no_conflicting_identity(
    *,
    outcome:dict[str,Any],
    learning_state:dict[str,Any],
    model_feedback_state:dict[str,Any],
)->None:
    """Reject reuse of an outcome_id for a different immutable payload."""
    expected_hash=outcome["outcome_hash"]
    prefix=f"value-outcome:{outcome['outcome_id']}:"
    prior_learning_hashes={
        key[len(prefix):]
        for key in learning_state["applied_source_keys"]
        if isinstance(key,str) and key.startswith(prefix)
    }
    req(
        not prior_learning_hashes or prior_learning_hashes=={expected_hash},
        "verified outcome identity conflicts with prior live-learning ingestion",
    )

    prior_model_hashes=set()
    for row in model_feedback_state["outcomes"]:
        if row.get("outcome_event_id")!=outcome["outcome_id"]:
            continue
        matches=[
            ref.split("value-outcome:",1)[1]
            for ref in row.get("provenance_refs",[])
            if isinstance(ref,str) and ref.startswith("value-outcome:")
        ]
        req(matches,"prior model feedback for outcome is missing immutable value-outcome provenance")
        prior_model_hashes.update(matches)
    req(
        not prior_model_hashes or prior_model_hashes=={expected_hash},
        "verified outcome identity conflicts with prior model-feedback ingestion",
    )


def ingest_verified_outcome(
    *,
    task_contract:dict[str,Any],
    verifier_contract:dict[str,Any],
    outcome:dict[str,Any],
    builder_provider_receipt:dict[str,Any],
    verifier_provider_receipt:dict[str,Any],
    hunter_state:dict[str,Any],
    model_feedback_state:dict[str,Any],
    learning_state:dict[str,Any],
    controlled_cases:dict[str,Any],
    at:str|None=None,
)->tuple[dict[str,Any],dict[str,Any],dict[str,Any],dict[str,Any]]:
    """Validate then transactionally project one immutable verified outcome."""
    # Validation must happen before any idempotency shortcut. A malformed replay
    # never becomes acceptable merely because a similarly named outcome ran before.
    validate_value_outcome(outcome)
    validate_hunter_state(hunter_state)
    validate_model_feedback_state(model_feedback_state)
    validate_learning_state(learning_state)
    _assert_no_conflicting_identity(
        outcome=outcome,
        learning_state=learning_state,
        model_feedback_state=model_feedback_state,
    )

    hunter=_copy(hunter_state)
    model=_copy(model_feedback_state)
    learning=_copy(learning_state)

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

    projection_applied={
        "hunter_feedback":bool(feedback["hunter_feedback_applied"]),
        "builder_model_feedback":bool(feedback["builder_feedback_applied"]),
        "verifier_model_feedback":bool(feedback["verifier_feedback_applied"]),
        "live_learning":learning_result["status"]=="APPLIED",
    }
    any_applied=any(projection_applied.values())
    status="INGESTED" if any_applied else "ALREADY_INGESTED"
    core={
        "schema_version":"1.0.0",
        "ingestion_id":_ingestion_id(outcome),
        "ingestion_path_id":"portfolio-verified-outcome-ingestion-v1",
        "status":status,
        "source_identity_key":_identity_key(outcome),
        "source_outcome_id":outcome["outcome_id"],
        "source_outcome_hash":outcome["outcome_hash"],
        "source_value_class":outcome["value_class"],
        "projection_applied":projection_applied,
        "hunter_state_sequence":hunter["sequence"],
        "model_feedback_state_sequence":model["sequence"],
        "learning_state_sequence":learning["sequence"],
        "learning_added_observations":learning_result["added_observations"],
        "value_verification":{
            "technical":"VERIFIED",
            "market":"NOT_VERIFIED",
            "revenue":"NOT_VERIFIED",
        },
        "provenance_refs":list(dict.fromkeys([
            "value-outcome:"+outcome["outcome_hash"],
            "hunter-finding:"+outcome["hunter_finding_id"],
            "task:"+outcome["task_id"],
            "builder-provider-receipt:"+outcome["builder_provider_receipt_hash"],
            "verifier-provider-receipt:"+outcome["verifier_provider_receipt_hash"],
            "feedback-receipt:"+feedback["receipt_hash"],
        ])),
        "authority_granted":False,
        "market_value_claimed":False,
        "revenue_value_claimed":False,
    }
    receipt={**core,"ingestion_hash":digest(core)}
    return hunter,model,learning,receipt


def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--task-contract",type=Path,default=Path("value_proof/MODEL_TASK_CONTRACT.json"))
    ap.add_argument("--verifier-contract",type=Path,default=Path("value_proof/VERIFIER_CONTRACT.json"))
    ap.add_argument("--value-outcome",type=Path,required=True)
    ap.add_argument("--builder-provider-receipt",type=Path,required=True)
    ap.add_argument("--verifier-provider-receipt",type=Path,required=True)
    ap.add_argument("--hunter-state",type=Path,required=True)
    ap.add_argument("--model-feedback-state",type=Path,required=True)
    ap.add_argument("--learning-state",type=Path,required=True)
    ap.add_argument("--controlled-cases",type=Path,default=Path("hunting/CONTROLLED_PROOF_CASES.json"))
    ap.add_argument("--output-dir",type=Path,required=True)
    ap.add_argument("--at",default=None)
    args=ap.parse_args()

    hunter=_load_or_seed(args.hunter_state,load_hunter_seed_state)
    model=_load_or_seed(args.model_feedback_state,load_model_feedback_seed_state)
    learning=_load_or_seed(args.learning_state,load_learning_seed_state)
    outcome=json.loads(args.value_outcome.read_text(encoding="utf-8"))
    builder=json.loads(args.builder_provider_receipt.read_text(encoding="utf-8"))
    verifier=json.loads(args.verifier_provider_receipt.read_text(encoding="utf-8"))
    controlled=json.loads(args.controlled_cases.read_text(encoding="utf-8"))

    hunter,model,learning,receipt=ingest_verified_outcome(
        task_contract=load_contract(args.task_contract),
        verifier_contract=load_verifier_contract(args.verifier_contract),
        outcome=outcome,
        builder_provider_receipt=builder,
        verifier_provider_receipt=verifier,
        hunter_state=hunter,
        model_feedback_state=model,
        learning_state=learning,
        controlled_cases=controlled,
        at=args.at,
    )
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/"hunter_state.json").write_text(json.dumps(hunter,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    (args.output_dir/"model_feedback_state.json").write_text(json.dumps(model,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    (args.output_dir/"learning_observation_state.json").write_text(json.dumps(learning,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    (args.output_dir/"outcome_ingestion_receipt.json").write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(receipt,sort_keys=True))


if __name__=="__main__":
    main()
