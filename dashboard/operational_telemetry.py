#!/usr/bin/env python3
"""Sanitized operational telemetry projection for Portfolio Brain."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from experiments.experiment_engine import build_experiment_portfolio
from uncertainty.highest_value_uncertainty import build_snapshot as build_uncertainty_snapshot

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "dashboard" / "live"
USAGE_FIELDS = (
    "cost_usd","input_tokens","output_tokens","model_calls","api_calls",
    "github_job_starts","github_runner_minutes",
)


def load_json(path: str | Path) -> Any:
    p=Path(path)
    if not p.is_absolute():p=ROOT/p
    return json.loads(p.read_text())


def live_json(filename: str, fallback: str) -> dict[str,Any]:
    p=LIVE/filename
    return load_json(p) if p.exists() else load_json(fallback)


def _time(value: str | None) -> datetime | None:
    if not value:return None
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    return dt.astimezone(timezone.utc)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")


def _zero_usage() -> dict[str,Any]:
    return {k:(0.0 if k=="cost_usd" else 0) for k in USAGE_FIELDS}


def _add_usage(total: dict[str,Any], usage: dict[str,Any]) -> None:
    for key in USAGE_FIELDS:total[key]+=usage[key]


def usage_today(cost_state: dict[str,Any], *, at: str) -> dict[str,Any]:
    now=_time(at);assert now is not None
    day=now.date()
    total=_zero_usage()
    for row in cost_state["reservations"]:
        created=_time(row["created_at"])
        if created is None or created.date()!=day:continue
        usage=None
        if row["status"]=="RESERVED":
            expires=_time(row["expires_at"])
            if expires is not None and expires>now:usage=row["estimated_usage"]
        elif row["status"]=="EXPIRED":
            usage=row["estimated_usage"]
        elif row["status"] in {"COMMITTED","OVERAGE"}:
            usage=row["actual_usage"] or row["estimated_usage"]
        if usage is not None:_add_usage(total,usage)
    return total

def actual_usage_today(cost_state: dict[str,Any], *, at: str) -> dict[str,Any]:
    now=_time(at);assert now is not None
    day=now.date();total=_zero_usage()
    for row in cost_state["reservations"]:
        created=_time(row["created_at"])
        if created is None or created.date()!=day:continue
        if row["status"] in {"COMMITTED","OVERAGE"} and row["actual_usage"] is not None:
            _add_usage(total,row["actual_usage"])
    return total


def _age_minutes(value: str | None, at: datetime) -> float | None:
    dt=_time(value)
    if dt is None:return None
    return round(max(0.0,(at-dt).total_seconds()/60),1)


def _queue(scheduler: dict[str,Any]) -> dict[str,Any]:
    states=["QUEUED","ACTIVE","COMPLETE","CANCELLED"]
    counts={s:sum(1 for row in scheduler["work_items"] if row["state"]==s) for s in states}
    items=[]
    for row in sorted(scheduler["work_items"],key=lambda x:(x.get("created_at") or "",x["scheduler_work_id"]),reverse=True)[:32]:
        items.append({
            "work_id":row["scheduler_work_id"],
            "work_type":row["work_type"],
            "state":row["state"],
            "project_ids":row["project_ids"],
            "assigned_agent_id":row["assigned_agent_id"],
            "required_authority":row["required_authority"],
            "consequence":row["consequence"],
            "created_at":row.get("created_at"),
            "lease_generation":row.get("lease_generation"),
            "lease_expires_at":row.get("lease_expires_at"),
            "source_ref":row.get("source_ref"),
        })
    return {
        "sequence":scheduler["sequence"],
        "updated_at":scheduler["updated_at"],
        "counts":counts,
        "open_total":counts["QUEUED"]+counts["ACTIVE"],
        "terminal_total":counts["COMPLETE"]+counts["CANCELLED"],
        "completed_fingerprint_count":len(scheduler["completed_fingerprints"]),
        "items":items,
    }


def _agents(agent_state: dict[str,Any], *, at: datetime) -> dict[str,Any]:
    rows=[]
    for agent_id,row in sorted(agent_state["agents"].items()):
        age=_age_minutes(row["last_heartbeat_at"],at)
        health="NEVER" if age is None else ("LIVE" if age<=180 else ("STALE" if age<=720 else "OFFLINE"))
        rows.append({
            "agent_id":agent_id,
            "role_key":row["role_key"],
            "status":row["status"],
            "heartbeat_health":health,
            "last_heartbeat_at":row["last_heartbeat_at"],
            "heartbeat_age_minutes":age,
            "last_activity_kind":row["last_activity_kind"],
            "source_workflow":row["source_workflow"],
            "source_run_id":row["source_run_id"],
            "recent_work_ids":row["recent_work_ids"],
        })
    return {
        "sequence":agent_state["sequence"],
        "updated_at":agent_state["updated_at"],
        "live":sum(1 for x in rows if x["heartbeat_health"]=="LIVE"),
        "stale":sum(1 for x in rows if x["heartbeat_health"]=="STALE"),
        "offline":sum(1 for x in rows if x["heartbeat_health"]=="OFFLINE"),
        "never":sum(1 for x in rows if x["heartbeat_health"]=="NEVER"),
        "agents":rows,
        "recent_events":agent_state["recent_events"][-25:],
    }


def _last_cycles(runtime: dict[str,Any],hunter: dict[str,Any],scheduler: dict[str,Any]) -> dict[str,Any]:
    rows=[]
    for row in runtime.get("recent_cycles",[]):
        if row.get("status")=="PASS":
            rows.append({"subsystem":"runtime","cycle_id":row["cycle_id"],"finished_at":row["finished_at"],"status":"PASS"})
    for row in hunter.get("recent_cycles",[]):
        rows.append({"subsystem":"hunter","cycle_id":row["cycle_id"],"finished_at":row["finished_at"],"status":"PASS"})
    for row in scheduler.get("recent_cycles",[]):
        rows.append({"subsystem":"scheduler","cycle_id":row["cycle_id"],"finished_at":row["finished_at"],"status":"PASS"})
    rows.sort(key=lambda x:x["finished_at"],reverse=True)
    latest={}
    for row in rows:
        latest.setdefault(row["subsystem"],row)
    return {"latest_overall":rows[0] if rows else None,"by_subsystem":latest,"recent":rows[:20]}


def _verified_outcomes() -> tuple[int,dict[str,int]]:
    experiment=load_json("experiments/EXPERIMENT_OUTCOME_LEDGER.json")["outcomes"]
    transfer=load_json("transfer/TRANSFER_LEDGER.json")["outcomes"]
    plans=build_experiment_portfolio(build_uncertainty_snapshot())["plans"]
    by_exp={p["experiment_id"]:p["project_ids"] for p in plans}
    by_project={f"PRJ-{i:03d}":0 for i in range(12)}
    count=0
    for row in experiment:
        if row.get("evidence_state")=="VERIFIED" and row.get("result") in {"PASSED","FAILED"}:
            count+=1
            for pid in by_exp.get(row.get("experiment_id"),[]):by_project[pid]=by_project.get(pid,0)+1
    for row in transfer:
        if row.get("evidence_state")=="VERIFIED" and row.get("result") in {"VERIFIED_EFFECTIVE","VERIFIED_NO_VALUE"}:
            count+=1
            pid=row.get("target_project_id")
            if pid:by_project[pid]=by_project.get(pid,0)+1
    return count,by_project


def build_operational_telemetry(*, at: str | None=None) -> dict[str,Any]:
    if at is None and (LIVE/"state_sources.json").exists():
        at=load_json(LIVE/"state_sources.json").get("generated_at")
    # Local/static validation has no live-state receipt. Use a deterministic
    # epoch rather than wall-clock time so repeated renders hash identically.
    at=at or "1970-01-01T00:00:00Z"
    now=_time(at);assert now is not None
    scheduler=live_json("scheduler_state.json","scheduler/SCHEDULER_STATE_SEED.json")
    hunter=live_json("hunter_state.json","hunting/HUNTER_STATE_SEED.json")
    cost=live_json("cost_state.json","cost_governor/COST_STATE_SEED.json")
    notifications=live_json("notification_state.json","notifications/NOTIFICATION_STATE_SEED.json")
    agents=live_json("agent_heartbeat_state.json","agents/AGENT_HEARTBEAT_STATE_SEED.json")
    runtime_path=LIVE/"runtime_state.json"
    runtime=load_json(runtime_path) if runtime_path.exists() else {"recent_cycles":[],"sequence":0,"updated_at":None}
    sources=load_json(LIVE/"state_sources.json") if (LIVE/"state_sources.json").exists() else {"sources":{}}
    action_ledger=load_json("action_engine/GMAIL_GATEWAY_LEDGER.json")
    cost_policy=load_json("cost_governor/COST_GOVERNOR_POLICY.json")

    queue=_queue(scheduler)
    agent_view=_agents(agents,at=now)
    accounted=usage_today(cost,at=at)
    actual=actual_usage_today(cost,at=at)
    ceilings=cost_policy["portfolio_ceiling"]
    utilization={
        key:{
            "used":accounted[key],
            "actual":actual[key],
            "ceiling":ceilings[key],
            "fraction":0 if ceilings[key]==0 else round(accounted[key]/ceilings[key],4),
        } for key in USAGE_FIELDS
    }

    recent_actions=[
        {
            "action_id":row["action_id"],"project_id":row["project_id"],"action_type":row["action_type"],
            "status":row["status"],"sent_at":row["sent_at"],"evidence_refs":row["evidence_refs"],
        }
        for row in sorted(action_ledger["executions"],key=lambda x:x["sent_at"],reverse=True)[:20]
    ]

    failures=[]
    for row in scheduler["work_items"]:
        if row["state"]=="CANCELLED":
            failures.append({"kind":"SCHEDULER_CANCELLED","at":row.get("created_at"),"ref":row["scheduler_work_id"],"project_ids":row["project_ids"]})
    for row in cost["reservations"]:
        if row["status"]=="OVERAGE":
            failures.append({"kind":"COST_OVERAGE","at":row.get("committed_at") or row["created_at"],"ref":row["reservation_id"],"project_ids":row["project_ids"]})
    for row in notifications["alert_records"]:
        if row["status"]=="ACTIVE" and row["kind"] in {"AUTONOMOUS_WORK_FAILURE","COST_HARD_STOP","VERIFIED_NEGATIVE_OUTCOME"}:
            failures.append({"kind":row["kind"],"at":row["last_seen_at"],"ref":row["alert_id"],"project_ids":row["project_ids"]})
    failures.sort(key=lambda x:x.get("at") or "",reverse=True)

    verified_count,verified_by_project=_verified_outcomes()
    project_activity={}
    for i in range(12):
        pid=f"PRJ-{i:03d}"
        works=[row for row in scheduler["work_items"] if pid in row["project_ids"]]
        project_activity[pid]={
            "open_work":sum(1 for row in works if row["state"] in {"QUEUED","ACTIVE"}),
            "completed_work":sum(1 for row in works if row["state"]=="COMPLETE"),
            "cancelled_work":sum(1 for row in works if row["state"]=="CANCELLED"),
            "sent_actions":sum(1 for row in action_ledger["executions"] if row["project_id"]==pid and row["status"]=="SENT"),
            "verified_outcomes":verified_by_project.get(pid,0),
        }

    hunter_totals={
        field:sum(stats[field] for stats in hunter["strategy_stats"].values())
        for field in ("cycles","queries","candidates","inspected","retained","experiment_proposals","verified_value_outcomes")
    }

    return {
        "schema_version":"1.0.0",
        "telemetry_id":"portfolio-operational-telemetry-v1",
        "generated_at":at,
        "authority_class":"OBSERVE",
        "queue":queue,
        "agents":agent_view,
        "cost":{
            "state_sequence":cost["sequence"],
            "state_updated_at":cost["updated_at"],
            "actual_usage_today":actual,
            "budget_accounted_usage_today":accounted,
            "utilization":utilization,
            "recent_decisions":cost["recent_decisions"][-20:],
            "recent_reservations":[
                {
                    "reservation_id":row["reservation_id"],"resource_kind":row["resource_kind"],
                    "project_ids":row["project_ids"],"provider_id":row["provider_id"],"model_id":row["model_id"],
                    "workflow_id":row["workflow_id"],"job_id":row["job_id"],"status":row["status"],
                    "created_at":row["created_at"],"committed_at":row["committed_at"],
                    "actual_usage":row["actual_usage"],
                } for row in cost["reservations"][-20:]
            ],
        },
        "actions":{"total_sent":len(action_ledger["executions"]),"recent":recent_actions},
        "failures":{"count":len(failures),"recent":failures[:20]},
        "cycles":_last_cycles(runtime,hunter,scheduler),
        "hunter":{"totals":hunter_totals,"state_sequence":hunter["sequence"],"updated_at":hunter["updated_at"]},
        "notifications":{
            "state_sequence":notifications["sequence"],"updated_at":notifications["updated_at"],
            "active_alerts":sum(1 for x in notifications["alert_records"] if x["status"]=="ACTIVE"),
            "recent_deliveries":notifications["recent_deliveries"][-20:],
        },
        "verified_external_outcomes":verified_count,
        "project_activity":project_activity,
        "state_source_ages":{
            name:{
                "status":src.get("status"),"age_minutes":src.get("age_minutes"),
                "source_run_id":src.get("source_run_id"),"artifact_created_at":src.get("artifact_created_at"),
            } for name,src in sources.get("sources",{}).items()
        },
    }


if __name__=="__main__":
    print(json.dumps(build_operational_telemetry(),indent=2,sort_keys=True))
