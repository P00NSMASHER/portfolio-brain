#!/usr/bin/env python3
"""Durable live learning observations derived only from VERIFIED value outcomes.

Checked-in learning history remains empty. This state is populated at runtime from
validated evidence-bearing outcome receipts and is advisory-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hunting.autonomous_hunter import load_strategies
from learning.continuous_learning import validate_observation
from model_router.model_router import validate_call_receipt
from value_proof.feedback_loop import validate_value_outcome
from value_proof.model_task import digest, load_contract
from value_proof.verifier import load_verifier_contract

ROOT=Path(__file__).resolve().parents[1]
SEED=ROOT/"learning"/"LIVE_OBSERVATION_STATE_SEED.json"
ARTIFACT_NAME="portfolio-learning-observation-state"
STATE_ID="portfolio-learning-observation-state"

class LiveLearningError(ValueError):
    pass

def req(ok:bool,msg:str)->None:
    if not ok:
        raise LiveLearningError(msg)

def canon(v:Any)->str:
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)

def now_iso()->str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

def load_seed_state()->dict[str,Any]:
    return json.loads(SEED.read_text(encoding="utf-8"))

def validate_state(state:dict[str,Any])->None:
    required={"schema_version","state_id","sequence","updated_at","applied_source_keys","observations"}
    req(isinstance(state,dict) and set(state)==required,"live learning state fields changed")
    req(state["schema_version"]=="1.0.0" and state["state_id"]==STATE_ID,"live learning state identity mismatch")
    req(type(state["sequence"]) is int and state["sequence"]>=0,"live learning sequence invalid")
    req(state["updated_at"] is None or isinstance(state["updated_at"],str),"live learning updated_at invalid")
    req(isinstance(state["applied_source_keys"],list),"live learning source keys invalid")
    req(len(state["applied_source_keys"])==len(set(state["applied_source_keys"])),"duplicate live learning source key")
    req(isinstance(state["observations"],list),"live learning observations invalid")
    seen=set()
    for row in state["observations"]:
        validate_observation(row)
        req(row["observation_id"] not in seen,"duplicate live learning observation id")
        seen.add(row["observation_id"])

def _id(prefix:str,*parts:str)->str:
    raw="\0".join(parts)
    return prefix+hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20].upper()

def _feedback_receipt_ok(receipt:dict[str,Any],outcome:dict[str,Any])->None:
    req(isinstance(receipt,dict),"feedback receipt invalid")
    given=receipt.get("receipt_hash")
    req(isinstance(given,str) and given.startswith("sha256:"),"feedback receipt hash missing")
    body=dict(receipt);body.pop("receipt_hash",None)
    req(given==digest(body),"feedback receipt hash mismatch")
    req(receipt.get("source_outcome_id")==outcome["outcome_id"],"feedback receipt outcome id mismatch")
    req(receipt.get("source_outcome_hash")==outcome["outcome_hash"],"feedback receipt outcome hash mismatch")
    req(receipt.get("hunter_finding_id")==outcome["hunter_finding_id"],"feedback receipt Hunter finding mismatch")
    req(receipt.get("status") in {"FEEDBACK_APPLIED","ALREADY_APPLIED"},"feedback receipt status not admissible")
    req(receipt.get("authority_granted") is False and receipt.get("evidence_upgraded") is False,"feedback receipt widened authority/evidence")
    req(receipt.get("customer_value_claimed") is False,"technical feedback receipt claimed customer value")

def _resource_usage(call:dict[str,Any])->dict[str,Any]:
    return {
      "model_calls":1,
      "tokens":int(call["input_tokens"])+int(call["output_tokens"]),
      "cost_usd":float(call["cost_usd"]),
      "compute_seconds":round(float(call["latency_ms"])/1000.0,6),
      "tool_calls":1,
    }

def _zero_resource_usage()->dict[str,Any]:
    return {"model_calls":0,"tokens":0,"cost_usd":0.0,"compute_seconds":0.0,"tool_calls":0}

def make_verified_learning_observations(
    *,
    task_contract:dict[str,Any],
    verifier_contract:dict[str,Any],
    outcome:dict[str,Any],
    feedback_receipt:dict[str,Any],
    builder_provider_receipt:dict[str,Any],
    verifier_provider_receipt:dict[str,Any],
)->list[dict[str,Any]]:
    validate_value_outcome(outcome)
    validate_call_receipt(builder_provider_receipt)
    validate_call_receipt(verifier_provider_receipt)
    _feedback_receipt_ok(feedback_receipt,outcome)

    req(outcome["task_id"]==task_contract["task_id"],"learning outcome task mismatch")
    req(outcome["builder_provider_receipt_hash"]==builder_provider_receipt["receipt_hash"],"learning builder receipt lineage mismatch")
    req(outcome["verifier_provider_receipt_hash"]==verifier_provider_receipt["receipt_hash"],"learning verifier receipt lineage mismatch")
    req(builder_provider_receipt["tier"]==task_contract["model_contract"]["expected_tier"],"learning builder tier mismatch")
    req(verifier_provider_receipt["tier"]==verifier_contract["model_contract"]["expected_tier"],"learning verifier tier mismatch")
    req(builder_provider_receipt["independence_group"]!=verifier_provider_receipt["independence_group"],"learning verifier independence collapsed")

    strategy=feedback_receipt["hunter_strategy_id"]
    req(strategy in {x["strategy_id"] for x in load_strategies()},"learning Hunter strategy unknown")
    project_ids=list(outcome["project_ids"])
    observed_at=verifier_provider_receipt["completed_at"]
    event_id=_id("EVT-MV-",outcome["outcome_id"],outcome["outcome_hash"])
    common_refs=[
      "value-outcome:"+outcome["outcome_hash"],
      "feedback-loop:"+feedback_receipt["receipt_hash"],
      "hunter-finding:"+outcome["hunter_finding_id"],
    ]
    search={
      "schema_version":"1.0.0",
      "observation_id":_id("LRN-MV-SEARCH-",outcome["outcome_id"],strategy),
      "domain":"SEARCH",
      "learning_key":"hunter-strategy:"+strategy+":verified-decision-utility",
      "scope":"GLOBAL",
      "project_ids":project_ids,
      "objective_id":None,
      "phase":"TRAIN",
      "measurement_quality":"BENCHMARK",
      "signal_class":"VERIFIED_TECHNICAL",
      "evidence_state":"VERIFIED",
      "reward_signal":1.0,
      "sample_size":1,
      "measured_numerator":1,
      "measured_denominator":1,
      "source_event_ids":[event_id],
      "evidence_ids":[_id("EVD-MV-SEARCH-",outcome["outcome_hash"],strategy)],
      "resource_usage":_zero_resource_usage(),
      "observed_at":observed_at,
      "provenance_refs":[*common_refs,"hunter-strategy:"+strategy],
    }
    pipeline_key=(
      "model-pipeline:"+task_contract["model_contract"]["task_kind"]+
      "->"+verifier_contract["model_contract"]["task_kind"]
    )
    builder={
      "schema_version":"1.0.0",
      "observation_id":_id("LRN-MV-BUILDER-",outcome["outcome_id"],builder_provider_receipt["invocation_id"]),
      "domain":"MODEL",
      "learning_key":pipeline_key,
      "scope":"GLOBAL",
      "project_ids":project_ids,
      "objective_id":None,
      "phase":"TRAIN",
      "measurement_quality":"BENCHMARK",
      "signal_class":"VERIFIED_TECHNICAL",
      "evidence_state":"VERIFIED",
      "reward_signal":1.0,
      "sample_size":1,
      "measured_numerator":1,
      "measured_denominator":1,
      "source_event_ids":[event_id],
      "evidence_ids":[_id("EVD-MV-BUILDER-",builder_provider_receipt["receipt_hash"])],
      "resource_usage":_resource_usage(builder_provider_receipt),
      "observed_at":builder_provider_receipt["completed_at"],
      "provenance_refs":[
        *common_refs,
        "provider-receipt:"+builder_provider_receipt["receipt_hash"],
        "model-role:BUILDER",
      ],
    }
    verifier={
      "schema_version":"1.0.0",
      "observation_id":_id("LRN-MV-VERIFY-",outcome["outcome_id"],verifier_provider_receipt["invocation_id"]),
      "domain":"MODEL",
      "learning_key":pipeline_key,
      "scope":"GLOBAL",
      "project_ids":project_ids,
      "objective_id":None,
      "phase":"CONFIRM",
      "measurement_quality":"BENCHMARK",
      "signal_class":"VERIFIED_TECHNICAL",
      "evidence_state":"VERIFIED",
      "reward_signal":1.0,
      "sample_size":1,
      "measured_numerator":1,
      "measured_denominator":1,
      "source_event_ids":[event_id],
      "evidence_ids":[_id("EVD-MV-VERIFY-",verifier_provider_receipt["receipt_hash"])],
      "resource_usage":_resource_usage(verifier_provider_receipt),
      "observed_at":observed_at,
      "provenance_refs":[
        *common_refs,
        "provider-receipt:"+verifier_provider_receipt["receipt_hash"],
        "model-role:INDEPENDENT_VERIFIER",
      ],
    }
    rows=[search,builder,verifier]
    for row in rows:
        validate_observation(row)
    return rows

def apply_verified_value_outcome(
    state:dict[str,Any],
    *,
    task_contract:dict[str,Any],
    verifier_contract:dict[str,Any],
    outcome:dict[str,Any],
    feedback_receipt:dict[str,Any],
    builder_provider_receipt:dict[str,Any],
    verifier_provider_receipt:dict[str,Any],
    at:str|None=None,
)->dict[str,Any]:
    validate_state(state)
    # Validate the immutable source before checking idempotency. A malformed
    # replay must never be accepted merely because its claimed source key was
    # already processed.
    validate_value_outcome(outcome)
    source_key="value-outcome:"+outcome["outcome_id"]+":"+outcome["outcome_hash"]
    prior_prefix="value-outcome:"+outcome["outcome_id"]+":"
    prior_keys=[key for key in state["applied_source_keys"] if key.startswith(prior_prefix)]
    req(not prior_keys or prior_keys==[source_key],"conflicting live learning outcome identity")
    if source_key in state["applied_source_keys"]:
        return {"status":"ALREADY_APPLIED","source_key":source_key,"added_observations":0}
    rows=make_verified_learning_observations(
      task_contract=task_contract,
      verifier_contract=verifier_contract,
      outcome=outcome,
      feedback_receipt=feedback_receipt,
      builder_provider_receipt=builder_provider_receipt,
      verifier_provider_receipt=verifier_provider_receipt,
    )
    existing={x["observation_id"] for x in state["observations"]}
    req(not existing.intersection(x["observation_id"] for x in rows),"learning observation collision")
    state["observations"].extend(rows)
    state["applied_source_keys"].append(source_key)
    state["sequence"]+=1
    state["updated_at"]=at or verifier_provider_receipt["completed_at"] or now_iso()
    validate_state(state)
    return {"status":"APPLIED","source_key":source_key,"added_observations":len(rows)}

def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--state",type=Path,required=True)
    ap.add_argument("--task-contract",type=Path,default=Path("value_proof/MODEL_TASK_CONTRACT.json"))
    ap.add_argument("--verifier-contract",type=Path,default=Path("value_proof/VERIFIER_CONTRACT.json"))
    ap.add_argument("--value-outcome",type=Path,required=True)
    ap.add_argument("--feedback-receipt",type=Path,required=True)
    ap.add_argument("--builder-provider-receipt",type=Path,required=True)
    ap.add_argument("--verifier-provider-receipt",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    state=json.loads(args.state.read_text(encoding="utf-8")) if args.state.exists() else load_seed_state()
    result=apply_verified_value_outcome(
      state,
      task_contract=load_contract(args.task_contract),
      verifier_contract=load_verifier_contract(args.verifier_contract),
      outcome=json.loads(args.value_outcome.read_text(encoding="utf-8")),
      feedback_receipt=json.loads(args.feedback_receipt.read_text(encoding="utf-8")),
      builder_provider_receipt=json.loads(args.builder_provider_receipt.read_text(encoding="utf-8")),
      verifier_provider_receipt=json.loads(args.verifier_provider_receipt.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(state,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({
      **result,
      "state_sequence":state["sequence"],
      "observation_count":len(state["observations"]),
    },sort_keys=True))

if __name__=="__main__":
    main()
