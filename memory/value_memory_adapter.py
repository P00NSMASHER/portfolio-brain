#!/usr/bin/env python3
"""Portfolio adapter for canonical AI Business OS Value Memory.

Actual learning remains in the pinned upstream ValueMemory engine. This module
validates portfolio metadata/provenance and converts only VERIFIED, independently
checked outcome receipts into upstream observation+verification calls.
"""
from __future__ import annotations
import hashlib, json, math, re
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
PIN_PATH=ROOT/"memory"/"AI_BUSINESS_OS_VALUE_MEMORY_PIN.json"

MEM_ID=re.compile(r"^MEM-[A-Z0-9-]{8,}$")
MOUT_ID=re.compile(r"^MOUT-[A-Z0-9-]{8,}$")
PRJ_ID=re.compile(r"^PRJ-[0-9]{3,}$")
OBJ_ID=re.compile(r"^(OBJ-[0-9]{3,}|\*)$")
EVT_ID=re.compile(r"^EVT-[A-Z0-9-]{8,}$")
EVD_ID=re.compile(r"^EVD-[A-Z0-9-]{8,}$")
SHA40=re.compile(r"^[0-9a-f]{40}$")
SHA256P=re.compile(r"^sha256:[0-9a-f]{64}$")
MEMORY_KINDS={"FACT","STRATEGY","ENGINEERING","RESEARCH","COMMERCIAL","PORTFOLIO","SELF_IMPROVEMENT"}
TRUTH_STATES={"OBSERVED","VERIFIED","INFERRED","UNKNOWN","CONTRADICTED","STALE","INVALID"}

class SharedMemoryError(ValueError): pass

def _require(ok: bool,msg: str)->None:
    if not ok: raise SharedMemoryError(msg)

def canonical_hash(value: Any)->str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    return "sha256:"+hashlib.sha256(raw).hexdigest()

def _time(value: str, field: str)->datetime:
    _require(isinstance(value,str) and value,f"{field} required")
    try: dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc: raise SharedMemoryError(f"{field} invalid ISO-8601") from exc
    _require(dt.tzinfo is not None,f"{field} requires timezone")
    return dt

def load_pin()->dict[str,Any]:
    pin=json.loads(PIN_PATH.read_text(encoding="utf-8"))
    validate_pin(pin)
    return pin

def validate_pin(pin: dict[str,Any])->None:
    _require(pin["schema_version"]=="1.0.0","pin schema mismatch")
    _require(pin["integration_mode"]=="PINNED_INTERFACE_ADAPTER","integration mode weakened")
    _require(pin["copied_source_code"] is False,"canonical Value Memory source must not be copied")
    _require(SHA40.fullmatch(pin["source_revision"]) is not None,"invalid source revision")
    _require(SHA40.fullmatch(pin["source_blob_sha"]) is not None,"invalid source blob")
    _require(SHA40.fullmatch(pin["source_test_blob_sha"]) is not None,"invalid source test blob")
    _require(pin["drift_policy"]=={
        "exact_repository_revision_required":True,
        "exact_blob_sha_required":True,
        "on_source_revision_change":"RECONFORM_BEFORE_USE",
        "on_blob_mismatch":"FAIL_CLOSED",
    },"value-memory drift policy weakened")

