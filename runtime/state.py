#!/usr/bin/env python3
"""Durable sanitized runtime-state helpers for Step 8."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]

class RuntimeStateError(ValueError): pass

def canonical_hash(value: Any)->str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    return "sha256:"+hashlib.sha256(raw).hexdigest()

def load_json(path: Path)->dict[str,Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def bootstrap_state(*, now: str)->dict[str,Any]:
    cursors=load_json(ROOT/"adapters"/"cursors"/"repositories.json")["repositories"]
    return {
      "schema_version":"1.0.0",
      "state_id":"portfolio-runtime-state",
      "sequence":0,
      "updated_at":now,
      "last_cycle_id":None,
      "repositories":{
        rid:{
          "source_ref":item["source_ref"],
          "cursor_sha":item["cursor_sha"],
          "status":item["status"],
          "observed_at":None,
        } for rid,item in sorted(cursors.items())
      },
      "recent_cycles":[],
      "daily_learning_state":None,
      "weekly_synthesis":None,
    }

def validate_state(state: dict[str,Any])->None:
    required={"schema_version","state_id","sequence","updated_at","last_cycle_id","repositories",
              "recent_cycles","daily_learning_state","weekly_synthesis"}
    if not isinstance(state,dict) or set(state)!=required:
        raise RuntimeStateError("runtime state fields changed")
    if state["schema_version"]!="1.0.0" or state["state_id"]!="portfolio-runtime-state":
        raise RuntimeStateError("runtime state identity mismatch")
    if not isinstance(state["sequence"],int) or state["sequence"]<0:
        raise RuntimeStateError("runtime state sequence invalid")
    repos=state["repositories"]
    if not isinstance(repos,dict) or set(repos)!={f"REPO-{i:03d}" for i in range(1,9)}:
        raise RuntimeStateError("runtime repository state set mismatch")
    for rid,item in repos.items():
        if set(item)!={"source_ref","cursor_sha","status","observed_at"}:
            raise RuntimeStateError(f"{rid} runtime cursor fields changed")
        sha=item["cursor_sha"]
        if not isinstance(sha,str) or len(sha)!=40:
            raise RuntimeStateError(f"{rid} cursor is not exact SHA")
        int(sha,16)
        if item["status"] not in {"CURRENT","BLOCKED_HISTORICAL_ONLY"}:
            raise RuntimeStateError(f"{rid} invalid runtime cursor status")
    if repos["REPO-006"]["status"]!="BLOCKED_HISTORICAL_ONLY":
        raise RuntimeStateError("REPO-006 must remain blocked historical-only")
    if not isinstance(state["recent_cycles"],list) or len(state["recent_cycles"])>20:
        raise RuntimeStateError("recent cycle history invalid")

def advance_cycle(state: dict[str,Any], receipt: dict[str,Any])->dict[str,Any]:
    validate_state(state)
    updated=json.loads(json.dumps(state))
    updated["sequence"]+=1
    updated["updated_at"]=receipt["finished_at"]
    updated["last_cycle_id"]=receipt["cycle_id"]
    history=[*updated["recent_cycles"],{
      "cycle_id":receipt["cycle_id"],
      "mode":receipt["mode"],
      "finished_at":receipt["finished_at"],
      "status":receipt["status"],
      "receipt_hash":receipt["receipt_hash"],
    }]
    updated["recent_cycles"]=history[-20:]
    for obs in receipt.get("observations",[]):
        rid=obs["repository_id"]
        if obs["status"] in {"CHANGED","UNCHANGED","INITIALIZED"} and obs.get("current_sha"):
            updated["repositories"][rid]["cursor_sha"]=obs["current_sha"]
            updated["repositories"][rid]["status"]="CURRENT"
            updated["repositories"][rid]["observed_at"]=receipt["finished_at"]
    validate_state(updated)
    return updated
