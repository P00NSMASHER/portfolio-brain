#!/usr/bin/env python3
"""Sanitized operational telemetry for Portfolio Brain Command Center v4."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "dashboard" / "live"
USAGE_FIELDS = (
    "cost_usd","input_tokens","output_tokens","model_calls",
    "api_calls","github_job_starts","github_runner_minutes",
)


def load_json(path: str | Path) -> dict[str, Any]:
    p=Path(path)
    if not p.is_absolute(): p=ROOT/p
    return json.loads(p.read_text(encoding="utf-8"))


def live_json(filename: str, fallback: str) -> dict[str, Any]:
    p=LIVE/filename
    return load_json(p) if p.exists() else load_json(fallback)


def _time(value: str | None) -> datetime | None:
    if not value: return None
    parsed=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.astimezone(timezone.utc).isoformat().replace("+00:00","Z")


def _usage_zero() -> dict[str, float | int]:
    return {
        "cost_usd":0.0,"input_tokens":0,"output_tokens":0,"model_calls":0,
        "api_calls":0,"github_job_starts":0,"github_runner_minutes":0,
    }


def _add_usage(target: dict[str, Any], source: dict[str, Any] | None) -> None:
    if not source: return
    for field in USAGE_FIELDS:
        target[field]+=source.get(field,0)


def _latest(values: list[str | None]) -> str | None:
    parsed=[(_time(v),v) for v in values if v]
    parsed=[x for x in parsed if x[0] is not None]
    return None if not parsed else max(parsed,key=lambda x:x[0])[1]


def build_operational_telemetry(*, now: datetime | None = None) -> dict[str, Any]:
    sources=load_json(LIVE/"state_sources.json") if (LIVE/"state_sources.json").exists() else {
        "generated_at":None,"bridge_status":"FALLBACK","sources":{}
    }
    now=now or _time(sources.get("generated_at")) or datetime.now(timezone.utc)
    scheduler=live_json("scheduler_state.json","scheduler/SCHEDULER_STATE_SEED.json")
    hunter=live_json("hunter_state.json","hunting/HUNTER_STATE_SEED.json")
    cost=live_json("cost_state.json","cost_governor/COST_STATE_SEED.json")
    notifications=live_json("notification_state.json","notifications/NOTIFICATION_STATE_SEED.json")
    agents_seed=load_json("agents/AGENT_STATE_SEED.json")
    agent_registry=load_json("agents/AGENT_REGISTRY.json")
    action_ledger=load_json("action_engine/GMAIL_GATEWAY_LEDGER.json")
    cost_policy=load_json("cost_governor/COST_GOVERNOR_POLICY.json")
    runtime_path=LIVE/"runtime_state.json"
    runtime=load_json(runtime_path) if runtime_path.exists() else None

    work_items=list(scheduler.get("work_items",[]))
    queue_counts={state:0 for state in ["QUEUED","ACTIVE","COMPLETE","CANCELLED"]}
    for item in work_items:
        state=item.get("state","UNKNOWN")
        queue_counts[state]=queue_counts.get(state,0)+1
    open_items=[w for w in work_items if w.get("state") in {"QUEUED","ACTIVE"}]
    open_items.sort(key=lambda w:(str(w.get("created_at") or ""),str(w.get("scheduler_work_id") or "")),reverse=True)
    queue_items=[{
        "work_id":w.get("scheduler_work_id"),
        "work_type":w.get("work_type"),
        "state":w.get("state"),
        "project_ids":w.get("project_ids",[]),
        "assigned_agent_id":w.get("assigned_agent_id"),
        "required_authority":w.get("required_authority"),
        "consequence":w.get("consequence"),
        "created_at":w.get("created_at"),
        "lease_generation":w.get("lease_generation"),
        "lease_expires_at":w.get("lease_expires_at"),
        "source_ref":w.get("source_ref"),
    } for w in open_items[:32]]

    today=now.date().isoformat()
    actual=_usage_zero(); reserved=_usage_zero()
    cost_failures=[]
    for row in cost.get("reservations",[]):
        created=_time(row.get("created_at"))
        if created is None or created.date().isoformat()!=today: continue
        if row.get("status") in {"COMMITTED","OVERAGE"}:
            _add_usage(actual,row.get("actual_usage") or row.get("estimated_usage"))
        elif row.get("status")=="RESERVED":
            _add_usage(reserved,row.get("estimated_usage"))
        if row.get("status")=="OVERAGE":
            cost_failures.append({
                "kind":"COST_OVERAGE","reservation_id":row.get("reservation_id"),
                "resource_kind":row.get("resource_kind"),"created_at":row.get("created_at"),
            })
    ceiling=cost_policy["portfolio_ceiling"]
    utilization={
        field:(0.0 if not ceiling[field] else round(100*float(actual[field])/float(ceiling[field]),2))
        for field in USAGE_FIELDS
    }

    actions=sorted(action_ledger.get("executions",[]),key=lambda x:str(x.get("sent_at") or ""),reverse=True)
    recent_actions=[{
        "action_id":x.get("action_id"),"project_id":x.get("project_id"),
        "action_type":x.get("action_type"),"status":x.get("status"),
        "sent_at":x.get("sent_at"),"evidence_refs":x.get("evidence_refs",[])[:6],
    } for x in actions[:12]]
    actions_today=sum(1 for x in actions if (_time(x.get("sent_at")) or datetime.min.replace(tzinfo=timezone.utc)).date().isoformat()==today)

    activity_by_agent: dict[str,list[str | None]]={}
    for w in work_items:
        aid=w.get("assigned_agent_id")
        if aid: activity_by_agent.setdefault(aid,[]).append(w.get("created_at"))
    if hunter.get("updated_at"): activity_by_agent.setdefault("AGT-HUNTER",[]).append(hunter.get("updated_at"))
    if runtime and runtime.get("updated_at"): activity_by_agent.setdefault("AGT-PORTFOLIO-MANAGER",[]).append(runtime.get("updated_at"))
    state_by_agent={a["agent_id"]:a for a in agents_seed.get("agents",[])}
    agent_telemetry=[]
    for role in agent_registry["roles"]:
        state=state_by_agent.get(role["agent_id"],{})
        heartbeat=state.get("last_heartbeat_at")
        if isinstance(heartbeat,(int,float)):
            heartbeat=_iso(datetime.fromtimestamp(float(heartbeat),tz=timezone.utc))
        elif heartbeat is not None:
            heartbeat=str(heartbeat)
        last_activity=_latest(activity_by_agent.get(role["agent_id"],[]))
        agent_telemetry.append({
            "agent_id":role["agent_id"],"name":role["display_name"],"role_key":role["role_key"],
            "registry_status":state.get("status",role.get("status")),
            "reported_heartbeat_at":heartbeat,
            "heartbeat_status":"REPORTED" if heartbeat else "UNAVAILABLE",
            "last_evidence_activity_at":last_activity,
            "activity_evidence_available":last_activity is not None,
            "open_work_count":sum(1 for w in open_items if w.get("assigned_agent_id")==role["agent_id"]),
        })

    failures=[]
    for w in work_items:
        if w.get("state")=="CANCELLED":
            failures.append({"kind":"SCHEDULER_CANCELLED","entity_id":w.get("scheduler_work_id"),"at":w.get("created_at")})
    failures.extend({"kind":x["kind"],"entity_id":x["reservation_id"],"at":x["created_at"]} for x in cost_failures)
    for alert in notifications.get("alert_records",[]):
        if alert.get("status")=="ACTIVE" and alert.get("severity") in {"HIGH","CRITICAL"}:
            failures.append({"kind":f'ALERT_{alert.get("kind")}',"entity_id":alert.get("alert_id"),"at":alert.get("last_seen_at")})
    if runtime:
        for cycle in runtime.get("recent_cycles",[]):
            if cycle.get("status") not in {None,"PASS"}:
                failures.append({"kind":"RUNTIME_CYCLE_FAILURE","entity_id":cycle.get("cycle_id"),"at":cycle.get("finished_at")})

    successful_cycles=[]
    if runtime:
        successful_cycles += [{
            "subsystem":"runtime","cycle_id":c.get("cycle_id"),"finished_at":c.get("finished_at")
        } for c in runtime.get("recent_cycles",[]) if c.get("status")=="PASS"]
    successful_cycles += [{
        "subsystem":"scheduler","cycle_id":c.get("cycle_id"),"finished_at":c.get("finished_at")
    } for c in scheduler.get("recent_cycles",[])]
    successful_cycles += [{
        "subsystem":"hunter","cycle_id":c.get("cycle_id"),"finished_at":c.get("finished_at")
    } for c in hunter.get("recent_cycles",[])]
    successful_cycles=[x for x in successful_cycles if x.get("finished_at")]
    successful_cycles.sort(key=lambda x:str(x["finished_at"]),reverse=True)
    last_cycle=successful_cycles[0] if successful_cycles else None

    source_ages={k:{
        "status":v.get("status"),"age_minutes":v.get("age_minutes"),
        "artifact_created_at":v.get("artifact_created_at"),"source_run_id":v.get("source_run_id"),
    } for k,v in sources.get("sources",{}).items()}

    return {
        "schema_version":"1.0.0",
        "telemetry_id":"portfolio-command-center-telemetry-v1",
        "generated_at":_iso(now),
        "authority_class":"OBSERVE",
        "queue":{
            "total_items":len(work_items),"open_count":len(open_items),
            "completed_fingerprint_count":len(scheduler.get("completed_fingerprints",[])),
            "state_counts":queue_counts,"items":queue_items,
        },
        "agents":{"items":agent_telemetry},
        "cost":{
            "actual_usage_today":actual,"reserved_usage_now":reserved,
            "portfolio_ceiling":ceiling,"actual_utilization_percent":utilization,
        },
        "actions":{"sent_today":actions_today,"total_sent":len(actions),"recent":recent_actions},
        "failures":{"count":len(failures),"recent":failures[-20:]},
        "last_successful_autonomous_cycle":last_cycle,
        "state_source_ages":source_ages,
    }


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",default="dashboard/live/telemetry.json")
    args=parser.parse_args()
    telemetry=build_operational_telemetry()
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(telemetry,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({
        "open_work":telemetry["queue"]["open_count"],
        "failures":telemetry["failures"]["count"],
        "actual_cost_usd":telemetry["cost"]["actual_usage_today"]["cost_usd"],
        "actions_today":telemetry["actions"]["sent_today"],
    },sort_keys=True))


if __name__=="__main__":
    main()
