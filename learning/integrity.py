#!/usr/bin/env python3
"""Cross-subsystem integrity projection for verified learning propagation.

This module proves whether one VERIFIED value event made it through all durable
learning layers. It is read-only and cannot grant authority or promote policy.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hunting.autonomous_hunter import validate_state as validate_hunter_state
from learning.live_observations import validate_state as validate_learning_state
from model_router.feedback_state import validate_state as validate_model_feedback_state

class LearningIntegrityError(ValueError):
    pass

def req(ok:bool,msg:str)->None:
    if not ok:
        raise LearningIntegrityError(msg)

def _learning_sources(state:dict[str,Any])->dict[str,str]:
    rows={}
    for key in state["applied_source_keys"]:
        if not isinstance(key,str) or not key.startswith("value-outcome:"):
            continue
        parts=key.split(":",2)
        if len(parts)==3 and parts[1] and parts[2].startswith("sha256:"):
            rows[parts[1]]=parts[2]
    return rows

def _learning_observation_counts_by_outcome_hash(state:dict[str,Any])->dict[str,int]:
    counts={}
    for observation in state["observations"]:
        for ref in observation["provenance_refs"]:
            if isinstance(ref,str) and ref.startswith("value-outcome:sha256:"):
                outcome_hash=ref[len("value-outcome:"):]
                counts[outcome_hash]=counts.get(outcome_hash,0)+1
    return counts

def build_learning_integrity(
    hunter_state:dict[str,Any],
    model_feedback_state:dict[str,Any],
    learning_state:dict[str,Any],
)->dict[str,Any]:
    validate_hunter_state(hunter_state)
    validate_model_feedback_state(model_feedback_state)
    validate_learning_state(learning_state)

    contexts={row["feedback_id"]:row for row in model_feedback_state["task_contexts"]}
    events={}
    for feedback in model_feedback_state["outcomes"]:
        if feedback["evidence_state"]!="VERIFIED":
            continue
        ctx=contexts.get(feedback["feedback_id"])
        req(ctx is not None,"verified model feedback missing task context")
        event_id=feedback["outcome_event_id"]
        bucket=events.setdefault(event_id,{
          "roles":set(),
          "feedback_ids":set(),
          "models":set(),
          "task_kinds":set(),
        })
        bucket["roles"].add(ctx["role"])
        bucket["feedback_ids"].add(feedback["feedback_id"])
        bucket["models"].add(f"T{ctx['tier']}::{ctx['provider_id']}::{ctx['model_id']}")
        bucket["task_kinds"].add(ctx["task_kind"])

    event_ids=set(events)
    learning_sources=_learning_sources(learning_state)
    learning_ids=set(learning_sources)
    learning_observation_counts=_learning_observation_counts_by_outcome_hash(learning_state)
    hunter_verified=sum(
        int(stats.get("verified_value_outcomes",0))
        for stats in hunter_state["strategy_stats"].values()
    )
    fully_independent={
        event_id for event_id,bucket in events.items()
        if {"BUILDER","VERIFIER"}.issubset(bucket["roles"])
        and len(bucket["models"])>=2
    }
    missing_learning=sorted(event_ids-learning_ids)
    orphan_learning=sorted(learning_ids-event_ids)
    learning_payload_complete=all(
        learning_observation_counts.get(learning_sources[event_id],0)>=3
        for event_id in event_ids
        if event_id in learning_sources
    ) and not missing_learning
    checks={
      "all_verified_events_have_builder_and_verifier":fully_independent==event_ids,
      "all_verified_events_reach_continuous_learning":not missing_learning,
      "continuous_learning_payloads_are_complete":learning_payload_complete,
      "no_orphan_learning_value_events":not orphan_learning,
      "hunter_value_credit_covers_verified_events":hunter_verified>=len(event_ids),
      "learning_observations_are_verified":all(
          row["evidence_state"]=="VERIFIED"
          for row in learning_state["observations"]
      ),
      "learning_is_advisory_only":True,
    }
    if not event_ids:
        status="NO_VERIFIED_VALUE"
    else:
        status="HEALTHY" if all(checks.values()) else "DEGRADED"

    event_rows=[]
    for event_id in sorted(events):
        bucket=events[event_id]
        event_rows.append({
          "outcome_event_id":event_id,
          "roles":sorted(bucket["roles"]),
          "models":sorted(bucket["models"]),
          "task_kinds":sorted(bucket["task_kinds"]),
          "feedback_record_count":len(bucket["feedback_ids"]),
          "continuous_learning_present":event_id in learning_ids,
          "continuous_learning_observations":0 if event_id not in learning_sources else learning_observation_counts.get(learning_sources[event_id],0),
          "builder_verifier_present":event_id in fully_independent,
        })

    return {
      "schema_version":"1.0.0",
      "integrity_id":"portfolio-verified-learning-integrity-v1",
      "status":status,
      "verified_value_event_count":len(event_ids),
      "independently_verified_event_count":len(fully_independent),
      "continuous_learning_event_count":len(event_ids & learning_ids),
      "hunter_verified_value_outcomes":hunter_verified,
      "model_feedback_sequence":model_feedback_state["sequence"],
      "learning_state_sequence":learning_state["sequence"],
      "hunter_state_sequence":hunter_state["sequence"],
      "missing_continuous_learning_event_ids":missing_learning,
      "orphan_continuous_learning_event_ids":orphan_learning,
      "checks":checks,
      "events":event_rows,
      "authority_granted":False,
      "policy_promoted":False,
      "evidence_upgraded":False,
    }

def main()->None:
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("--hunter-state",type=Path,required=True)
    ap.add_argument("--model-feedback-state",type=Path,required=True)
    ap.add_argument("--learning-state",type=Path,required=True)
    args=ap.parse_args()
    load=lambda p:json.loads(p.read_text(encoding="utf-8"))
    print(json.dumps(build_learning_integrity(
      load(args.hunter_state),load(args.model_feedback_state),load(args.learning_state)
    ),indent=2,sort_keys=True))

if __name__=="__main__":
    main()