def validate_memory(record: dict[str,Any])->None:
    required={"schema_version","memory_id","memory_key","version","memory_kind","project_ids",
              "objective_id","scope","content","content_hash","provenance_evidence_ids",
              "truth_state","status","upstream_memory_id"}
    _require(isinstance(record,dict) and set(record)==required,"memory fields must exactly match contract")
    _require(record["schema_version"]=="1.0.0","memory schema mismatch")
    _require(MEM_ID.fullmatch(record["memory_id"]) is not None,"invalid memory_id")
    _require(isinstance(record["memory_key"],str) and record["memory_key"],"memory_key required")
    _require(isinstance(record["version"],str) and record["version"],"version required")
    _require(record["memory_kind"] in MEMORY_KINDS,"invalid memory_kind")
    pids=record["project_ids"]; _require(isinstance(pids,list) and pids and len(pids)==len(set(pids)),"project_ids invalid")
    _require(all(PRJ_ID.fullmatch(x) for x in pids),"invalid project_id")
    _require(OBJ_ID.fullmatch(record["objective_id"]) is not None,"invalid objective_id")
    _require(record["scope"]=="GLOBAL","shared memory scope must be GLOBAL")
    _require(isinstance(record["content"],dict) and record["content"],"content required")
    _require(record["content_hash"]==canonical_hash(record["content"]),"content_hash mismatch")
    evid=record["provenance_evidence_ids"]; _require(isinstance(evid,list) and evid and len(evid)==len(set(evid)),"provenance evidence invalid")
    _require(all(EVD_ID.fullmatch(x) for x in evid),"invalid provenance evidence id")
    _require(record["truth_state"] in TRUTH_STATES,"invalid truth_state")
    _require(record["status"] in {"ACTIVE","RETIRED"},"invalid memory status")
    _require(isinstance(record["upstream_memory_id"],str) and record["upstream_memory_id"],"upstream_memory_id required")

def validate_outcome(outcome: dict[str,Any])->None:
    required={"schema_version","outcome_id","memory_id","event_id","project_id","objective_id",
              "reward","attribution_fraction","evidence_ids","evidence_state","observer_actor_id",
              "verifier_actor_id","verification_report_hash","observed_at","verified_at"}
    _require(isinstance(outcome,dict) and set(outcome)==required,"outcome fields must exactly match contract")
    _require(outcome["schema_version"]=="1.0.0","outcome schema mismatch")
    _require(MOUT_ID.fullmatch(outcome["outcome_id"]) is not None,"invalid outcome_id")
    _require(MEM_ID.fullmatch(outcome["memory_id"]) is not None,"invalid memory_id")
    _require(EVT_ID.fullmatch(outcome["event_id"]) is not None,"invalid event_id")
    _require(PRJ_ID.fullmatch(outcome["project_id"]) is not None,"invalid project_id")
    _require(OBJ_ID.fullmatch(outcome["objective_id"]) is not None,"invalid objective_id")
    reward=float(outcome["reward"]); fraction=float(outcome["attribution_fraction"])
    _require(math.isfinite(reward) and -1<=reward<=1,"reward outside [-1,1]")
    _require(math.isfinite(fraction) and 0<fraction<=1,"attribution_fraction outside (0,1]")
    ids=outcome["evidence_ids"]; _require(isinstance(ids,list) and ids and len(ids)==len(set(ids)),"evidence_ids invalid")
    _require(all(EVD_ID.fullmatch(x) for x in ids),"invalid evidence id")
    _require(outcome["evidence_state"] in TRUTH_STATES,"invalid evidence state")
    _require(isinstance(outcome["observer_actor_id"],str) and outcome["observer_actor_id"],"observer required")
    _time(outcome["observed_at"],"observed_at")
    if outcome["evidence_state"]=="VERIFIED":
        _require(isinstance(outcome["verifier_actor_id"],str) and outcome["verifier_actor_id"],"VERIFIED outcome requires verifier")
        _require(outcome["verifier_actor_id"]!=outcome["observer_actor_id"],"observer cannot verify own outcome")
        _require(isinstance(outcome["verification_report_hash"],str) and SHA256P.fullmatch(outcome["verification_report_hash"]),"VERIFIED outcome requires verification report hash")
        _require(outcome["verified_at"] is not None,"VERIFIED outcome requires verified_at")
        _require(_time(outcome["verified_at"],"verified_at")>=_time(outcome["observed_at"],"observed_at"),"verified_at precedes observed_at")
    else:
        _require(outcome["verifier_actor_id"] is None,"non-VERIFIED outcome cannot claim verifier")
        _require(outcome["verification_report_hash"] is None,"non-VERIFIED outcome cannot claim verification report")
        _require(outcome["verified_at"] is None,"non-VERIFIED outcome cannot claim verified_at")

