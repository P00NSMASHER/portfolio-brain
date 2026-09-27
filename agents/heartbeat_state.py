#!/usr/bin/env python3
"""Durable sanitized heartbeat telemetry for persistent Portfolio Brain roles."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_ID = "portfolio-agent-heartbeat-state"
ARTIFACT_NAME = "portfolio-agent-heartbeat-state"
MAX_EVENTS = 200
MAX_WORK_IDS = 12


class AgentHeartbeatError(ValueError):
    pass


def req(ok: bool, message: str) -> None:
    if not ok:
        raise AgentHeartbeatError(message)


def canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _time(value: str, field: str) -> datetime:
    req(isinstance(value, str) and value, f"{field} required")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AgentHeartbeatError(f"{field} invalid ISO-8601") from exc
    req(dt.tzinfo is not None, f"{field} requires timezone")
    return dt.astimezone(timezone.utc)


def registry() -> dict[str, dict[str, Any]]:
    doc = json.loads((ROOT / "agents" / "AGENT_REGISTRY.json").read_text())
    return {row["agent_id"]: row for row in doc["roles"]}


def seed_state() -> dict[str, Any]:
    reg = registry()
    return {
        "schema_version": "1.0.0",
        "state_id": STATE_ID,
        "sequence": 0,
        "updated_at": None,
        "agents": {
            agent_id: {
                "role_key": role["role_key"],
                "status": role["status"],
                "last_heartbeat_at": None,
                "last_activity_kind": None,
                "source_workflow": None,
                "source_run_id": None,
                "recent_work_ids": [],
            }
            for agent_id, role in sorted(reg.items())
        },
        "recent_events": [],
    }


def validate_state(state: dict[str, Any]) -> None:
    reg = registry()
    required = {"schema_version", "state_id", "sequence", "updated_at", "agents", "recent_events"}
    req(isinstance(state, dict) and set(state) == required, "agent heartbeat state fields changed")
    req(state["schema_version"] == "1.0.0" and state["state_id"] == STATE_ID, "agent heartbeat state identity mismatch")
    req(type(state["sequence"]) is int and state["sequence"] >= 0, "agent heartbeat sequence invalid")
    if state["updated_at"] is not None:
        _time(state["updated_at"], "updated_at")
    req(isinstance(state["agents"], dict) and set(state["agents"]) == set(reg), "agent heartbeat coverage mismatch")
    for agent_id, row in state["agents"].items():
        fields = {
            "role_key", "status", "last_heartbeat_at", "last_activity_kind",
            "source_workflow", "source_run_id", "recent_work_ids",
        }
        req(isinstance(row, dict) and set(row) == fields, f"{agent_id} heartbeat fields changed")
        req(row["role_key"] == reg[agent_id]["role_key"], f"{agent_id} role key drifted")
        req(row["status"] == reg[agent_id]["status"], f"{agent_id} status drifted")
        if row["last_heartbeat_at"] is not None:
            _time(row["last_heartbeat_at"], f"{agent_id}.last_heartbeat_at")
        for key in ("last_activity_kind", "source_workflow", "source_run_id"):
            req(row[key] is None or (isinstance(row[key], str) and 1 <= len(row[key]) <= 160), f"{agent_id} {key} invalid")
        req(
            isinstance(row["recent_work_ids"], list)
            and len(row["recent_work_ids"]) <= MAX_WORK_IDS
            and len(row["recent_work_ids"]) == len(set(row["recent_work_ids"]))
            and all(isinstance(x, str) and 1 <= len(x) <= 160 for x in row["recent_work_ids"]),
            f"{agent_id} recent work ids invalid",
        )
    req(isinstance(state["recent_events"], list) and len(state["recent_events"]) <= MAX_EVENTS, "heartbeat event history invalid")
    seen = set()
    for event in state["recent_events"]:
        fields = {"event_id", "agent_id", "at", "activity_kind", "source_workflow", "source_run_id", "work_ids"}
        req(isinstance(event, dict) and set(event) == fields, "heartbeat event fields changed")
        req(event["event_id"] not in seen and event["event_id"].startswith("AHB-"), "heartbeat event id invalid")
        seen.add(event["event_id"])
        req(event["agent_id"] in reg, "heartbeat event unknown agent")
        _time(event["at"], "heartbeat event at")
        for key in ("activity_kind", "source_workflow", "source_run_id"):
            req(isinstance(event[key], str) and 1 <= len(event[key]) <= 160, f"heartbeat event {key} invalid")
        req(
            isinstance(event["work_ids"], list)
            and len(event["work_ids"]) <= MAX_WORK_IDS
            and len(event["work_ids"]) == len(set(event["work_ids"]))
            and all(isinstance(x, str) and 1 <= len(x) <= 160 for x in event["work_ids"]),
            "heartbeat event work ids invalid",
        )


def load_state(path: str | Path | None = None) -> dict[str, Any]:
    if path is not None and Path(path).exists():
        state = json.loads(Path(path).read_text())
    else:
        seed_path = ROOT / "agents" / "AGENT_HEARTBEAT_STATE_SEED.json"
        state = json.loads(seed_path.read_text()) if seed_path.exists() else seed_state()
    validate_state(state)
    return state


def heartbeat(
    state: dict[str, Any],
    *,
    agent_ids: list[str],
    activity_kind: str,
    source_workflow: str,
    source_run_id: str,
    work_ids_by_agent: dict[str, list[str]] | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    validate_state(state)
    reg = registry()
    req(agent_ids and len(agent_ids) == len(set(agent_ids)), "agent ids required and unique")
    req(all(agent_id in reg for agent_id in agent_ids), "unknown heartbeat agent")
    req(isinstance(activity_kind, str) and activity_kind, "activity kind required")
    req(isinstance(source_workflow, str) and source_workflow, "source workflow required")
    req(isinstance(source_run_id, str) and source_run_id, "source run id required")
    at = at or _now()
    _time(at, "heartbeat at")
    work_ids_by_agent = work_ids_by_agent or {}

    out = json.loads(json.dumps(state))
    for agent_id in sorted(agent_ids):
        work_ids = list(dict.fromkeys(work_ids_by_agent.get(agent_id, [])))[:MAX_WORK_IDS]
        row = out["agents"][agent_id]
        row["last_heartbeat_at"] = at
        row["last_activity_kind"] = activity_kind
        row["source_workflow"] = source_workflow
        row["source_run_id"] = source_run_id
        row["recent_work_ids"] = list(dict.fromkeys([*work_ids, *row["recent_work_ids"]]))[:MAX_WORK_IDS]
        event_core = {
            "agent_id": agent_id,
            "at": at,
            "activity_kind": activity_kind,
            "source_workflow": source_workflow,
            "source_run_id": source_run_id,
            "work_ids": work_ids,
        }
        event_id = "AHB-" + hashlib.sha256(canon(event_core).encode()).hexdigest()[:20].upper()
        event = {"event_id": event_id, **event_core}
        if not any(existing["event_id"] == event_id for existing in out["recent_events"]):
            out["recent_events"].append(event)

    out["recent_events"] = out["recent_events"][-MAX_EVENTS:]
    out["sequence"] += 1
    out["updated_at"] = at
    validate_state(out)
    return out


def _selected_work(path: Path) -> tuple[list[str], dict[str, list[str]]]:
    if not path.exists():
        return [], {}
    rows = json.loads(path.read_text())
    req(isinstance(rows, list), "selected work payload must be list")
    ids = []
    work: dict[str, list[str]] = {}
    for row in rows:
        agent_id = row.get("assigned_agent_id")
        if agent_id is None:
            continue
        ids.append(agent_id)
        wid = row.get("scheduler_work_id") or row.get("source_ref") or row.get("fingerprint")
        if isinstance(wid, str) and wid:
            work.setdefault(agent_id, []).append(wid)
    return list(dict.fromkeys(ids)), work


def main() -> None:
    parser = argparse.ArgumentParser(description="Update durable agent heartbeat telemetry")
    parser.add_argument("--state", default="agents/live/agent_heartbeat_state.json")
    parser.add_argument("--output", default="agents/out/agent_heartbeat_state.json")
    parser.add_argument("--agent-id", action="append", default=[])
    parser.add_argument("--all-registered", action="store_true")
    parser.add_argument("--selected-work", default=None)
    parser.add_argument("--activity-kind", required=True)
    parser.add_argument("--source-workflow", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--at", default=None)
    args = parser.parse_args()

    state = load_state(args.state)
    selected_agents: list[str] = []
    work_ids: dict[str, list[str]] = {}
    if args.selected_work:
        selected_agents, work_ids = _selected_work(Path(args.selected_work))
    all_registered = sorted(registry()) if args.all_registered else []
    agent_ids = list(dict.fromkeys([*all_registered, *args.agent_id, *selected_agents]))
    out = heartbeat(
        state,
        agent_ids=agent_ids,
        activity_kind=args.activity_kind,
        source_workflow=args.source_workflow,
        source_run_id=args.source_run_id,
        work_ids_by_agent=work_ids,
        at=args.at,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"sequence": out["sequence"], "agents_heartbeated": agent_ids}, sort_keys=True))


if __name__ == "__main__":
    main()
