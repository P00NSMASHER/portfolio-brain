#!/usr/bin/env python3
"""Durable sanitized hourly history for Portfolio Brain command-center trends."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dashboard.operational_telemetry import build_operational_telemetry

ROOT=Path(__file__).resolve().parents[1]
STATE_ID="portfolio-command-center-history"
ARTIFACT_NAME="portfolio-command-center-history"
MAX_POINTS=2160  # 90 days at one point per hour.


class HistoryError(ValueError):pass


def req(ok:bool,msg:str)->None:
    if not ok:raise HistoryError(msg)


def canon(v:Any)->str:
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)


def _time(v:str)->datetime:
    dt=datetime.fromisoformat(v.replace("Z","+00:00"))
    req(dt.tzinfo is not None,"history timestamp requires timezone")
    return dt.astimezone(timezone.utc)


def load_state(path:str|Path|None=None)->dict[str,Any]:
    p=Path(path) if path is not None else ROOT/"dashboard"/"HISTORY_STATE_SEED.json"
    if not p.exists():p=ROOT/"dashboard"/"HISTORY_STATE_SEED.json"
    state=json.loads(p.read_text())
    validate_state(state);return state


def validate_state(state:dict[str,Any])->None:
    req(set(state)=={"schema_version","state_id","sequence","updated_at","points"},"history state fields changed")
    req(state["schema_version"]=="1.0.0" and state["state_id"]==STATE_ID,"history state identity mismatch")
    req(type(state["sequence"]) is int and state["sequence"]>=0,"history sequence invalid")
    if state["updated_at"] is not None:_time(state["updated_at"])
    req(isinstance(state["points"],list) and len(state["points"])<=MAX_POINTS,"history point capacity invalid")
    buckets=set()
    for p in state["points"]:
        fields={"point_id","bucket_at","observed_at","source_commit","metrics","project_activity"}
        req(isinstance(p,dict) and set(p)==fields,"history point fields changed")
        req(p["point_id"].startswith("HPT-"),"history point id invalid")
        _time(p["bucket_at"]);_time(p["observed_at"])
        req(p["bucket_at"] not in buckets,"duplicate history hour bucket");buckets.add(p["bucket_at"])
        req(isinstance(p["source_commit"],str) and p["source_commit"],"history source commit missing")
        m=p["metrics"]
        expected={
          "open_work","queued_work","active_work","completed_work_total","cancelled_work_total",
          "cost_usd_today","model_calls_today","api_calls_today","github_runner_minutes_today",
          "hunter_candidates_total","hunter_retained_total","action_executions_total",
          "failures_total","verified_external_outcomes_total"
        }
        req(set(m)==expected,"history metric vector changed")
        req(all(isinstance(v,(int,float)) and v>=0 for v in m.values()),"history metric invalid")
        req(isinstance(p["project_activity"],dict),"history project activity invalid")


def _bucket(value:str)->str:
    dt=_time(value).replace(minute=0,second=0,microsecond=0)
    return dt.isoformat().replace("+00:00","Z")


def _point(telemetry:dict[str,Any],source_commit:str)->dict[str,Any]:
    q=telemetry["queue"];usage=telemetry["cost"]["actual_usage_today"];h=telemetry["hunter"]["totals"]
    observed=telemetry["generated_at"];bucket=_bucket(observed)
    metrics={
      "open_work":q["open_total"],
      "queued_work":q["counts"]["QUEUED"],
      "active_work":q["counts"]["ACTIVE"],
      "completed_work_total":q["completed_fingerprint_count"],
      "cancelled_work_total":q["counts"]["CANCELLED"],
      "cost_usd_today":round(float(usage["cost_usd"]),6),
      "model_calls_today":int(usage["model_calls"]),
      "api_calls_today":int(usage["api_calls"]),
      "github_runner_minutes_today":int(usage["github_runner_minutes"]),
      "hunter_candidates_total":int(h["candidates"]),
      "hunter_retained_total":int(h["retained"]),
      "action_executions_total":int(telemetry["actions"]["total_sent"]),
      "failures_total":int(telemetry["failures"]["count"]),
      "verified_external_outcomes_total":int(telemetry["verified_external_outcomes"]),
    }
    core={"bucket_at":bucket,"observed_at":observed,"source_commit":source_commit,"metrics":metrics,"project_activity":telemetry["project_activity"]}
    return {"point_id":"HPT-"+hashlib.sha256(canon(core).encode()).hexdigest()[:20].upper(),**core}


def _validate_observation(point:dict[str,Any])->None:
    fields={"point_id","bucket_at","observed_at","source_commit","metrics","project_activity"}
    req(isinstance(point,dict) and set(point)==fields,"history observation fields changed")
    req(point["bucket_at"]==_bucket(point["observed_at"]),"history observation bucket mismatch")
    core={key:point[key] for key in ("bucket_at","observed_at","source_commit","metrics","project_activity")}
    expected="HPT-"+hashlib.sha256(canon(core).encode()).hexdigest()[:20].upper()
    req(point["point_id"]==expected,"history observation identity mismatch")


def replay_history_observation(state:dict[str,Any],point:dict[str,Any])->dict[str,Any]:
    """Replay one exact sanitized observation without trusting upload order."""
    validate_state(state);_validate_observation(point)
    if state["updated_at"] is not None:
        req(_time(point["observed_at"])>_time(state["updated_at"]),"history observation time did not advance")
    out=json.loads(json.dumps(state))
    point=json.loads(json.dumps(point))
    out["points"]=[p for p in out["points"] if p["bucket_at"]!=point["bucket_at"]]
    out["points"].append(point)
    out["points"].sort(key=lambda p:p["bucket_at"])
    out["points"]=out["points"][-MAX_POINTS:]
    out["sequence"]+=1;out["updated_at"]=point["observed_at"]
    validate_state(out);return out


def history_observation(before:dict[str,Any],after:dict[str,Any])->dict[str,Any]|None:
    """Infer a transition only when one native observation reproduces it exactly."""
    validate_state(before);validate_state(after)
    if after["sequence"]!=before["sequence"]+1 or after["updated_at"] is None:
        return None
    candidates=[
      p for p in after["points"]
      if p["observed_at"]==after["updated_at"] and p["bucket_at"]==_bucket(after["updated_at"])
    ]
    if len(candidates)!=1:
        return None
    point=json.loads(json.dumps(candidates[0]))
    try:
        rebuilt=replay_history_observation(before,point)
    except HistoryError:
        return None
    return point if rebuilt==after else None


def append_point(state:dict[str,Any],telemetry:dict[str,Any],*,source_commit:str)->dict[str,Any]:
    return replay_history_observation(state,_point(telemetry,source_commit))


def daily_trends(state:dict[str,Any],days:int=14)->list[dict[str,Any]]:
    validate_state(state)
    if not state["points"]:return []
    by_day:dict[str,list[dict[str,Any]]]={}
    for p in state["points"]:by_day.setdefault(p["bucket_at"][:10],[]).append(p)
    days_sorted=sorted(by_day)[-days:]
    all_days=sorted(by_day)
    out=[]
    for day in days_sorted:
        rows=sorted(by_day[day],key=lambda p:p["bucket_at"]);last=rows[-1]
        idx=all_days.index(day)
        prev_last=None if idx==0 else sorted(by_day[all_days[idx-1]],key=lambda p:p["bucket_at"])[-1]
        def delta(field):
            if prev_last is None:return 0
            return max(0,last["metrics"][field]-prev_last["metrics"][field])
        m=last["metrics"]
        out.append({
          "day":day,
          "open_work_end":m["open_work"],
          "completed_work":delta("completed_work_total"),
          "cancelled_work":delta("cancelled_work_total"),
          "cost_usd":m["cost_usd_today"],
          "model_calls":m["model_calls_today"],
          "api_calls":m["api_calls_today"],
          "github_runner_minutes":m["github_runner_minutes_today"],
          "hunter_candidates":delta("hunter_candidates_total"),
          "hunter_retained":delta("hunter_retained_total"),
          "action_executions":delta("action_executions_total"),
          "new_failures":delta("failures_total"),
          "verified_external_outcomes":delta("verified_external_outcomes_total"),
        })
    return out


def project_momentum(state:dict[str,Any],hours:int=24)->list[dict[str,Any]]:
    validate_state(state)
    if not state["points"]:return []
    latest=state["points"][-1]
    target=_time(latest["bucket_at"]).timestamp()-hours*3600
    baseline=state["points"][0]
    for p in state["points"]:
        if _time(p["bucket_at"]).timestamp()<=target:baseline=p
        else:break
    rows=[]
    for pid,current in sorted(latest["project_activity"].items()):
        before=baseline["project_activity"].get(pid,{})
        rows.append({
          "project_id":pid,
          "open_work":current.get("open_work",0),
          "completed_work_delta":max(0,current.get("completed_work",0)-before.get("completed_work",0)),
          "cancelled_work_delta":max(0,current.get("cancelled_work",0)-before.get("cancelled_work",0)),
          "sent_actions_delta":max(0,current.get("sent_actions",0)-before.get("sent_actions",0)),
          "verified_outcomes_delta":max(0,current.get("verified_outcomes",0)-before.get("verified_outcomes",0)),
          "window_hours":hours,
        })
    return rows


def public_history(state:dict[str,Any])->dict[str,Any]:
    validate_state(state)
    return {
      "schema_version":"1.0.0",
      "history_id":"portfolio-command-center-public-history-v1",
      "sequence":state["sequence"],
      "updated_at":state["updated_at"],
      "point_count":len(state["points"]),
      "daily":daily_trends(state,14),
      "project_momentum":project_momentum(state,24),
      "hourly_points":state["points"][-168:],
      "momentum_definition":"Signals only, not a score: open work plus 24h deltas in completed/cancelled work, sent actions, and verified outcomes.",
    }


def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--state",default="dashboard/live/history_state.json")
    ap.add_argument("--output",default="dashboard/out/history_state.json")
    ap.add_argument("--public-output",default="dashboard/out/history.json")
    ap.add_argument("--source-commit",default=None)
    args=ap.parse_args()
    state=load_state(args.state)
    telemetry=build_operational_telemetry()
    source=args.source_commit or os.environ.get("GITHUB_SHA") or "LOCAL"
    out=append_point(state,telemetry,source_commit=source)
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    pub=public_history(out)
    public_output=Path(args.public_output);public_output.parent.mkdir(parents=True,exist_ok=True)
    public_output.write_text(json.dumps(pub,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"history_points":len(out["points"]),"daily_points":len(pub["daily"]),"sequence":out["sequence"]},sort_keys=True))


if __name__=="__main__":main()