def upstream_registration_args(record: dict[str,Any])->dict[str,Any]:
    validate_memory(record)
    return {
        "memory_key":record["memory_key"],
        "content":{
            "portfolio_memory_id":record["memory_id"],
            "memory_kind":record["memory_kind"],
            "project_ids":record["project_ids"],
            "truth_state":record["truth_state"],
            "provenance_evidence_ids":record["provenance_evidence_ids"],
            "content":record["content"],
            "content_hash":record["content_hash"],
        },
        "objective":record["objective_id"],
        "scope":"GLOBAL",
        "version":record["version"],
        "memory_id":record["upstream_memory_id"],
    }

def verified_outcome_calls(memory: dict[str,Any], outcome: dict[str,Any])->dict[str,Any]:
    validate_memory(memory); validate_outcome(outcome)
    _require(memory["status"]=="ACTIVE","cannot learn into retired memory")
    _require(outcome["memory_id"]==memory["memory_id"],"outcome memory mismatch")
    _require(outcome["project_id"] in memory["project_ids"],"outcome project outside memory attribution")
    _require(memory["objective_id"] in {"*",outcome["objective_id"]},"outcome objective outside memory scope")
    _require(outcome["evidence_state"]=="VERIFIED","only VERIFIED outcomes may change learned value")
    return {
        "observe":{
            "memory_id":memory["upstream_memory_id"],
            "event_id":outcome["event_id"],
            "reward":float(outcome["reward"]),
            "attribution_fraction":float(outcome["attribution_fraction"]),
            "evidence":{
                "portfolio_outcome_id":outcome["outcome_id"],
                "project_id":outcome["project_id"],
                "objective_id":outcome["objective_id"],
                "evidence_ids":outcome["evidence_ids"],
                "evidence_state":"VERIFIED",
            },
        },
        "verify":{
            "verification_report_hash":outcome["verification_report_hash"].removeprefix("sha256:"),
            "accepted":True,
            "verifier_actor_id":outcome["verifier_actor_id"],
        }
    }

def validate_credit_conservation(outcomes: list[dict[str,Any]])->None:
    totals={}
    for outcome in outcomes:
        validate_outcome(outcome)
        if outcome["evidence_state"]!="VERIFIED": continue
        totals[outcome["event_id"]]=totals.get(outcome["event_id"],0.0)+float(outcome["attribution_fraction"])
    for event_id,total in totals.items():
        _require(total<=1.0+1e-9,f"verified attribution exceeds 1.0 for {event_id}")

def project_upstream_summary(summary: dict[str,Any])->dict[str,Any]:
    required={"verified_count","rejected_count","unverified_count","unique_events","unique_verifiers",
              "effective_weight","mean_reward","confidence","half_life_days","as_of"}
    _require(required<=set(summary),"upstream value summary missing fields")
    for key in ["effective_weight","mean_reward","confidence","half_life_days","as_of"]:
        _require(isinstance(summary[key],(int,float)) and math.isfinite(float(summary[key])),f"invalid summary {key}")
    _require(summary["verified_count"]>=0 and summary["rejected_count"]>=0 and summary["unverified_count"]>=0,"negative summary count")
    _require(-1<=float(summary["mean_reward"])<=1,"mean_reward outside range")
    _require(0<=float(summary["confidence"])<=1,"confidence outside range")
    value_factor=0.5+0.5*float(summary["mean_reward"])*float(summary["confidence"])
    return {
        "verified_outcome_count":int(summary["verified_count"]),
        "speculative_or_unverified_count":int(summary["unverified_count"]),
        "rejected_outcome_count":int(summary["rejected_count"]),
        "effective_verified_weight":float(summary["effective_weight"]),
        "mean_verified_reward":float(summary["mean_reward"]),
        "confidence_from_verified_outcomes":float(summary["confidence"]),
        "value_factor":value_factor,
    }
