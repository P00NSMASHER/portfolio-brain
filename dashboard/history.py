#!/usr/bin/env python3
"""Durable sanitized trend history for Portfolio Brain Command Center."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from dashboard.telemetry import build_operational_telemetry

ROOT=Path(__file__).resolve().parents[1]
MAX_SAMPLES=2160


class HistoryError(ValueError):
    pass


def _req(ok: bool, msg: str) -> None:
    if not ok: raise HistoryError(msg)


def _hash(value: Any) -> str:
    return "sha256:"+hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()


def empty_history() -> dict[str,Any]:
    return {
        "schema_version":"1.0.0",
        "state_id":"portfolio-command-center-history",
        "sequence":0,
        "updated_at":None,
        "samples":[],
    }


def validate_history(state: dict[str,Any]) -> None:
    _req(isinstance(state,dict) and set(state)=={"schema_version","state_id","sequence","updated_at","samples"},"history fields changed")
    _req(state["schema_version"]=="1.0.0" and state["state_id"]=="portfolio-command-center-history","history identity mismatch")
    _req(type(state["sequence"]) is int and state["sequence"]>=0,"history sequence invalid")
    _req(state["updated_at"] is None or isinstance(state["updated_at"],str),"history updated_at invalid")
    _req(isinstance(state["samples"],list) and len(state["samples"])<=MAX_SAMPLES,"history sample capacity exceeded")
    seen=set()
    required={
        "sample_id","hour_bucket","recorded_at","telemetry_hash","bridge_status",
        "open_work","blocked_work","completed_work_cumulative",
        "actual_cost_usd_today","model_calls_today","api_calls_today",
        "github_jobs_today","github_minutes_today","hunter_cycles_cumulative",
        "hunter_retained_cumulative","actions_sent_cumulative","actions_sent_today",
        "failure_count","verified_experiment_outcomes","verified_transfer_outcomes",
        "live_source_count","stale_source_count","fallback_source_count",
    }
    for sample in state["samples"]:
        _req(isinstance(sample,dict) and set(sample)==required,"history sample fields changed")
        _req(sample["sample_id"] not in seen,"duplicate history sample id");seen.add(sample["sample_id"])
        _req(isinstance(sample["recorded_at"],str) and isinstance(sample["hour_bucket"],str),"history timestamps missing")
        _req(sample["telemetry_hash"].startswith("sha256:"),"telemetry hash missing")
        for key in required-{"sample_id","hour_bucket","recorded_at","telemetry_hash","bridge_status"}:
            _req(type(sample[key]) in {int,float},"history metric must be numeric")


def load_history(path: str | Path | None=None) -> dict[str,Any]:
    p=Path(path) if path else ROOT/"dashboard/live/history.json"
    if not p.exists(): return empty_history()
    state=json.loads(p.read_text(encoding="utf-8"));validate_history(state);return state


def make_sample(telemetry: dict[str,Any]) -> dict[str,Any]:
    recorded=telemetry["generated_at"]
    hour=recorded[:13]+":00:00Z"
    sources=telemetry.get("state_source_ages",{})
    statuses=[v.get("status") for v in sources.values()]
    cost=telemetry["cost"]["actual_usage_today"]
    hunter=telemetry.get("hunter",{})
    outcomes=telemetry.get("outcomes",{})
    sample={
        "sample_id":"",
        "hour_bucket":hour,
        "recorded_at":recorded,
        "telemetry_hash":_hash(telemetry),
        "bridge_status":telemetry.get("bridge_status","UNKNOWN"),
        "open_work":telemetry["queue"]["open_count"],
        "blocked_work":telemetry.get("blocked_work_count",0),
        "completed_work_cumulative":telemetry["queue"]["completed_fingerprint_count"],
        "actual_cost_usd_today":cost["cost_usd"],
        "model_calls_today":cost["model_calls"],
        "api_calls_today":cost["api_calls"],
        "github_jobs_today":cost["github_job_starts"],
        "github_minutes_today":cost["github_runner_minutes"],
        "hunter_cycles_cumulative":hunter.get("cycles_cumulative",0),
        "hunter_retained_cumulative":hunter.get("retained_cumulative",0),
        "actions_sent_cumulative":telemetry["actions"]["total_sent"],
        "actions_sent_today":telemetry["actions"]["sent_today"],
        "failure_count":telemetry["failures"]["count"],
        "verified_experiment_outcomes":outcomes.get("verified_experiment_outcomes",0),
        "verified_transfer_outcomes":outcomes.get("verified_transfer_outcomes",0),
        "live_source_count":sum(1 for x in statuses if x=="LIVE"),
        "stale_source_count":sum(1 for x in statuses if x=="STALE"),
        "fallback_source_count":sum(1 for x in statuses if x=="FALLBACK"),
    }
    sample["sample_id"]="HIST-"+hashlib.sha256((hour+"\0"+sample["telemetry_hash"]).encode()).hexdigest()[:20].upper()
    return sample


def append_sample(state: dict[str,Any], telemetry: dict[str,Any]) -> dict[str,Any]:
    validate_history(state)
    sample=make_sample(telemetry)
    out=json.loads(json.dumps(state))
    out["samples"]=[x for x in out["samples"] if x["hour_bucket"]!=sample["hour_bucket"]]
    out["samples"].append(sample)
    out["samples"].sort(key=lambda x:x["recorded_at"])
    out["samples"]=out["samples"][-MAX_SAMPLES:]
    out["sequence"]+=1
    out["updated_at"]=sample["recorded_at"]
    validate_history(out)
    return out


def trend_summary(state: dict[str,Any]) -> dict[str,Any]:
    validate_history(state)
    if not state["samples"]:
        return {"sample_count":0,"latest":None,"change_24h":{}}
    latest=state["samples"][-1]
    target_index=max(0,len(state["samples"])-25)
    prior=state["samples"][target_index]
    metrics=[
        "open_work","blocked_work","completed_work_cumulative","actual_cost_usd_today",
        "model_calls_today","actions_sent_cumulative","failure_count",
        "verified_experiment_outcomes","verified_transfer_outcomes",
    ]
    delta={k:round(float(latest[k])-float(prior[k]),4) for k in metrics}
    return {"sample_count":len(state["samples"]),"latest":latest,"comparison_sample_at":prior["recorded_at"],"change_24h":delta}


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--history",default="dashboard/live/history.json")
    parser.add_argument("--telemetry",default="dashboard/live/telemetry.json")
    parser.add_argument("--output",default="dashboard/live/history.json")
    args=parser.parse_args()
    telemetry_path=Path(args.telemetry)
    telemetry=json.loads(telemetry_path.read_text()) if telemetry_path.exists() else build_operational_telemetry()
    state=load_history(args.history)
    state=append_sample(state,telemetry)
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(state,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"sequence":state["sequence"],"samples":len(state["samples"]),"updated_at":state["updated_at"]},sort_keys=True))


if __name__=="__main__":
    main()
