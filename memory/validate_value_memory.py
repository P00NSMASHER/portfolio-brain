#!/usr/bin/env python3
"""Cross-file validator for Step 6 shared value memory."""
from __future__ import annotations
import json
from pathlib import Path
from memory.value_memory_adapter import (
    load_pin, validate_pin, validate_memory, validate_outcome, validate_credit_conservation
)

ROOT=Path(__file__).resolve().parents[1]

class SharedMemoryConformanceError(ValueError): pass

def require(ok: bool,msg: str)->None:
    if not ok: raise SharedMemoryConformanceError(msg)

def load(path: str):
    return json.loads((ROOT/path).read_text(encoding="utf-8"))

def validate_shared_value_memory()->dict[str,object]:
    pin=load_pin(); validate_pin(pin)
    state=load("PORTFOLIO_BUILD_STATE.json")
    conf=load("memory/VALUE_MEMORY_CONFORMANCE.json")
    ledger=load("memory/SHARED_VALUE_MEMORY_LEDGER.json")
    mem_schema=load("schemas/VALUE_MEMORY_SCHEMA.json")
    out_schema=load("schemas/VALUE_MEMORY_OUTCOME_SCHEMA.json")

    require(state["repositories"]["REPO-001"]["last_inspected_sha"]==pin["source_revision"],
            "Value Memory source cursor drifted; reconformance required")
    require(mem_schema["additionalProperties"] is False,"memory schema must be closed")
    require(out_schema["additionalProperties"] is False,"outcome schema must be closed")
    require(conf["schema_version"]=="1.0.0","conformance schema mismatch")
    source=conf["source"]
    require(source["repository"]==pin["source_repository"],"source repository mismatch")
    require(source["revision"]==pin["source_revision"],"source revision mismatch")
    require(source["blob_sha"]==pin["source_blob_sha"],"source blob mismatch")
    require(source["test_blob_sha"]==pin["source_test_blob_sha"],"source test blob mismatch")
    require(conf["authority_change"]=="NONE","memory integration cannot grant authority")

    semantics=conf["semantics"]
    require(semantics=={
      "independently_verified_outcomes_only":"REQUIRED",
      "observer_verifier_separation":"REQUIRED",
      "immutable_verification_decision":"REQUIRED",
      "per_event_credit_conservation":"MAX_1_TOTAL",
      "objective_conditioning":"REQUIRED",
      "untested_memory_prior":"NEUTRAL",
      "recency_decay":"HALF_LIFE",
      "duplicate_event_per_memory":"REJECT",
    },"canonical Value Memory semantics changed")

    require(ledger["schema_version"]=="1.0.0","ledger schema mismatch")
    require(ledger["ledger_id"]=="portfolio-shared-value-memory","ledger identity mismatch")
    memories=ledger["memories"]; outcomes=ledger["outcomes"]
    require(isinstance(memories,list) and isinstance(outcomes,list),"ledger collections must be lists")
    memory_ids=set()
    for record in memories:
        validate_memory(record)
        require(record["memory_id"] not in memory_ids,"duplicate memory_id")
        memory_ids.add(record["memory_id"])
    outcome_ids=set()
    for outcome in outcomes:
        validate_outcome(outcome)
        require(outcome["outcome_id"] not in outcome_ids,"duplicate outcome_id")
        require(outcome["memory_id"] in memory_ids,"outcome references missing memory")
        outcome_ids.add(outcome["outcome_id"])
    validate_credit_conservation(outcomes)

    return {
      "memories":len(memories),
      "outcomes":len(outcomes),
      "source_revision":pin["source_revision"],
      "source_blob_sha":pin["source_blob_sha"],
      "verified_learning_only":True,
    }

if __name__=="__main__":
    print("portfolio-brain Step 6 shared memory: PASS",json.dumps(validate_shared_value_memory(),sort_keys=True))
